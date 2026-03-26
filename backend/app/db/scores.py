"""Score calculation with transactional stale-marking.

Wraps score recalculation in a transaction that marks affected rows stale
before computing and fresh after success.  If recalculation fails, the
rows stay stale so the UI can surface a warning to the user.

Flow:  mark stale -> recalculate -> mark fresh (on success only)
"""
from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ._pool import _acquire

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _score_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert an entity_scores row to a JSON-safe dict."""
    d = dict(row)
    for field in ("entity_id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
    return d


# ---------------------------------------------------------------------------
# Stale marking
# ---------------------------------------------------------------------------

async def db_mark_scores_stale(
    campaign_id: str,
    entity_id: str | None = None,
) -> int:
    """Set ``score_stale = TRUE`` for affected entity_scores rows.

    Args:
        campaign_id: Target campaign UUID.
        entity_id:   Optional single entity to scope the update.

    Returns:
        Number of rows marked stale.
    """
    if entity_id:
        sql = (
            "UPDATE playbook.entity_scores "
            "SET score_stale = TRUE "
            "WHERE campaign_id = $1::uuid AND entity_id = $2::uuid"
        )
        args: tuple[str, ...] = (campaign_id, entity_id)
    else:
        sql = (
            "UPDATE playbook.entity_scores "
            "SET score_stale = TRUE "
            "WHERE campaign_id = $1::uuid"
        )
        args = (campaign_id,)

    async with _acquire() as conn:
        result = await conn.execute(sql, *args)
    # asyncpg returns e.g. "UPDATE 5"
    return int(result.split()[-1])


async def db_mark_scores_fresh(
    campaign_id: str,
    entity_id: str | None = None,
) -> int:
    """Set ``score_stale = FALSE`` for entities that have backing data.

    Only marks rows fresh when the entity has validation results in
    completed jobs **or** entity_attribute_assignments for the campaign.
    Entities without any data remain stale.

    Args:
        campaign_id: Target campaign UUID.
        entity_id:   Optional single entity to scope the update.

    Returns:
        Number of rows marked fresh.
    """
    if entity_id:
        entity_clause = " AND es.entity_id = $2::uuid"
        args: tuple[str, ...] = (campaign_id, entity_id)
    else:
        entity_clause = ""
        args = (campaign_id,)

    sql = f"""
        UPDATE playbook.entity_scores es
        SET score_stale = FALSE
        WHERE es.campaign_id = $1::uuid
          {entity_clause}
          AND (
            EXISTS (
                SELECT 1 FROM playbook.validation_results r
                JOIN playbook.validation_jobs j ON r.job_id = j.id
                WHERE j.campaign_id = es.campaign_id
                  AND r.entity_id = es.entity_id
                  AND j.status = 'done'
            )
            OR EXISTS (
                SELECT 1 FROM playbook.entity_attribute_assignments eaa
                WHERE eaa.campaign_id = es.campaign_id
                  AND eaa.entity_id = es.entity_id
            )
          )
    """

    async with _acquire() as conn:
        result = await conn.execute(sql, *args)
    return int(result.split()[-1])


# ---------------------------------------------------------------------------
# Recalculation (transactional with stale marking)
# ---------------------------------------------------------------------------

async def db_recalculate_scores(
    campaign_id: str,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    """Recalculate scores for a campaign in a single atomic transaction.

    All steps execute on one connection within one transaction:

    1. Mark affected rows as stale.
    2. Recompute scores from the **latest** validation result per
       (entity, attribute) pair across all completed jobs.
       The INSERT … ON CONFLICT sets ``score_stale = FALSE`` for every
       entity that has results.

    On failure the entire transaction rolls back — scores remain unchanged.
    Entities without results are unaffected.

    Args:
        campaign_id: Campaign UUID to recalculate.
        entity_id:   Optional entity UUID to limit recalculation scope.

    Returns:
        List of updated score dicts.
    """
    entity_filter = ""
    args: list[str] = [campaign_id]
    if entity_id:
        entity_filter = " AND r.entity_id = $2::uuid"
        args.append(entity_id)

    # Build WHERE for stale marking (same entity scope as recalculation)
    stale_where = "WHERE campaign_id = $1::uuid"
    if entity_id:
        stale_where += " AND entity_id = $2::uuid"

    try:
        async with _acquire() as conn:
            async with conn.transaction():
                # Step 1: mark stale (inside the transaction — rolls back on failure)
                await conn.execute(
                    f"UPDATE playbook.entity_scores "
                    f"SET score_stale = TRUE {stale_where}",
                    *args,
                )
                logger.info(
                    "Scores marked stale for campaign=%s entity=%s",
                    campaign_id, entity_id or "ALL",
                )

                # Step 2: recompute — INSERT sets score_stale = FALSE
                rows = await conn.fetch(
                    f"""
                    WITH latest AS (
                        SELECT DISTINCT ON (r.entity_id, r.attribute_id)
                               r.entity_id,
                               r.attribute_id,
                               r.present,
                               a.weight
                        FROM playbook.validation_results r
                        JOIN playbook.validation_jobs j ON r.job_id = j.id
                        JOIN playbook.attributes a ON r.attribute_id = a.id
                        WHERE j.campaign_id = $1::uuid
                          AND j.status = 'done'
                          {entity_filter}
                        ORDER BY r.entity_id, r.attribute_id, r.created_at DESC
                    )
                    INSERT INTO playbook.entity_scores
                        (entity_id, campaign_id, total_score,
                         attributes_present, attributes_checked,
                         last_updated, score_stale)
                    SELECT
                        l.entity_id,
                        $1::uuid,
                        SUM(CASE WHEN l.present THEN l.weight ELSE 0 END),
                        COUNT(CASE WHEN l.present THEN 1 END)::int,
                        COUNT(*)::int,
                        NOW(),
                        FALSE
                    FROM latest l
                    GROUP BY l.entity_id
                    ON CONFLICT (entity_id, campaign_id) DO UPDATE SET
                        total_score        = EXCLUDED.total_score,
                        attributes_present = EXCLUDED.attributes_present,
                        attributes_checked = EXCLUDED.attributes_checked,
                        last_updated       = NOW(),
                        score_stale        = FALSE
                    RETURNING *
                    """,
                    *args,
                )

        logger.info(
            "Scores recalculated for campaign=%s entity=%s (%d rows)",
            campaign_id, entity_id or "ALL", len(rows),
        )
        return [_score_row_to_dict(r) for r in rows]

    except Exception:
        logger.exception(
            "Score recalculation failed for campaign=%s entity=%s — transaction rolled back",
            campaign_id, entity_id or "ALL",
        )
        raise


# ---------------------------------------------------------------------------
# Matrix-based recalculation (entity_attribute_assignments)
# ---------------------------------------------------------------------------

async def db_recalculate_scores_from_matrix(
    campaign_id: str,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    """Recalculate scores from matrix cell values in a single atomic transaction.

    Uses the weighted-sum formula:
      score = sum(normalized_value_i * effective_weight_i) / sum(effective_weight_i)

    Normalization:
      - boolean: true=1.0, false=0.0
      - numeric (bounded): clamp((value - min) / (max - min), 0, 1)
      - numeric (unbounded): value / max(all_values) per attribute
      - select: ordinal_position / (total_options - 1) from the options array
      - text: excluded from scoring

    All steps execute on one connection within one transaction.
    On failure the entire transaction rolls back — scores remain unchanged.
    """
    entity_filter = ""
    args: list[str] = [campaign_id]
    if entity_id:
        entity_filter = " AND eaa.entity_id = $2::uuid"
        args.append(entity_id)

    stale_where = "WHERE campaign_id = $1::uuid"
    if entity_id:
        stale_where += " AND entity_id = $2::uuid"

    try:
        async with _acquire() as conn:
            async with conn.transaction():
                # Step 1: mark stale (inside the transaction)
                await conn.execute(
                    f"UPDATE playbook.entity_scores "
                    f"SET score_stale = TRUE {stale_where}",
                    *args,
                )
                logger.info(
                    "Matrix scores marked stale for campaign=%s entity=%s",
                    campaign_id, entity_id or "ALL",
                )

                # Step 2: recompute — INSERT sets score_stale = FALSE
                rows = await conn.fetch(
                    f"""
                    WITH raw_cells AS (
                        SELECT
                            eaa.entity_id,
                            eaa.attribute_id,
                            COALESCE(ca.weight_override, a.weight, 1.0) AS eff_weight,
                            a.attribute_type,
                            eaa.value_boolean,
                            eaa.value_numeric,
                            eaa.value_select,
                            a.numeric_min,
                            a.numeric_max,
                            a.options
                        FROM playbook.entity_attribute_assignments eaa
                        JOIN playbook.attributes a ON a.id = eaa.attribute_id
                        LEFT JOIN playbook.campaign_attributes ca
                            ON ca.campaign_id = eaa.campaign_id
                            AND ca.attribute_id = eaa.attribute_id
                        WHERE eaa.campaign_id = $1::uuid
                          AND a.attribute_type IN ('boolean', 'numeric', 'select')
                          AND (eaa.value_boolean IS NOT NULL
                               OR eaa.value_numeric IS NOT NULL
                               OR eaa.value_select IS NOT NULL)
                          {entity_filter}
                    ),
                    numeric_maxes AS (
                        SELECT attribute_id,
                               MAX(ABS(value_numeric)) AS max_val
                        FROM raw_cells
                        WHERE attribute_type = 'numeric'
                          AND value_numeric IS NOT NULL
                          AND (numeric_min IS NULL OR numeric_max IS NULL
                               OR numeric_max <= numeric_min)
                        GROUP BY attribute_id
                    ),
                    cell_scores AS (
                        SELECT
                            rc.entity_id,
                            rc.eff_weight,
                            CASE rc.attribute_type
                                WHEN 'boolean' THEN
                                    CASE WHEN rc.value_boolean THEN 1.0 ELSE 0.0 END
                                WHEN 'numeric' THEN
                                    CASE
                                        WHEN rc.numeric_min IS NOT NULL
                                             AND rc.numeric_max IS NOT NULL
                                             AND rc.numeric_max > rc.numeric_min
                                        THEN LEAST(1.0, GREATEST(0.0,
                                            (rc.value_numeric - rc.numeric_min)
                                            / (rc.numeric_max - rc.numeric_min)))
                                        WHEN nm.max_val IS NOT NULL AND nm.max_val > 0
                                        THEN LEAST(1.0, GREATEST(0.0,
                                            rc.value_numeric / nm.max_val))
                                        ELSE NULL
                                    END
                                WHEN 'select' THEN
                                    CASE
                                        WHEN rc.options IS NOT NULL
                                             AND rc.value_select IS NOT NULL
                                             AND jsonb_array_length(rc.options) > 1
                                        THEN (
                                            SELECT idx::float
                                                / (jsonb_array_length(rc.options) - 1)
                                            FROM generate_series(
                                                0, jsonb_array_length(rc.options) - 1
                                            ) AS idx
                                            WHERE rc.options ->> idx = rc.value_select
                                            LIMIT 1
                                        )
                                        WHEN rc.options IS NOT NULL
                                             AND rc.value_select IS NOT NULL
                                             AND jsonb_array_length(rc.options) = 1
                                        THEN 1.0
                                        ELSE NULL
                                    END
                                ELSE NULL
                            END AS normalized_value
                        FROM raw_cells rc
                        LEFT JOIN numeric_maxes nm
                            ON rc.attribute_id = nm.attribute_id
                    ),
                    scored AS (
                        SELECT
                            entity_id,
                            SUM(normalized_value * eff_weight)
                                / NULLIF(SUM(eff_weight), 0) * 100 AS total_score,
                            COUNT(CASE WHEN normalized_value > 0 THEN 1 END)::int
                                AS attributes_present,
                            COUNT(*)::int AS attributes_checked
                        FROM cell_scores
                        WHERE normalized_value IS NOT NULL
                        GROUP BY entity_id
                    )
                    INSERT INTO playbook.entity_scores
                        (entity_id, campaign_id, total_score,
                         attributes_present, attributes_checked,
                         last_updated, score_stale)
                    SELECT
                        s.entity_id, $1::uuid, ROUND(s.total_score::numeric, 2),
                        s.attributes_present, s.attributes_checked,
                        NOW(), FALSE
                    FROM scored s
                    ON CONFLICT (entity_id, campaign_id) DO UPDATE SET
                        total_score        = EXCLUDED.total_score,
                        attributes_present = EXCLUDED.attributes_present,
                        attributes_checked = EXCLUDED.attributes_checked,
                        last_updated       = NOW(),
                        score_stale        = FALSE
                    RETURNING *
                    """,
                    *args,
                )

        logger.info(
            "Matrix scores recalculated for campaign=%s entity=%s (%d rows)",
            campaign_id, entity_id or "ALL", len(rows),
        )
        return [_score_row_to_dict(r) for r in rows]

    except Exception:
        logger.exception(
            "Matrix score recalculation failed for campaign=%s entity=%s — transaction rolled back",
            campaign_id, entity_id or "ALL",
        )
        raise


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def db_get_score(
    campaign_id: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return the current score for a single entity in a campaign.

    Returns:
        Score dict or ``None`` if no score row exists yet.
    """
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT es.*, e.label AS entity_label, e.gwm_id
            FROM playbook.entity_scores es
            JOIN playbook.entities e ON es.entity_id = e.id
            WHERE es.campaign_id = $1::uuid
              AND es.entity_id = $2::uuid
            """,
            campaign_id, entity_id,
        )
    return _score_row_to_dict(row) if row else None


async def db_list_campaign_scores(
    campaign_id: str,
    sort_by: str = "score",
    order: str = "desc",
) -> list[dict[str, Any]]:
    """Return ranked scores for all entities in a campaign.

    Args:
        campaign_id: Campaign UUID.
        sort_by:     Column to sort by -- ``"score"`` (default) or ``"label"``.
        order:       ``"asc"`` or ``"desc"`` (default).

    Returns:
        List of score dicts ordered as requested.
    """
    # Whitelist sort columns to prevent SQL injection
    sort_column = {
        "score": "es.total_score",
        "label": "e.label",
        "attributes_present": "es.attributes_present",
        "last_updated": "es.last_updated",
    }.get(sort_by, "es.total_score")

    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT es.*, e.label AS entity_label, e.gwm_id
            FROM playbook.entity_scores es
            JOIN playbook.entities e ON es.entity_id = e.id
            WHERE es.campaign_id = $1::uuid
            ORDER BY {sort_column} {order_dir}
            """,
            campaign_id,
        )
    return [_score_row_to_dict(r) for r in rows]

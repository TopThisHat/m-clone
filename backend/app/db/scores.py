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
    """Set ``score_stale = FALSE`` after a successful recalculation.

    Args:
        campaign_id: Target campaign UUID.
        entity_id:   Optional single entity to scope the update.

    Returns:
        Number of rows marked fresh.
    """
    if entity_id:
        sql = (
            "UPDATE playbook.entity_scores "
            "SET score_stale = FALSE "
            "WHERE campaign_id = $1::uuid AND entity_id = $2::uuid"
        )
        args: tuple[str, ...] = (campaign_id, entity_id)
    else:
        sql = (
            "UPDATE playbook.entity_scores "
            "SET score_stale = FALSE "
            "WHERE campaign_id = $1::uuid"
        )
        args = (campaign_id,)

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
    """Recalculate scores for a campaign, wrapped in a transaction.

    1. Mark affected rows as stale.
    2. Recompute scores from the **latest** validation result per
       (entity, attribute) pair across all completed jobs for the campaign.
    3. Mark rows as fresh.

    If step 2 raises, the transaction rolls back but the stale marks from
    step 1 persist (they were committed in a separate statement before the
    transaction), signalling to the UI that a recalculation was attempted
    but failed.

    Args:
        campaign_id: Campaign UUID to recalculate.
        entity_id:   Optional entity UUID to limit recalculation scope.

    Returns:
        List of updated score dicts.
    """
    # Step 1: mark stale *outside* the recalc transaction so that if
    # recalculation fails the stale flag remains visible.
    await db_mark_scores_stale(campaign_id, entity_id)
    logger.info(
        "Scores marked stale for campaign=%s entity=%s",
        campaign_id, entity_id or "ALL",
    )

    entity_filter = ""
    args: list[str] = [campaign_id]
    if entity_id:
        entity_filter = " AND r.entity_id = $2::uuid"
        args.append(entity_id)

    try:
        async with _acquire() as conn:
            async with conn.transaction():
                # Step 2: recompute from latest result per (entity, attribute)
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

        # Step 3: mark fresh (handles any rows that already existed but were
        # not touched by the INSERT ... ON CONFLICT, e.g. entities with no
        # results in completed jobs).
        await db_mark_scores_fresh(campaign_id, entity_id)

        logger.info(
            "Scores recalculated for campaign=%s entity=%s (%d rows)",
            campaign_id, entity_id or "ALL", len(rows),
        )
        return [_score_row_to_dict(r) for r in rows]

    except Exception:
        logger.exception(
            "Score recalculation failed for campaign=%s entity=%s — scores remain stale",
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

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ._pool import _acquire

logger = logging.getLogger(__name__)

# Staleness tiers that count as cache hits
_CACHE_HIT_TIERS = frozenset({"fresh", "warm"})


def _knowledge_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("source_job_id", "source_campaign_id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
    return d


async def db_lookup_knowledge(
    gwm_id: str,
    attribute_label: str,
    *,
    team_id: str | None = None,
    max_age_hours: int = 168,
) -> dict[str, Any] | None:
    """Return cached research result for a gwm_id x attribute_label pair, or None.

    When *team_id* is provided the lookup is staleness-aware:
      - Check team-scoped rows first, then master (team_id IS NULL).
      - 'fresh' / 'warm' tiers are cache hits; 'stale' / 'expired' are misses.
      - The returned dict includes a ``staleness_tier`` key.

    When *team_id* is ``None`` (default) the legacy behaviour is preserved:
      rows older than *max_age_hours* are ignored (backward compat).
    """
    if not gwm_id or not gwm_id.strip():
        logger.warning("db_lookup_knowledge: called with NULL/empty gwm_id, returning None")
        return None
    async with _acquire() as conn:
        if team_id is not None:
            # ── staleness-aware, team-scoped lookup ──────────────────────
            row = await conn.fetchrow(
                """
                SELECT k.*,
                       playbook.compute_staleness_tier(k.last_updated) AS staleness_tier
                FROM playbook.entity_attribute_knowledge k
                WHERE k.gwm_id = $1 AND k.attribute_label = $2
                  AND (k.team_id = $3::uuid OR k.team_id IS NULL)
                ORDER BY
                    CASE WHEN k.team_id = $3::uuid THEN 0 ELSE 1 END,
                    k.last_updated DESC NULLS LAST
                LIMIT 1
                """,
                gwm_id, attribute_label, team_id,
            )
            if row is None:
                return None
            d = _knowledge_row_to_dict(row)
            tier = d.pop("staleness_tier", None)
            d["staleness_tier"] = tier
            if tier not in _CACHE_HIT_TIERS:
                return None  # stale / expired → cache miss
            return d
        else:
            # ── legacy behaviour (backward compat) ───────────────────────
            row = await conn.fetchrow(
                """
                SELECT * FROM playbook.entity_attribute_knowledge
                WHERE gwm_id = $1 AND attribute_label = $2
                  AND last_updated > NOW() - make_interval(hours => $3::float)
                """,
                gwm_id, attribute_label, float(max_age_hours),
            )
            return _knowledge_row_to_dict(row) if row else None


async def db_get_knowledge_for_campaign(campaign_id: str) -> list[dict[str, Any]]:
    """Return all knowledge rows for gwm_id entities in the given campaign.

    Includes ``team_id`` and ``staleness_tier`` in each result dict.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT k.*,
                   playbook.compute_staleness_tier(k.last_updated) AS staleness_tier
            FROM playbook.entity_attribute_knowledge k
            WHERE k.gwm_id IN (
                SELECT gwm_id FROM playbook.entities
                WHERE campaign_id = $1::uuid AND gwm_id IS NOT NULL
            )
            ORDER BY k.last_updated DESC
            """,
            campaign_id,
        )
    results: list[dict[str, Any]] = []
    for r in rows:
        d = _knowledge_row_to_dict(r)
        tier = d.pop("staleness_tier", None)
        d["staleness_tier"] = tier
        results.append(d)
    return results


async def db_lookup_knowledge_batch(
    pairs: list[tuple[str, str]],
    *,
    team_id: str | None = None,
    max_age_hours: int = 168,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return {(gwm_id, attribute_label): knowledge_row} for cache hits.

    When *team_id* is provided the lookup is staleness-aware:
      - Prefers team-scoped rows over master (team_id IS NULL).
      - 'fresh' / 'warm' tiers are cache hits; 'stale' / 'expired' are misses.
      - Each returned dict includes a ``staleness_tier`` key.

    When *team_id* is ``None`` the legacy max_age_hours filter applies.
    """
    if not pairs:
        return {}
    # Filter out pairs with NULL/empty gwm_id
    valid_pairs = [(g, a) for g, a in pairs if g and g.strip()]
    if not valid_pairs:
        return {}
    if len(valid_pairs) < len(pairs):
        logger.warning(
            "db_lookup_knowledge_batch: filtered %d pairs with NULL/empty gwm_id",
            len(pairs) - len(valid_pairs),
        )
    gwm_ids = [g for g, _ in valid_pairs]
    attr_labels = [a for _, a in valid_pairs]
    if len(gwm_ids) != len(attr_labels):
        logger.error(
            "db_lookup_knowledge_batch: mismatched arrays (%d gwm_ids vs %d labels) — skipping",
            len(gwm_ids), len(attr_labels),
        )
        return {}

    async with _acquire() as conn:
        if team_id is not None:
            # ── staleness-aware, team-scoped batch lookup ────────────────
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (inp.gwm_id, inp.attr)
                    k.*,
                    inp.gwm_id  AS _inp_gwm_id,
                    inp.attr    AS _inp_attr,
                    playbook.compute_staleness_tier(k.last_updated) AS staleness_tier
                FROM unnest($1::text[], $2::text[]) AS inp(gwm_id, attr)
                JOIN playbook.entity_attribute_knowledge k
                    ON k.gwm_id = inp.gwm_id AND k.attribute_label = inp.attr
                    AND (k.team_id = $3::uuid OR k.team_id IS NULL)
                ORDER BY inp.gwm_id, inp.attr,
                    CASE WHEN k.team_id = $3::uuid THEN 0 ELSE 1 END,
                    k.last_updated DESC NULLS LAST
                """,
                gwm_ids, attr_labels, team_id,
            )
            result: dict[tuple[str, str], dict[str, Any]] = {}
            for r in rows:
                d = _knowledge_row_to_dict(r)
                # Remove helper columns used only for DISTINCT ON ordering
                d.pop("_inp_gwm_id", None)
                d.pop("_inp_attr", None)
                tier = d.pop("staleness_tier", None)
                d["staleness_tier"] = tier
                if tier in _CACHE_HIT_TIERS:
                    result[(r["_inp_gwm_id"], r["_inp_attr"])] = d
            return result
        else:
            # ── legacy behaviour (backward compat) ───────────────────────
            rows = await conn.fetch(
                """
                SELECT k.*
                FROM playbook.entity_attribute_knowledge k
                JOIN unnest($1::text[], $2::text[]) AS inp(gwm_id, attr)
                  ON k.gwm_id = inp.gwm_id AND k.attribute_label = inp.attr
                WHERE k.last_updated > NOW() - make_interval(hours => $3::float)
                """,
                gwm_ids, attr_labels, float(max_age_hours),
            )
            return {(r["gwm_id"], r["attribute_label"]): _knowledge_row_to_dict(r) for r in rows}


async def db_check_staleness_batch(
    pairs: list[tuple[str, str]],  # [(gwm_id, attribute_label), ...]
    team_id: str | None = None,
) -> dict[tuple[str, str], dict]:
    """Batch staleness check across team + master scope.

    Returns ``{(gwm_id, attr_label): {"tier": str, "cached_result": dict|None}}``.

    Uses a single query with ``unnest`` (not N+1) per SQL expert recommendation.
    Prefers team-scoped results over master.  Fresh/warm return cached results;
    stale/expired return ``cached_result=None``.
    """
    if not pairs:
        return {}

    # Filter out pairs with NULL/empty gwm_id
    valid_pairs = [(g, a) for g, a in pairs if g and g.strip()]
    if not valid_pairs:
        return {}

    gwm_ids = [g for g, _ in valid_pairs]
    attr_labels = [a for _, a in valid_pairs]

    async with _acquire() as conn:
        if team_id is not None:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (inp.gwm_id, inp.attr)
                    inp.gwm_id, inp.attr AS attribute_label,
                    k.*,
                    playbook.compute_staleness_tier(k.last_updated) AS tier
                FROM unnest($1::text[], $2::text[]) AS inp(gwm_id, attr)
                LEFT JOIN playbook.entity_attribute_knowledge k
                    ON k.gwm_id = inp.gwm_id AND k.attribute_label = inp.attr
                    AND (k.team_id = $3::uuid OR k.team_id IS NULL)
                ORDER BY inp.gwm_id, inp.attr,
                    CASE WHEN k.team_id = $3::uuid THEN 0 ELSE 1 END,
                    k.last_updated DESC NULLS LAST
                """,
                gwm_ids, attr_labels, team_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (inp.gwm_id, inp.attr)
                    inp.gwm_id, inp.attr AS attribute_label,
                    k.*,
                    playbook.compute_staleness_tier(k.last_updated) AS tier
                FROM unnest($1::text[], $2::text[]) AS inp(gwm_id, attr)
                LEFT JOIN playbook.entity_attribute_knowledge k
                    ON k.gwm_id = inp.gwm_id AND k.attribute_label = inp.attr
                    AND k.team_id IS NULL
                ORDER BY inp.gwm_id, inp.attr,
                    k.last_updated DESC NULLS LAST
                """,
                gwm_ids, attr_labels,
            )

    result: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["gwm_id"], r["attribute_label"])
        tier = r["tier"]  # may be None when LEFT JOIN found no match

        if tier is None:
            # No knowledge row exists at all
            result[key] = {"tier": "expired", "cached_result": None}
        elif tier in _CACHE_HIT_TIERS:
            d = _knowledge_row_to_dict(r)
            # Remove synthetic columns that aren't part of the knowledge row
            d.pop("tier", None)
            result[key] = {"tier": tier, "cached_result": d}
        else:
            result[key] = {"tier": tier, "cached_result": None}

    return result

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ._pool import _acquire

logger = logging.getLogger(__name__)


def _knowledge_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("source_job_id", "source_campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
    return d


async def db_lookup_knowledge(gwm_id: str, attribute_label: str, max_age_hours: int = 168) -> dict[str, Any] | None:
    """Return cached research result for a gwm_id x attribute_label pair, or None.

    max_age_hours: ignore cache entries older than this many hours (default 168 = 7 days).
    """
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM playbook.entity_attribute_knowledge
            WHERE gwm_id = $1 AND attribute_label = $2
              AND last_updated > NOW() - ($3 || ' hours')::interval
            """,
            gwm_id, attribute_label, str(max_age_hours),
        )
    return _knowledge_row_to_dict(row) if row else None


async def db_get_knowledge_for_campaign(campaign_id: str) -> list[dict[str, Any]]:
    """Return all knowledge rows for gwm_id entities in the given campaign."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT k.*
            FROM playbook.entity_attribute_knowledge k
            WHERE k.gwm_id IN (
                SELECT gwm_id FROM playbook.entities
                WHERE campaign_id = $1::uuid AND gwm_id IS NOT NULL
            )
            ORDER BY k.last_updated DESC
            """,
            campaign_id,
        )
    return [_knowledge_row_to_dict(r) for r in rows]


async def db_lookup_knowledge_batch(
    pairs: list[tuple[str, str]], max_age_hours: int = 168
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return {(gwm_id, attribute_label): knowledge_row} for cache hits."""
    if not pairs:
        return {}
    gwm_ids = [g for g, _ in pairs]
    attr_labels = [a for _, a in pairs]
    if len(gwm_ids) != len(attr_labels):
        logger.error(
            "db_lookup_knowledge_batch: mismatched arrays (%d gwm_ids vs %d labels) — skipping",
            len(gwm_ids), len(attr_labels),
        )
        return {}
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT k.*
            FROM playbook.entity_attribute_knowledge k
            JOIN unnest($1::text[], $2::text[]) AS inp(gwm_id, attr)
              ON k.gwm_id = inp.gwm_id AND k.attribute_label = inp.attr
            WHERE k.last_updated > NOW() - ($3 || ' hours')::interval
            """,
            gwm_ids, attr_labels, str(max_age_hours),
        )
    return {(r["gwm_id"], r["attribute_label"]): _knowledge_row_to_dict(r) for r in rows}

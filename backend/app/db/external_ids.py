"""External identifier management — find entities by external system IDs.

Extends the entity_external_ids table with lookup and batch operations.
Basic CRUD (set/get/delete) lives in entities.py for backwards compatibility.
"""
from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _ext_id_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("entity_id",):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    return d


async def db_find_entity_by_external_id(
    system: str,
    external_id: str,
    campaign_id: str | None = None,
) -> dict[str, Any] | None:
    """Find an entity by its external identifier.

    Args:
        system: External system name (e.g. "gwm", "bloomberg", "crm").
        external_id: The ID in the external system.
        campaign_id: Optional campaign scope to narrow the search.

    Returns:
        Entity dict with external_id info, or None if not found.
    """
    if campaign_id:
        sql = """
            SELECT e.id, e.label, e.description, e.campaign_id, e.gwm_id,
                   ei.system, ei.external_id
            FROM playbook.entity_external_ids ei
            JOIN playbook.entities e ON e.id = ei.entity_id
            WHERE ei.system = $1 AND ei.external_id = $2
              AND e.campaign_id = $3::uuid
            LIMIT 1
        """
        args: tuple[str, ...] = (system, external_id, campaign_id)
    else:
        sql = """
            SELECT e.id, e.label, e.description, e.campaign_id, e.gwm_id,
                   ei.system, ei.external_id
            FROM playbook.entity_external_ids ei
            JOIN playbook.entities e ON e.id = ei.entity_id
            WHERE ei.system = $1 AND ei.external_id = $2
            LIMIT 1
        """
        args = (system, external_id)

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *args)
    if not row:
        return None
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    return d


async def db_find_entities_by_external_ids(
    system: str,
    external_ids: list[str],
    campaign_id: str | None = None,
) -> list[dict[str, Any]]:
    """Batch lookup: find entities by multiple external identifiers.

    Args:
        system: External system name.
        external_ids: List of external IDs to look up.
        campaign_id: Optional campaign scope.

    Returns:
        List of entity dicts with external_id info.
    """
    if not external_ids:
        return []

    if campaign_id:
        sql = """
            SELECT e.id, e.label, e.description, e.campaign_id, e.gwm_id,
                   ei.system, ei.external_id
            FROM playbook.entity_external_ids ei
            JOIN playbook.entities e ON e.id = ei.entity_id
            WHERE ei.system = $1 AND ei.external_id = ANY($2::text[])
              AND e.campaign_id = $3::uuid
            ORDER BY e.label
        """
        args: tuple[Any, ...] = (system, external_ids, campaign_id)
    else:
        sql = """
            SELECT e.id, e.label, e.description, e.campaign_id, e.gwm_id,
                   ei.system, ei.external_id
            FROM playbook.entity_external_ids ei
            JOIN playbook.entities e ON e.id = ei.entity_id
            WHERE ei.system = $1 AND ei.external_id = ANY($2::text[])
            ORDER BY e.label
        """
        args = (system, external_ids)

    async with _acquire() as conn:
        rows = await conn.fetch(sql, *args)

    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        for field in ("id", "campaign_id"):
            if field in d and d[field] is not None:
                d[field] = str(d[field])
        results.append(d)
    return results


async def db_find_entity_by_gwm_id(
    gwm_id: str,
    campaign_id: str | None = None,
) -> dict[str, Any] | None:
    """Find an entity by its GWM ID (stored directly on the entity row).

    Args:
        gwm_id: The GWM identifier.
        campaign_id: Optional campaign scope.

    Returns:
        Entity dict or None.
    """
    if campaign_id:
        sql = """
            SELECT id, label, description, campaign_id, gwm_id, metadata
            FROM playbook.entities
            WHERE gwm_id = $1 AND campaign_id = $2::uuid
            LIMIT 1
        """
        args: tuple[str, ...] = (gwm_id, campaign_id)
    else:
        sql = """
            SELECT id, label, description, campaign_id, gwm_id, metadata
            FROM playbook.entities
            WHERE gwm_id = $1
            LIMIT 1
        """
        args = (gwm_id,)

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *args)
    if not row:
        return None
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if d.get("metadata") and isinstance(d["metadata"], str):
        import json
        d["metadata"] = json.loads(d["metadata"])
    return d

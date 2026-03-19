from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _entity_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_create_entity(campaign_id: str, label: str, description: str | None = None,
                           gwm_id: str | None = None, metadata: dict | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
            RETURNING *
            """,
            campaign_id, label, description, gwm_id, json.dumps(metadata or {}),
        )
    return _entity_row_to_dict(row)


async def db_bulk_create_entities(campaign_id: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Insert entities, skipping duplicates. Returns {inserted: list, skipped: int}."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $1::uuid,
                   e->>'label',
                   NULLIF(e->>'description', ''),
                   NULLIF(e->>'gwm_id', ''),
                   COALESCE((e->'metadata')::jsonb, '{}'::jsonb)
            FROM jsonb_array_elements($2::jsonb) AS e
            WHERE (e->>'label') IS NOT NULL AND (e->>'label') != ''
            ON CONFLICT (campaign_id, label) DO NOTHING
            RETURNING *
            """,
            campaign_id, json.dumps(entities),
        )
    inserted = [_entity_row_to_dict(r) for r in rows]
    skipped = len([e for e in entities if e.get("label")]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_list_entities(
    campaign_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        if limit == 0:
            rows = await conn.fetch(
                """SELECT *, COUNT(*) OVER() AS _total FROM playbook.entities
                   WHERE campaign_id = $1::uuid
                     AND ($2::text IS NULL OR label ILIKE '%' || $2 || '%')
                   ORDER BY created_at ASC""",
                campaign_id, search,
            )
        else:
            rows = await conn.fetch(
                """SELECT *, COUNT(*) OVER() AS _total FROM playbook.entities
                   WHERE campaign_id = $1::uuid
                     AND ($2::text IS NULL OR label ILIKE '%' || $2 || '%')
                   ORDER BY created_at ASC
                   LIMIT $3 OFFSET $4""",
                campaign_id, search, limit, offset,
            )
    total = int(rows[0]["_total"]) if rows else 0
    items = [_entity_row_to_dict(r) for r in rows]
    for item in items:
        item.pop("_total", None)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def db_get_entity(entity_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.entities WHERE id = $1::uuid", entity_id)
    return _entity_row_to_dict(row) if row else None


async def db_delete_entity(entity_id: str, campaign_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.entities WHERE id = $1::uuid AND campaign_id = $2::uuid",
            entity_id, campaign_id,
        )
    return result.endswith("1")


async def db_update_entity(entity_id: str, campaign_id: str, **kwargs: Any) -> dict[str, Any] | None:
    allowed = {"label", "description", "gwm_id", "metadata"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return await db_get_entity(entity_id)
    set_parts = []
    values = []
    for i, (k, v) in enumerate(fields.items(), start=1):
        if k == "metadata":
            set_parts.append(f"{k} = ${i}::jsonb")
            values.append(json.dumps(v))
        else:
            set_parts.append(f"{k} = ${i}")
            values.append(v)
    values += [entity_id, campaign_id]
    sql = (
        f"UPDATE playbook.entities SET {', '.join(set_parts)} "
        f"WHERE id = ${len(values)-1}::uuid AND campaign_id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _entity_row_to_dict(row) if row else None

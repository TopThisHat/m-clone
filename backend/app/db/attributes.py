from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _attribute_row_to_dict(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    # Deserialise JSONB options column into a Python list
    if "options" in d and isinstance(d["options"], str):
        d["options"] = json.loads(d["options"])
    return d


async def db_create_attribute(
    campaign_id: str,
    label: str,
    description: str | None = None,
    weight: float = 1.0,
    *,
    attribute_type: str = "text",
    category: str | None = None,
    numeric_min: float | None = None,
    numeric_max: float | None = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.attributes
                (campaign_id, label, description, weight,
                 attribute_type, category, numeric_min, numeric_max, options)
            VALUES ($1::uuid, TRIM($2), $3, $4, $5, $6, $7, $8, $9::jsonb)
            RETURNING *
            """,
            campaign_id,
            label,
            description,
            weight,
            attribute_type,
            category,
            numeric_min,
            numeric_max,
            json.dumps(options) if options is not None else None,
        )
    return _attribute_row_to_dict(row)


async def db_bulk_create_attributes(campaign_id: str, attributes: list[dict[str, Any]]) -> dict[str, Any]:
    """Insert attributes, skipping duplicates. Returns {inserted: list, skipped: int}."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.attributes
                (campaign_id, label, description, weight,
                 attribute_type, category, numeric_min, numeric_max, options)
            SELECT $1::uuid,
                   TRIM(a->>'label'),
                   NULLIF(TRIM(a->>'description'), ''),
                   COALESCE((a->>'weight')::float, 1.0),
                   COALESCE(NULLIF(TRIM(a->>'attribute_type'), ''), 'text'),
                   NULLIF(TRIM(a->>'category'), ''),
                   (a->>'numeric_min')::float,
                   (a->>'numeric_max')::float,
                   CASE WHEN a->'options' IS NOT NULL AND a->>'options' != 'null'
                        THEN a->'options' ELSE NULL END
            FROM jsonb_array_elements($2::jsonb) AS a
            WHERE TRIM(COALESCE(a->>'label', '')) != ''
            ON CONFLICT (campaign_id, (LOWER(TRIM(label)))) DO NOTHING
            RETURNING *
            """,
            campaign_id, json.dumps(attributes),
        )
    inserted = [_attribute_row_to_dict(r) for r in rows]
    skipped = len([a for a in attributes if (a.get("label") or "").strip()]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_list_attributes(
    campaign_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    _where = """WHERE campaign_id = $1::uuid
                  AND ($2::text IS NULL OR label ILIKE '%' || $2 || '%')
                  AND ($3::text IS NULL OR category = $3)"""
    async with _acquire() as conn:
        if limit == 0:
            rows = await conn.fetch(
                f"SELECT * FROM playbook.attributes {_where} ORDER BY created_at ASC",
                campaign_id, search, category,
            )
            total = len(rows)
        else:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM playbook.attributes {_where}",
                campaign_id, search, category,
            )
            rows = await conn.fetch(
                f"SELECT * FROM playbook.attributes {_where} ORDER BY created_at ASC LIMIT $4 OFFSET $5",
                campaign_id, search, category, limit, offset,
            )
    items = [_attribute_row_to_dict(r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def db_get_attribute(attribute_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.attributes WHERE id = $1::uuid", attribute_id)
    return _attribute_row_to_dict(row) if row else None


async def db_update_attribute(attribute_id: str, campaign_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"label", "description", "weight", "attribute_type", "category", "numeric_min", "numeric_max", "options"}
    fields: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in allowed:
            continue
        # Serialise options list to JSON string for the JSONB column
        if k == "options":
            fields[k] = json.dumps(v) if v is not None else None
        else:
            fields[k] = v
    if not fields:
        return await db_get_attribute(attribute_id)

    set_parts: list[str] = []
    values: list[Any] = []
    for i, (k, v) in enumerate(fields.items()):
        if k == "options":
            set_parts.append(f"{k} = ${i + 1}::jsonb")
        else:
            set_parts.append(f"{k} = ${i + 1}")
        values.append(v)
    values += [attribute_id, campaign_id]
    sql = (
        f"UPDATE playbook.attributes SET {', '.join(set_parts)} "
        f"WHERE id = ${len(values) - 1}::uuid AND campaign_id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _attribute_row_to_dict(row) if row else None


async def db_delete_attribute(attribute_id: str, campaign_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.attributes WHERE id = $1::uuid AND campaign_id = $2::uuid",
            attribute_id, campaign_id,
        )
    return result.endswith("1")

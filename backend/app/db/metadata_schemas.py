from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _schema_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a metadata_schemas row to a plain dict with serialised UUID/timestamps."""
    d = dict(row)
    for field in ("id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    if "options" in d and isinstance(d["options"], str):
        d["options"] = json.loads(d["options"])
    return d


async def db_create_metadata_schema(
    team_id: str,
    field_name: str,
    field_type: str,
    label: str,
    *,
    description: str | None = None,
    required: bool = False,
    options: list[str] | None = None,
    display_order: int = 0,
) -> dict[str, Any]:
    """Create a metadata field definition for a team."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.metadata_schemas
                (team_id, field_name, field_type, label, description,
                 required, options, display_order)
            VALUES ($1::uuid, LOWER(TRIM($2)), $3, TRIM($4), $5,
                    $6, $7::jsonb, $8)
            RETURNING *
            """,
            team_id,
            field_name,
            field_type,
            label,
            description,
            required,
            json.dumps(options) if options is not None else None,
            display_order,
        )
    return _schema_row_to_dict(row)


async def db_list_metadata_schemas(team_id: str) -> list[dict[str, Any]]:
    """List all metadata field definitions for a team, ordered by display_order."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.metadata_schemas
            WHERE team_id = $1::uuid
            ORDER BY display_order ASC, created_at ASC
            """,
            team_id,
        )
    return [_schema_row_to_dict(r) for r in rows]


async def db_get_metadata_schema(schema_id: str) -> dict[str, Any] | None:
    """Get a single metadata field definition by ID."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM playbook.metadata_schemas WHERE id = $1::uuid",
            schema_id,
        )
    return _schema_row_to_dict(row) if row else None


async def db_update_metadata_schema(
    schema_id: str,
    team_id: str,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a metadata field definition. Returns None if not found."""
    allowed = {"field_name", "field_type", "label", "description", "required", "options", "display_order"}
    fields: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in allowed:
            continue
        if k == "options":
            fields[k] = json.dumps(v) if v is not None else None
        elif k == "field_name":
            fields[k] = v.strip().lower() if isinstance(v, str) else v
        else:
            fields[k] = v
    if not fields:
        return await db_get_metadata_schema(schema_id)

    set_parts: list[str] = []
    values: list[Any] = []
    for i, (k, v) in enumerate(fields.items()):
        if k == "options":
            set_parts.append(f"{k} = ${i + 1}::jsonb")
        else:
            set_parts.append(f"{k} = ${i + 1}")
        values.append(v)
    values += [schema_id, team_id]
    sql = (
        f"UPDATE playbook.metadata_schemas SET {', '.join(set_parts)}, updated_at = NOW() "
        f"WHERE id = ${len(values) - 1}::uuid AND team_id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _schema_row_to_dict(row) if row else None


async def db_delete_metadata_schema(schema_id: str, team_id: str) -> bool:
    """Delete a metadata field definition. Returns True if deleted."""
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.metadata_schemas WHERE id = $1::uuid AND team_id = $2::uuid",
            schema_id, team_id,
        )
    return result.endswith("1")


async def db_bulk_create_metadata_schemas(
    team_id: str,
    schemas: list[dict[str, Any]],
) -> dict[str, Any]:
    """Insert metadata field definitions in bulk, skipping duplicates on field_name.

    Returns {inserted: list, skipped: int}.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.metadata_schemas
                (team_id, field_name, field_type, label, description,
                 required, options, display_order)
            SELECT $1::uuid,
                   LOWER(TRIM(s->>'field_name')),
                   COALESCE(NULLIF(TRIM(s->>'field_type'), ''), 'text'),
                   TRIM(s->>'label'),
                   NULLIF(TRIM(s->>'description'), ''),
                   COALESCE((s->>'required')::boolean, false),
                   CASE WHEN s->'options' IS NOT NULL AND s->>'options' != 'null'
                        THEN s->'options' ELSE NULL END,
                   COALESCE((s->>'display_order')::int, 0)
            FROM jsonb_array_elements($2::jsonb) AS s
            WHERE TRIM(COALESCE(s->>'field_name', '')) != ''
            ON CONFLICT (team_id, (LOWER(TRIM(field_name)))) DO NOTHING
            RETURNING *
            """,
            team_id, json.dumps(schemas),
        )
    inserted = [_schema_row_to_dict(r) for r in rows]
    skipped = len([s for s in schemas if (s.get("field_name") or "").strip()]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_reorder_metadata_schemas(
    team_id: str,
    ordering: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update display_order for multiple schema fields at once.

    Args:
        team_id: The team these schemas belong to.
        ordering: List of {id: str, display_order: int} dicts.

    Returns:
        Updated list of all schemas for the team.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            for item in ordering:
                await conn.execute(
                    """
                    UPDATE playbook.metadata_schemas
                    SET display_order = $1, updated_at = NOW()
                    WHERE id = $2::uuid AND team_id = $3::uuid
                    """,
                    item["display_order"], item["id"], team_id,
                )
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.metadata_schemas
            WHERE team_id = $1::uuid
            ORDER BY display_order ASC, created_at ASC
            """,
            team_id,
        )
    return [_schema_row_to_dict(r) for r in rows]

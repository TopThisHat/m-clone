from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _lib_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


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


def _attribute_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_list_entity_library(
    owner_sid: str,
    team_id: str | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "asc",
) -> dict[str, Any]:
    # Whitelist sort columns
    allowed_sort = {"label", "gwm_id", "created_at"}
    sort_col = sort_by if sort_by in allowed_sort else "created_at"
    sort_direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"

    # Search now covers label, gwm_id, and description
    if team_id:
        _where = """WHERE team_id=$1::uuid AND (
            $2::text IS NULL OR
            label ILIKE '%' || $2 || '%' OR
            COALESCE(gwm_id, '') ILIKE '%' || $2 || '%' OR
            COALESCE(description, '') ILIKE '%' || $2 || '%'
        )"""
        args: list[Any] = [team_id, search]
    else:
        _where = """WHERE owner_sid=$1 AND team_id IS NULL AND (
            $2::text IS NULL OR
            label ILIKE '%' || $2 || '%' OR
            COALESCE(gwm_id, '') ILIKE '%' || $2 || '%' OR
            COALESCE(description, '') ILIKE '%' || $2 || '%'
        )"""
        args = [owner_sid, search]

    async with _acquire() as conn:
        if limit == 0:
            rows = await conn.fetch(
                f"SELECT * FROM playbook.entity_library {_where} ORDER BY {sort_col} {sort_direction}",
                *args,
            )
            total = len(rows)
        else:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM playbook.entity_library {_where}",
                *args,
            )
            rows = await conn.fetch(
                f"SELECT * FROM playbook.entity_library {_where} ORDER BY {sort_col} {sort_direction} LIMIT $3 OFFSET $4",
                *args, limit, offset,
            )
    items = [_lib_row_to_dict(r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def db_create_entity_library(owner_sid: str, team_id: str | None, label: str,
                                   description: str | None, gwm_id: str | None,
                                   metadata: dict | None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.entity_library (owner_sid, team_id, label, description, gwm_id, metadata)
            VALUES ($1, $2::uuid, TRIM($3), $4, NULLIF(TRIM($5), ''), $6::jsonb)
            RETURNING *
            """,
            owner_sid, team_id, label, description, gwm_id, json.dumps(metadata or {}),
        )
    return _lib_row_to_dict(row)


async def db_bulk_create_entity_library(owner_sid: str, team_id: str | None,
                                        items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"inserted": [], "skipped": 0}
    # Choose ON CONFLICT target based on whether this is a team or personal library
    if team_id:
        conflict = "ON CONFLICT (team_id, (LOWER(TRIM(label)))) WHERE team_id IS NOT NULL DO NOTHING"
    else:
        conflict = "ON CONFLICT (owner_sid, (LOWER(TRIM(label)))) WHERE team_id IS NULL DO NOTHING"
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            INSERT INTO playbook.entity_library (owner_sid, team_id, label, description, gwm_id, metadata)
            SELECT $1,
                   $2::uuid,
                   TRIM(e->>'label'),
                   NULLIF(TRIM(e->>'description'), ''),
                   NULLIF(TRIM(e->>'gwm_id'), ''),
                   COALESCE((e->'metadata')::jsonb, '{{}}'::jsonb)
            FROM jsonb_array_elements($3::jsonb) AS e
            WHERE TRIM(COALESCE(e->>'label', '')) != ''
            {conflict}
            RETURNING *
            """,
            owner_sid, team_id, json.dumps(items),
        )
    inserted = [_lib_row_to_dict(r) for r in rows]
    skipped = len([i for i in items if (i.get("label") or "").strip()]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_update_entity_library(item_id: str, owner_sid: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"label", "description", "gwm_id", "metadata"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        # Return current state on no-op instead of None
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM playbook.entity_library WHERE id=$1::uuid AND owner_sid=$2",
                item_id, owner_sid,
            )
        return _lib_row_to_dict(row) if row else None
    set_clauses = []
    values: list[Any] = []
    for i, (k, v) in enumerate(updates.items(), start=3):
        if k == "metadata":
            set_clauses.append(f"{k} = ${i}::jsonb")
            values.append(json.dumps(v))
        elif k == "gwm_id":
            set_clauses.append(f"{k} = NULLIF(TRIM(${i}), '')")
            values.append(v)
        elif k == "label":
            set_clauses.append(f"{k} = TRIM(${i})")
            values.append(v)
        else:
            set_clauses.append(f"{k} = ${i}")
            values.append(v)
    sql = f"UPDATE playbook.entity_library SET {', '.join(set_clauses)} WHERE id=$1::uuid AND owner_sid=$2 RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, item_id, owner_sid, *values)
    return _lib_row_to_dict(row) if row else None


async def db_delete_entity_library(item_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.entity_library WHERE id=$1::uuid AND owner_sid=$2",
            item_id, owner_sid,
        )
    return result.endswith("1")


async def db_list_attribute_library(
    owner_sid: str,
    team_id: str | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "asc",
) -> dict[str, Any]:
    # Whitelist sort columns
    allowed_sort = {"label", "weight", "created_at"}
    sort_col = sort_by if sort_by in allowed_sort else "created_at"
    sort_direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"

    # Search covers label and description
    if team_id:
        _where = """WHERE team_id=$1::uuid AND (
            $2::text IS NULL OR
            label ILIKE '%' || $2 || '%' OR
            COALESCE(description, '') ILIKE '%' || $2 || '%'
        )"""
        args: list[Any] = [team_id, search]
    else:
        _where = """WHERE owner_sid=$1 AND team_id IS NULL AND (
            $2::text IS NULL OR
            label ILIKE '%' || $2 || '%' OR
            COALESCE(description, '') ILIKE '%' || $2 || '%'
        )"""
        args = [owner_sid, search]

    async with _acquire() as conn:
        if limit == 0:
            rows = await conn.fetch(
                f"SELECT * FROM playbook.attribute_library {_where} ORDER BY {sort_col} {sort_direction}",
                *args,
            )
            total = len(rows)
        else:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM playbook.attribute_library {_where}",
                *args,
            )
            rows = await conn.fetch(
                f"SELECT * FROM playbook.attribute_library {_where} ORDER BY {sort_col} {sort_direction} LIMIT $3 OFFSET $4",
                *args, limit, offset,
            )
    items = [_lib_row_to_dict(r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def db_create_attribute_library(owner_sid: str, team_id: str | None, label: str,
                                      description: str | None, weight: float) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.attribute_library (owner_sid, team_id, label, description, weight)
            VALUES ($1, $2::uuid, TRIM($3), $4, $5)
            RETURNING *
            """,
            owner_sid, team_id, label, description, weight,
        )
    return _lib_row_to_dict(row)


async def db_bulk_create_attribute_library(owner_sid: str, team_id: str | None,
                                           items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"inserted": [], "skipped": 0}
    if team_id:
        conflict = "ON CONFLICT (team_id, (LOWER(TRIM(label)))) WHERE team_id IS NOT NULL DO NOTHING"
    else:
        conflict = "ON CONFLICT (owner_sid, (LOWER(TRIM(label)))) WHERE team_id IS NULL DO NOTHING"
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            INSERT INTO playbook.attribute_library (owner_sid, team_id, label, description, weight)
            SELECT $1,
                   $2::uuid,
                   TRIM(e->>'label'),
                   NULLIF(TRIM(e->>'description'), ''),
                   COALESCE((e->>'weight')::float, 1.0)
            FROM jsonb_array_elements($3::jsonb) AS e
            WHERE TRIM(COALESCE(e->>'label', '')) != ''
            {conflict}
            RETURNING *
            """,
            owner_sid, team_id, json.dumps(items),
        )
    inserted = [_lib_row_to_dict(r) for r in rows]
    skipped = len([i for i in items if (i.get("label") or "").strip()]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_update_attribute_library(item_id: str, owner_sid: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"label", "description", "weight"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        # Return current state on no-op instead of None
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM playbook.attribute_library WHERE id=$1::uuid AND owner_sid=$2",
                item_id, owner_sid,
            )
        return _lib_row_to_dict(row) if row else None
    set_clauses = []
    values: list[Any] = []
    for i, (k, v) in enumerate(updates.items(), start=3):
        if k == "label":
            set_clauses.append(f"{k} = TRIM(${i})")
        else:
            set_clauses.append(f"{k} = ${i}")
        values.append(v)
    sql = f"UPDATE playbook.attribute_library SET {', '.join(set_clauses)} WHERE id=$1::uuid AND owner_sid=$2 RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, item_id, owner_sid, *values)
    return _lib_row_to_dict(row) if row else None


async def db_delete_attribute_library(item_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.attribute_library WHERE id=$1::uuid AND owner_sid=$2",
            item_id, owner_sid,
        )
    return result.endswith("1")


async def db_import_entities_from_library(
    campaign_id: str,
    lib_ids: list[str],
    *,
    owner_sid: str | None = None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Copy entity_library rows into campaign entities, skip duplicates.

    Returns a structured result: ``{"inserted": [...], "skipped": int, "total_requested": int}``.

    Handles all unique-constraint edge cases:
      1. CTE deduplicates the batch on label (DISTINCT ON) so within-batch
         label collisions never reach INSERT.
      2. ON CONFLICT DO NOTHING catches gwm_id and label collisions with
         rows already in the target campaign.

    When *owner_sid* or *team_id* is provided, an ownership filter is applied
    so users can only import from their own or their team's library.
    """
    total_requested = len(lib_ids)
    if not lib_ids:
        return {"inserted": [], "skipped": 0, "total_requested": 0}

    # Build optional ownership filter
    ownership_filter = ""
    args: list[Any] = [campaign_id, lib_ids]
    if team_id:
        ownership_filter = " AND team_id = $3::uuid"
        args.append(team_id)
    elif owner_sid:
        ownership_filter = " AND owner_sid = $3"
        args.append(owner_sid)

    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            WITH source AS (
                SELECT DISTINCT ON (LOWER(TRIM(label)))
                    TRIM(label) AS label,
                    description,
                    NULLIF(TRIM(gwm_id), '') AS gwm_id,
                    metadata
                FROM playbook.entity_library
                WHERE id = ANY($2::uuid[])
                  AND TRIM(COALESCE(label, '')) != ''
                  {ownership_filter}
                ORDER BY LOWER(TRIM(label)), created_at
            )
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $1::uuid, s.label, s.description, s.gwm_id, s.metadata
            FROM source s
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            *args,
        )
    inserted = [_entity_row_to_dict(r) for r in rows]
    return {
        "inserted": inserted,
        "skipped": total_requested - len(inserted),
        "total_requested": total_requested,
    }


async def db_import_attributes_from_library(
    campaign_id: str,
    lib_ids: list[str],
    *,
    owner_sid: str | None = None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Copy attribute_library rows into campaign attributes, skip duplicates.

    Returns structured result: ``{"inserted": [...], "skipped": int, "total_requested": int}``.

    When *owner_sid* or *team_id* is provided, an ownership filter is applied
    so users can only import from their own or their team's library.
    """
    total_requested = len(lib_ids)
    if not lib_ids:
        return {"inserted": [], "skipped": 0, "total_requested": 0}

    # Build optional ownership filter
    ownership_filter = ""
    args: list[Any] = [campaign_id, lib_ids]
    if team_id:
        ownership_filter = " AND team_id = $3::uuid"
        args.append(team_id)
    elif owner_sid:
        ownership_filter = " AND owner_sid = $3"
        args.append(owner_sid)

    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            WITH source AS (
                SELECT DISTINCT ON (LOWER(TRIM(label)))
                    TRIM(label) AS label,
                    description,
                    weight
                FROM playbook.attribute_library
                WHERE id = ANY($2::uuid[])
                  AND TRIM(COALESCE(label, '')) != ''
                  {ownership_filter}
                ORDER BY LOWER(TRIM(label)), created_at
            )
            INSERT INTO playbook.attributes (campaign_id, label, description, weight)
            SELECT $1::uuid, s.label, s.description, s.weight
            FROM source s
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            *args,
        )
    inserted = [_attribute_row_to_dict(r) for r in rows]
    return {
        "inserted": inserted,
        "skipped": total_requested - len(inserted),
        "total_requested": total_requested,
    }

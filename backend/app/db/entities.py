from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


# ── Allowed sort columns (whitelist to prevent SQL injection) ────────────────
_SORT_COLUMNS = {
    "name": "e.label",
    "label": "e.label",
    "created_at": "e.created_at",
    "score": "COALESCE(s.total_score, 0)",
}


class DuplicateLabelError(Exception):
    """Raised when an entity label already exists within the campaign."""

    def __init__(self, label: str, campaign_id: str) -> None:
        self.label = label
        self.campaign_id = campaign_id
        super().__init__(f"Entity with label '{label}' already exists in campaign {campaign_id}")


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


# ── Label uniqueness check ───────────────────────────────────────────────────

async def _check_label_unique(
    conn: asyncpg.Connection,
    campaign_id: str,
    label: str,
    exclude_entity_id: str | None = None,
) -> None:
    """Raise DuplicateLabelError if label already exists in the campaign.

    The check is case-insensitive and ignores leading/trailing whitespace,
    matching the unique index ``entities_campaign_label_unique``.
    """
    if exclude_entity_id:
        existing = await conn.fetchval(
            """
            SELECT id FROM playbook.entities
            WHERE campaign_id = $1::uuid
              AND LOWER(TRIM(label)) = LOWER(TRIM($2))
              AND id != $3::uuid
            """,
            campaign_id, label, exclude_entity_id,
        )
    else:
        existing = await conn.fetchval(
            """
            SELECT id FROM playbook.entities
            WHERE campaign_id = $1::uuid
              AND LOWER(TRIM(label)) = LOWER(TRIM($2))
            """,
            campaign_id, label,
        )
    if existing is not None:
        raise DuplicateLabelError(label.strip(), campaign_id)


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def db_create_entity(
    campaign_id: str,
    label: str,
    description: str | None = None,
    gwm_id: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        await _check_label_unique(conn, campaign_id, label)
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
                VALUES ($1::uuid, TRIM($2), $3, NULLIF(TRIM($4), ''), $5::jsonb)
                RETURNING *
                """,
                campaign_id, label, description, gwm_id, json.dumps(metadata or {}),
            )
        except asyncpg.UniqueViolationError:
            raise DuplicateLabelError(label.strip(), campaign_id)
    return _entity_row_to_dict(row)


async def db_bulk_create_entities(campaign_id: str, entities: list[dict[str, Any]]) -> dict[str, Any]:
    """Insert entities, skipping duplicates on both label and gwm_id.

    ON CONFLICT DO NOTHING catches both the label unique index and the
    gwm_id unique index, correctly handling NULL gwm_id values (which are
    always distinct in PostgreSQL partial unique indexes).
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            WITH incoming AS (
                SELECT TRIM(e->>'label') AS label,
                       NULLIF(TRIM(e->>'description'), '') AS description,
                       NULLIF(TRIM(e->>'gwm_id'), '') AS gwm_id,
                       COALESCE((e->'metadata')::jsonb, '{}'::jsonb) AS metadata
                FROM jsonb_array_elements($2::jsonb) AS e
                WHERE TRIM(COALESCE(e->>'label', '')) != ''
            )
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $1::uuid, i.label, i.description, i.gwm_id, i.metadata
            FROM incoming i
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            campaign_id, json.dumps(entities),
        )
    inserted = [_entity_row_to_dict(r) for r in rows]
    skipped = len([e for e in entities if (e.get("label") or "").strip()]) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_list_entities(
    campaign_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    sort_by: str = "created_at",
    order: str = "asc",
) -> dict[str, Any]:
    """List entities for a campaign with optional search, sorting, and pagination.

    Args:
        campaign_id: UUID of the campaign.
        limit: Max rows to return (0 = unlimited).
        offset: Pagination offset.
        search: Case-insensitive substring match on label.
        sort_by: Column to sort by (name/label, created_at, score).
        order: Sort direction (asc or desc).
    """
    sort_col = _SORT_COLUMNS.get(sort_by, "e.created_at")
    direction = "DESC" if order.lower() == "desc" else "ASC"

    # When sorting by score we LEFT JOIN entity_scores
    needs_score_join = sort_by == "score"

    _from = "FROM playbook.entities e"
    if needs_score_join:
        _from += """
            LEFT JOIN playbook.entity_scores s
                ON s.entity_id = e.id AND s.campaign_id = e.campaign_id"""

    _where = """WHERE e.campaign_id = $1::uuid
                  AND ($2::text IS NULL OR e.label ILIKE '%' || $2 || '%')"""

    _order = f"ORDER BY {sort_col} {direction}"

    async with _acquire() as conn:
        if limit == 0:
            rows = await conn.fetch(
                f"SELECT e.* {_from} {_where} {_order}",
                campaign_id, search,
            )
            total = len(rows)
        else:
            total = await conn.fetchval(
                f"SELECT COUNT(*) {_from} {_where}",
                campaign_id, search,
            )
            rows = await conn.fetch(
                f"SELECT e.* {_from} {_where} {_order} LIMIT $3 OFFSET $4",
                campaign_id, search, limit, offset,
            )
    items = [_entity_row_to_dict(r) for r in rows]
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

    async with _acquire() as conn:
        # Enforce label uniqueness on update
        if "label" in fields:
            await _check_label_unique(conn, campaign_id, fields["label"], exclude_entity_id=entity_id)

        set_parts: list[str] = []
        values: list[Any] = []
        for i, (k, v) in enumerate(fields.items(), start=1):
            if k == "metadata":
                set_parts.append(f"{k} = ${i}::jsonb")
                values.append(json.dumps(v))
            elif k == "gwm_id":
                set_parts.append(f"{k} = NULLIF(TRIM(${i}), '')")
                values.append(v)
            elif k == "label":
                set_parts.append(f"{k} = TRIM(${i})")
                values.append(v)
            else:
                set_parts.append(f"{k} = ${i}")
                values.append(v)
        values += [entity_id, campaign_id]
        sql = (
            f"UPDATE playbook.entities SET {', '.join(set_parts)} "
            f"WHERE id = ${len(values) - 1}::uuid AND campaign_id = ${len(values)}::uuid RETURNING *"
        )
        try:
            row = await conn.fetchrow(sql, *values)
        except asyncpg.UniqueViolationError:
            raise DuplicateLabelError(fields.get("label", "").strip(), campaign_id)
    return _entity_row_to_dict(row) if row else None


# ── Metadata CRUD ────────────────────────────────────────────────────────────

async def db_get_entity_metadata(entity_id: str) -> dict[str, Any]:
    """Return the metadata JSONB column for an entity, or empty dict if not found."""
    async with _acquire() as conn:
        val = await conn.fetchval(
            "SELECT metadata FROM playbook.entities WHERE id = $1::uuid",
            entity_id,
        )
    if val is None:
        return {}
    if isinstance(val, str):
        return json.loads(val)
    return dict(val) if not isinstance(val, dict) else val


async def db_set_entity_metadata(entity_id: str, key: str, value: Any) -> dict[str, Any]:
    """Set a single key in the metadata JSONB column. Returns the full updated metadata."""
    async with _acquire() as conn:
        row = await conn.fetchval(
            """
            UPDATE playbook.entities
            SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), ARRAY[$2], $3::jsonb)
            WHERE id = $1::uuid
            RETURNING metadata
            """,
            entity_id, key, json.dumps(value),
        )
    if row is None:
        return {}
    return json.loads(row) if isinstance(row, str) else dict(row)


async def db_set_entity_metadata_batch(entity_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Atomically set multiple keys in the metadata JSONB column. Returns the full updated metadata."""
    if not updates:
        return {}
    async with _acquire() as conn:
        async with conn.transaction():
            row: Any = None
            for key, value in updates.items():
                row = await conn.fetchval(
                    """
                    UPDATE playbook.entities
                    SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), ARRAY[$2], $3::jsonb)
                    WHERE id = $1::uuid
                    RETURNING metadata
                    """,
                    entity_id, key, json.dumps(value),
                )
    if row is None:
        return {}
    return json.loads(row) if isinstance(row, str) else dict(row)


async def db_delete_entity_metadata(entity_id: str, key: str) -> dict[str, Any]:
    """Remove a key from the metadata JSONB column. Returns the remaining metadata."""
    async with _acquire() as conn:
        row = await conn.fetchval(
            """
            UPDATE playbook.entities
            SET metadata = COALESCE(metadata, '{}'::jsonb) - $2
            WHERE id = $1::uuid
            RETURNING metadata
            """,
            entity_id, key,
        )
    if row is None:
        return {}
    return json.loads(row) if isinstance(row, str) else dict(row)


# ── External IDs (GWM_ID via junction table) ─────────────────────────────────

async def db_set_external_id(entity_id: str, system: str, external_id: str) -> dict[str, Any]:
    """Upsert an external ID for a given system. Returns the row as dict."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.entity_external_ids (entity_id, system, external_id)
            VALUES ($1::uuid, $2, $3)
            ON CONFLICT (entity_id, system)
            DO UPDATE SET external_id = EXCLUDED.external_id
            RETURNING *
            """,
            entity_id, system.strip(), external_id.strip(),
        )
    if row is None:
        return {}
    d = dict(row)
    d["entity_id"] = str(d["entity_id"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_get_external_ids(entity_id: str) -> list[dict[str, Any]]:
    """Return all external IDs for an entity."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM playbook.entity_external_ids WHERE entity_id = $1::uuid ORDER BY system",
            entity_id,
        )
    result: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["entity_id"] = str(d["entity_id"])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result


async def db_delete_external_id(entity_id: str, system: str) -> bool:
    """Delete an external ID for a given system. Returns True if deleted."""
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.entity_external_ids WHERE entity_id = $1::uuid AND system = $2",
            entity_id, system,
        )
    return result.endswith("1")


# ── Entity-Campaign Assignment ────────────────────────────────────────────────

async def db_assign_entities_to_campaign(
    campaign_id: str,
    entity_ids: list[str],
) -> dict[str, Any]:
    """Assign entities from the entity library to a campaign by copying them.

    Skips duplicates (matching on label within the campaign).
    Returns {inserted: list, skipped: int}.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $1::uuid, el.label, el.description, el.gwm_id, el.metadata
            FROM playbook.entity_library el
            WHERE el.id = ANY($2::uuid[])
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            campaign_id, entity_ids,
        )
    inserted = [_entity_row_to_dict(r) for r in rows]
    skipped = len(entity_ids) - len(inserted)
    return {"inserted": inserted, "skipped": max(0, skipped)}


async def db_unassign_entities_from_campaign(
    campaign_id: str,
    entity_ids: list[str],
) -> int:
    """Remove entities from a campaign. Returns the number of entities removed."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.entities
            WHERE campaign_id = $1::uuid AND id = ANY($2::uuid[])
            """,
            campaign_id, entity_ids,
        )
    # result is like "DELETE 3"
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0

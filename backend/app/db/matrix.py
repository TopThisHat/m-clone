from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire, _acquire_team


def _assignment_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert an entity_attribute_assignments row to a plain dict."""
    d = dict(row)
    for field in ("campaign_id", "entity_id", "attribute_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "updated_at" in d and d["updated_at"] is not None:
        d["updated_at"] = d["updated_at"].isoformat()
    return d


async def db_get_matrix_data(campaign_id: str) -> dict[str, Any]:
    """Return the full entity x attribute matrix data for a campaign.

    Returns:
        {
            entities: [{id, label, gwm_id, metadata}],
            attributes: [{id, label, attribute_type, category, weight, ...}],
            cells: [{entity_id, attribute_id, value_boolean, value_numeric,
                      value_text, value_select, updated_at}],
        }
    """
    async with _acquire() as conn:
        entities = await conn.fetch(
            """
            SELECT id, label, description, gwm_id, metadata, created_at
            FROM playbook.entities
            WHERE campaign_id = $1::uuid
            ORDER BY created_at ASC
            """,
            campaign_id,
        )
        attributes = await conn.fetch(
            """
            SELECT a.id, a.label, a.description, a.attribute_type,
                   a.category, a.weight, a.numeric_min, a.numeric_max,
                   a.options, a.created_at,
                   ca.weight_override, ca.display_order,
                   COALESCE(ca.weight_override, a.weight, 1.0) AS effective_weight
            FROM playbook.attributes a
            LEFT JOIN playbook.campaign_attributes ca
                ON ca.attribute_id = a.id AND ca.campaign_id = a.campaign_id
            WHERE a.campaign_id = $1::uuid
            ORDER BY COALESCE(ca.display_order, 0) ASC, a.created_at ASC
            """,
            campaign_id,
        )
        cells = await conn.fetch(
            """
            SELECT entity_id, attribute_id,
                   value_boolean, value_numeric, value_text, value_select,
                   updated_at, updated_by
            FROM playbook.entity_attribute_assignments
            WHERE campaign_id = $1::uuid
            """,
            campaign_id,
        )

    import json

    entity_list: list[dict[str, Any]] = []
    for r in entities:
        d = dict(r)
        d["id"] = str(d["id"])
        if d.get("metadata") and isinstance(d["metadata"], str):
            d["metadata"] = json.loads(d["metadata"])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        entity_list.append(d)

    attr_list: list[dict[str, Any]] = []
    for r in attributes:
        d = dict(r)
        d["id"] = str(d["id"])
        if d.get("options") and isinstance(d["options"], str):
            d["options"] = json.loads(d["options"])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        attr_list.append(d)

    cell_list = [_assignment_row_to_dict(r) for r in cells]

    return {
        "entities": entity_list,
        "attributes": attr_list,
        "cells": cell_list,
    }


async def db_upsert_cell_value(
    campaign_id: str,
    entity_id: str,
    attribute_id: str,
    value: Any,
    *,
    attribute_type: str | None = None,
    updated_by: str | None = None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Upsert a single cell value in the matrix.

    If attribute_type is not provided, it will be looked up from the attribute.
    The value is stored in the appropriate typed column based on attribute_type.

    Args:
        team_id: When provided, ``SET LOCAL app.current_team_id`` is issued so
            that row-level security policies are enforced on the write.

    Returns the upserted row as a dict.
    """
    async with _acquire_team(team_id) as conn:
        # Look up attribute type if not provided
        if attribute_type is None:
            attribute_type = await conn.fetchval(
                "SELECT attribute_type FROM playbook.attributes WHERE id = $1::uuid",
                attribute_id,
            )
            if attribute_type is None:
                raise ValueError(f"Attribute {attribute_id} not found")

        # Determine which column to set, NULL out the others
        val_bool: bool | None = None
        val_num: float | None = None
        val_text: str | None = None
        val_select: str | None = None

        if value is not None:
            if attribute_type == "boolean":
                val_bool = bool(value)
            elif attribute_type == "numeric":
                val_num = float(value)
            elif attribute_type == "select":
                val_select = str(value)
            else:  # text
                val_text = str(value)

        row = await conn.fetchrow(
            """
            INSERT INTO playbook.entity_attribute_assignments
                (campaign_id, entity_id, attribute_id,
                 value_boolean, value_numeric, value_text, value_select,
                 updated_at, updated_by)
            VALUES ($1::uuid, $2::uuid, $3::uuid,
                    $4, $5, $6, $7,
                    NOW(), $8)
            ON CONFLICT (campaign_id, entity_id, attribute_id) DO UPDATE
                SET value_boolean = EXCLUDED.value_boolean,
                    value_numeric = EXCLUDED.value_numeric,
                    value_text = EXCLUDED.value_text,
                    value_select = EXCLUDED.value_select,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by
            RETURNING *
            """,
            campaign_id, entity_id, attribute_id,
            val_bool, val_num, val_text, val_select,
            updated_by,
        )
    return _assignment_row_to_dict(row)


async def db_delete_cell_value(
    campaign_id: str,
    entity_id: str,
    attribute_id: str,
    *,
    team_id: str | None = None,
) -> bool:
    """Delete a cell value (clear the cell). Returns True if deleted.

    Args:
        team_id: When provided, enforces RLS via ``SET LOCAL app.current_team_id``.
    """
    async with _acquire_team(team_id) as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.entity_attribute_assignments
            WHERE campaign_id = $1::uuid
              AND entity_id = $2::uuid
              AND attribute_id = $3::uuid
            """,
            campaign_id, entity_id, attribute_id,
        )
    return result.endswith("1")


async def db_get_cell_value(
    campaign_id: str,
    entity_id: str,
    attribute_id: str,
) -> dict[str, Any] | None:
    """Get a single cell value."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM playbook.entity_attribute_assignments
            WHERE campaign_id = $1::uuid
              AND entity_id = $2::uuid
              AND attribute_id = $3::uuid
            """,
            campaign_id, entity_id, attribute_id,
        )
    return _assignment_row_to_dict(row) if row else None


async def db_bulk_upsert_cells(
    campaign_id: str,
    cells: list[dict[str, Any]],
    *,
    updated_by: str | None = None,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    """Bulk upsert cell values within a single transaction.

    Each cell dict should have: entity_id, attribute_id, value, and optionally
    attribute_type (looked up if missing).

    Args:
        team_id: When provided, enforces RLS via ``SET LOCAL app.current_team_id``.
    """
    results: list[dict[str, Any]] = []
    async with _acquire_team(team_id) as conn:
        # Pre-fetch attribute types for all referenced attributes
        attr_ids = list({c["attribute_id"] for c in cells})
        type_rows = await conn.fetch(
            """
            SELECT id, attribute_type FROM playbook.attributes
            WHERE id = ANY($1::uuid[])
            """,
            attr_ids,
        )
        type_map = {str(r["id"]): r["attribute_type"] for r in type_rows}

        async with conn.transaction():
            for cell in cells:
                attr_type = cell.get("attribute_type") or type_map.get(cell["attribute_id"], "text")
                value = cell.get("value")

                val_bool: bool | None = None
                val_num: float | None = None
                val_text: str | None = None
                val_select: str | None = None

                if value is not None:
                    if attr_type == "boolean":
                        val_bool = bool(value)
                    elif attr_type == "numeric":
                        val_num = float(value)
                    elif attr_type == "select":
                        val_select = str(value)
                    else:
                        val_text = str(value)

                row = await conn.fetchrow(
                    """
                    INSERT INTO playbook.entity_attribute_assignments
                        (campaign_id, entity_id, attribute_id,
                         value_boolean, value_numeric, value_text, value_select,
                         updated_at, updated_by)
                    VALUES ($1::uuid, $2::uuid, $3::uuid,
                            $4, $5, $6, $7,
                            NOW(), $8)
                    ON CONFLICT (campaign_id, entity_id, attribute_id) DO UPDATE
                        SET value_boolean = EXCLUDED.value_boolean,
                            value_numeric = EXCLUDED.value_numeric,
                            value_text = EXCLUDED.value_text,
                            value_select = EXCLUDED.value_select,
                            updated_at = NOW(),
                            updated_by = EXCLUDED.updated_by
                    RETURNING *
                    """,
                    campaign_id, cell["entity_id"], cell["attribute_id"],
                    val_bool, val_num, val_text, val_select,
                    updated_by,
                )
                results.append(_assignment_row_to_dict(row))
    return results

from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _ca_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a campaign_attributes row to a plain dict with serialised UUIDs."""
    d = dict(row)
    for field in ("campaign_id", "attribute_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "assigned_at" in d and d["assigned_at"] is not None:
        d["assigned_at"] = d["assigned_at"].isoformat()
    return d


def _enriched_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a joined campaign_attributes + attributes row to dict."""
    d = dict(row)
    for field in ("campaign_id", "attribute_id", "id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("assigned_at", "created_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_assign_attribute_to_campaign(
    campaign_id: str,
    attribute_id: str,
    *,
    weight_override: float | None = None,
    display_order: int = 0,
) -> dict[str, Any]:
    """Assign an attribute to a campaign with optional weight override.

    Uses upsert to handle re-assignment gracefully.
    """
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.campaign_attributes
                (campaign_id, attribute_id, weight_override, display_order)
            VALUES ($1::uuid, $2::uuid, $3, $4)
            ON CONFLICT (campaign_id, attribute_id) DO UPDATE
                SET weight_override = EXCLUDED.weight_override,
                    display_order = EXCLUDED.display_order
            RETURNING *
            """,
            campaign_id, attribute_id, weight_override, display_order,
        )
    return _ca_row_to_dict(row)


async def db_update_campaign_attribute(
    campaign_id: str,
    attribute_id: str,
    *,
    weight_override: float | None = ...,  # type: ignore[assignment]
    display_order: int | None = None,
) -> dict[str, Any] | None:
    """Update weight_override and/or display_order for a campaign-attribute assignment.

    Returns None if the assignment doesn't exist.
    """
    set_parts: list[str] = []
    values: list[Any] = []
    idx = 1

    # Use sentinel to distinguish "not provided" from "set to None"
    if weight_override is not ...:
        set_parts.append(f"weight_override = ${idx}")
        values.append(weight_override)
        idx += 1
    if display_order is not None:
        set_parts.append(f"display_order = ${idx}")
        values.append(display_order)
        idx += 1

    if not set_parts:
        return await db_get_campaign_attribute(campaign_id, attribute_id)

    values += [campaign_id, attribute_id]
    sql = (
        f"UPDATE playbook.campaign_attributes SET {', '.join(set_parts)} "
        f"WHERE campaign_id = ${idx}::uuid AND attribute_id = ${idx + 1}::uuid "
        f"RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _ca_row_to_dict(row) if row else None


async def db_unassign_attribute_from_campaign(
    campaign_id: str,
    attribute_id: str,
) -> bool:
    """Remove an attribute assignment from a campaign. Returns True if removed."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.campaign_attributes
            WHERE campaign_id = $1::uuid AND attribute_id = $2::uuid
            """,
            campaign_id, attribute_id,
        )
    return result.endswith("1")


async def db_get_campaign_attribute(
    campaign_id: str,
    attribute_id: str,
) -> dict[str, Any] | None:
    """Get a single campaign-attribute assignment."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM playbook.campaign_attributes
            WHERE campaign_id = $1::uuid AND attribute_id = $2::uuid
            """,
            campaign_id, attribute_id,
        )
    return _ca_row_to_dict(row) if row else None


async def db_list_campaign_attributes(
    campaign_id: str,
) -> list[dict[str, Any]]:
    """List all attribute assignments for a campaign with attribute details.

    Returns attributes joined with their assignment data, ordered by display_order.
    The effective_weight is resolved as COALESCE(weight_override, weight, 1.0).
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.id AS attribute_id,
                a.label,
                a.description,
                a.weight AS default_weight,
                a.attribute_type,
                a.category,
                a.numeric_min,
                a.numeric_max,
                a.options,
                a.created_at,
                ca.campaign_id,
                ca.weight_override,
                ca.display_order,
                ca.assigned_at,
                COALESCE(ca.weight_override, a.weight, 1.0) AS effective_weight
            FROM playbook.campaign_attributes ca
            JOIN playbook.attributes a ON a.id = ca.attribute_id
            WHERE ca.campaign_id = $1::uuid
            ORDER BY ca.display_order ASC, a.created_at ASC
            """,
            campaign_id,
        )
    return [_enriched_row_to_dict(r) for r in rows]


async def db_reorder_campaign_attributes(
    campaign_id: str,
    ordering: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update display_order for multiple campaign-attribute assignments.

    Args:
        campaign_id: The campaign.
        ordering: List of {attribute_id: str, display_order: int} dicts.

    Returns:
        Updated list of all campaign attribute assignments.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            for item in ordering:
                await conn.execute(
                    """
                    UPDATE playbook.campaign_attributes
                    SET display_order = $1
                    WHERE campaign_id = $2::uuid AND attribute_id = $3::uuid
                    """,
                    item["display_order"], campaign_id, item["attribute_id"],
                )
    return await db_list_campaign_attributes(campaign_id)

from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _template_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for f in ("id", "team_id"):
        if f in d and d[f] is not None:
            d[f] = str(d[f])
    if "attributes" in d and isinstance(d["attributes"], str):
        d["attributes"] = json.loads(d["attributes"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_list_attribute_templates(owner_sid: str, team_id: str | None = None) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        if team_id:
            rows = await conn.fetch(
                "SELECT * FROM playbook.attribute_templates WHERE team_id = $1::uuid ORDER BY created_at DESC",
                team_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM playbook.attribute_templates WHERE owner_sid = $1 AND team_id IS NULL ORDER BY created_at DESC",
                owner_sid,
            )
    return [_template_row_to_dict(r) for r in rows]


async def db_create_attribute_template(
    owner_sid: str, name: str, attributes: list[dict], team_id: str | None = None
) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.attribute_templates (owner_sid, team_id, name, attributes)
            VALUES ($1, $2::uuid, $3, $4::jsonb)
            RETURNING *
            """,
            owner_sid, team_id, name, json.dumps(attributes),
        )
    return _template_row_to_dict(row)


async def db_get_attribute_template(template_id: str) -> dict[str, Any] | None:
    """Fetch a single template by ID."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM playbook.attribute_templates WHERE id = $1::uuid",
            template_id,
        )
    return _template_row_to_dict(row) if row else None


async def db_delete_attribute_template(template_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.attribute_templates WHERE id = $1::uuid AND owner_sid = $2",
            template_id, owner_sid,
        )
    return int(result.split()[-1]) > 0


async def db_save_template_from_campaign(
    campaign_id: str,
    name: str,
    owner_sid: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Snapshot a campaign's attributes into a reusable template.

    Captures label, description, weight, attribute_type, category,
    numeric_min, numeric_max, and options for each attribute.
    """
    async with _acquire() as conn:
        attr_rows = await conn.fetch(
            """
            SELECT label, description, weight, attribute_type,
                   category, numeric_min, numeric_max, options
            FROM playbook.attributes
            WHERE campaign_id = $1::uuid
            ORDER BY created_at ASC
            """,
            campaign_id,
        )
        attributes: list[dict[str, Any]] = []
        for r in attr_rows:
            d = dict(r)
            if d.get("options") and isinstance(d["options"], str):
                d["options"] = json.loads(d["options"])
            attributes.append(d)

        row = await conn.fetchrow(
            """
            INSERT INTO playbook.attribute_templates (owner_sid, team_id, name, attributes)
            VALUES ($1, $2::uuid, $3, $4::jsonb)
            RETURNING *
            """,
            owner_sid, team_id, name, json.dumps(attributes),
        )
    return _template_row_to_dict(row)


async def db_apply_template_to_campaign(
    template_id: str,
    campaign_id: str,
) -> dict[str, Any]:
    """Apply a template's attributes to a campaign.

    Creates attributes from the template, skipping any that conflict with
    existing attributes (ON CONFLICT DO NOTHING on the label unique index).

    Returns: {inserted: int, skipped: int}
    """
    async with _acquire() as conn:
        template_row = await conn.fetchrow(
            "SELECT attributes FROM playbook.attribute_templates WHERE id = $1::uuid",
            template_id,
        )
        if template_row is None:
            raise ValueError(f"Template {template_id} not found")

        raw_attrs = template_row["attributes"]
        if isinstance(raw_attrs, str):
            attrs = json.loads(raw_attrs)
        else:
            attrs = list(raw_attrs)

        if not attrs:
            return {"inserted": 0, "skipped": 0}

        rows = await conn.fetch(
            """
            WITH incoming AS (
                SELECT
                    TRIM(a->>'label') AS label,
                    NULLIF(TRIM(a->>'description'), '') AS description,
                    COALESCE((a->>'weight')::float, 1.0) AS weight,
                    COALESCE(a->>'attribute_type', 'text') AS attribute_type,
                    NULLIF(TRIM(a->>'category'), '') AS category,
                    (a->>'numeric_min')::float AS numeric_min,
                    (a->>'numeric_max')::float AS numeric_max,
                    CASE WHEN a->'options' IS NOT NULL
                         THEN (a->'options')::jsonb ELSE NULL END AS options
                FROM jsonb_array_elements($2::jsonb) AS a
                WHERE TRIM(COALESCE(a->>'label', '')) != ''
            )
            INSERT INTO playbook.attributes
                (campaign_id, label, description, weight, attribute_type,
                 category, numeric_min, numeric_max, options)
            SELECT $1::uuid, i.label, i.description, i.weight, i.attribute_type,
                   i.category, i.numeric_min, i.numeric_max, i.options::text
            FROM incoming i
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            campaign_id, json.dumps(attrs),
        )
    inserted = len(rows)
    total_valid = len([a for a in attrs if (a.get("label") or "").strip()])
    return {"inserted": inserted, "skipped": total_valid - inserted}

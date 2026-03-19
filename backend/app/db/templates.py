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


async def db_delete_attribute_template(template_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.attribute_templates WHERE id = $1::uuid AND owner_sid = $2",
            template_id, owner_sid,
        )
    return int(result.split()[-1]) > 0

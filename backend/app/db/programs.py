from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _program_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a programs row to a plain dict with serialised UUID/timestamps."""
    d = dict(row)
    for field in ("id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_create_program(
    name: str,
    description: str | None,
    owner_sid: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.programs (name, description, owner_sid, team_id)
            VALUES ($1, $2, $3, $4::uuid)
            RETURNING *
            """,
            name, description, owner_sid, team_id,
        )
    return _program_row_to_dict(row)


async def db_list_programs(
    owner_sid: str,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        if team_id:
            rows = await conn.fetch(
                """
                SELECT p.*
                FROM playbook.programs p
                JOIN playbook.team_members tm ON tm.team_id = p.team_id
                WHERE p.team_id = $1::uuid AND tm.sid = $2
                ORDER BY p.updated_at DESC
                """,
                team_id, owner_sid,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT p.*
                FROM playbook.programs p
                WHERE p.owner_sid = $1 AND p.team_id IS NULL
                ORDER BY p.updated_at DESC
                """,
                owner_sid,
            )
    return [_program_row_to_dict(r) for r in rows]


async def db_get_program(program_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*
            FROM playbook.programs p
            WHERE p.id = $1::uuid
            """,
            program_id,
        )
    return _program_row_to_dict(row) if row else None


async def db_update_program(
    program_id: str,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    allowed: dict[str, Any] = {}
    if name is not None:
        allowed["name"] = name
    if description is not None:
        allowed["description"] = description
    if not allowed:
        return await db_get_program(program_id)

    set_parts = [f"{k} = ${i + 1}" for i, k in enumerate(allowed)]
    values = list(allowed.values()) + [program_id]
    sql = (
        f"UPDATE playbook.programs SET {', '.join(set_parts)}, updated_at = NOW() "
        f"WHERE id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _program_row_to_dict(row) if row else None


async def db_delete_program(program_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.programs WHERE id = $1::uuid",
            program_id,
        )
    return result.endswith("1")

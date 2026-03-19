from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("message_history", "trace_steps", "mentions", "payload", "facts"):
        if field in d and isinstance(d[field], str):
            d[field] = json.loads(d[field])
    for field in ("id", "session_id", "team_id", "parent_id", "comment_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    if "updated_at" in d and d["updated_at"] is not None:
        d["updated_at"] = d["updated_at"].isoformat()
    if "joined_at" in d and d["joined_at"] is not None:
        d["joined_at"] = d["joined_at"].isoformat()
    if "shared_at" in d and d["shared_at"] is not None:
        d["shared_at"] = d["shared_at"].isoformat()
    if "pinned_at" in d and d["pinned_at"] is not None:
        d["pinned_at"] = d["pinned_at"].isoformat()
    if "last_login" in d and d["last_login"] is not None:
        d["last_login"] = d["last_login"].isoformat()
    return d


async def db_upsert_user(sid: str, display_name: str, email: str = "") -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.users (sid, display_name, email, last_login)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (sid) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                last_login = NOW()
            RETURNING *
            """,
            sid, display_name, email,
        )
    return _row_to_dict(row)


async def db_get_user(sid: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.users WHERE sid = $1", sid)
    return _row_to_dict(row) if row else None


async def db_update_user_theme(sid: str, theme: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE playbook.users SET theme = $1 WHERE sid = $2",
            theme, sid,
        )

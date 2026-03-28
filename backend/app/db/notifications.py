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


async def db_create_notification(recipient_sid: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.notifications (recipient_sid, type, payload)
            VALUES ($1, $2, $3::jsonb)
            RETURNING *
            """,
            recipient_sid, type_, json.dumps(payload),
        )
    return _row_to_dict(row)


async def db_list_notifications(recipient_sid: str, limit: int = 50) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.notifications
            WHERE recipient_sid = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            recipient_sid, limit,
        )
    result = []
    for r in rows:
        d = dict(r)
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


async def db_mark_notification_read(notification_id: str, recipient_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "UPDATE playbook.notifications SET read = TRUE WHERE id = $1::uuid AND recipient_sid = $2",
            notification_id, recipient_sid,
        )
    return result.endswith("1")


async def db_mark_all_notifications_read(recipient_sid: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE playbook.notifications SET read = TRUE WHERE recipient_sid = $1 AND read = FALSE",
            recipient_sid,
        )

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


async def db_create_comment(
    session_id: str,
    author_sid: str,
    body: str,
    mentions: list[str],
    parent_id: str | None = None,
    highlight_anchor: dict | None = None,
    comment_type: str = "comment",
    proposed_text: str | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.comments (session_id, author_sid, body, mentions, parent_id, highlight_anchor, comment_type, proposed_text)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5::uuid, $6::jsonb, $7, $8)
            RETURNING *
            """,
            session_id, author_sid, body, json.dumps(mentions),
            parent_id if parent_id else None,
            json.dumps(highlight_anchor) if highlight_anchor else None,
            comment_type,
            proposed_text,
        )
    return _row_to_dict(row)


async def db_list_comments(session_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*, u.display_name AS author_name, u.avatar_url AS author_avatar
            FROM playbook.comments c
            LEFT JOIN playbook.users u ON c.author_sid = u.sid
            WHERE c.session_id = $1::uuid
            ORDER BY c.created_at ASC
            """,
            session_id,
        )
    result = []
    comment_ids = []
    for r in rows:
        d = dict(r)
        for field in ("mentions", "highlight_anchor"):
            if field in d and isinstance(d[field], str):
                d[field] = json.loads(d[field])
        for field in ("id", "session_id", "parent_id"):
            if field in d and d[field] is not None:
                d[field] = str(d[field])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if "updated_at" in d and d["updated_at"] is not None:
            d["updated_at"] = d["updated_at"].isoformat()
        d.setdefault("reactions", {})
        result.append(d)
        comment_ids.append(d["id"])
    # Attach reactions in bulk
    if comment_ids:
        reactions_map = await db_get_reactions_bulk(comment_ids)
        for d in result:
            d["reactions"] = reactions_map.get(d["id"], {})
    return result


async def db_get_comment(comment_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.comments WHERE id = $1::uuid", comment_id)
    return _row_to_dict(row) if row else None


async def db_delete_comment(comment_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM playbook.comments WHERE id = $1::uuid", comment_id)
    return result.endswith("1")


async def db_update_comment(comment_id: str, body: str, mentions: list[str]) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE playbook.comments SET body=$2, updated_at=NOW(), mentions=$3::jsonb
            WHERE id=$1::uuid RETURNING *
            """,
            comment_id, body, json.dumps(mentions),
        )
    return _row_to_dict(row) if row else None


async def db_resolve_suggestion(comment_id: str, status: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE playbook.comments SET suggestion_status=$2, updated_at=NOW()
            WHERE id=$1::uuid AND comment_type='suggestion' RETURNING *
            """,
            comment_id, status,
        )
    return _row_to_dict(row) if row else None


async def db_toggle_reaction(comment_id: str, user_sid: str, emoji: str) -> dict[str, list[str]]:
    async with _acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT 1 FROM playbook.comment_reactions WHERE comment_id=$1::uuid AND user_sid=$2 AND emoji=$3",
                comment_id, user_sid, emoji,
            )
            if existing:
                await conn.execute(
                    "DELETE FROM playbook.comment_reactions WHERE comment_id=$1::uuid AND user_sid=$2 AND emoji=$3",
                    comment_id, user_sid, emoji,
                )
            else:
                await conn.execute(
                    "INSERT INTO playbook.comment_reactions (comment_id, user_sid, emoji) VALUES ($1::uuid, $2, $3) ON CONFLICT DO NOTHING",
                    comment_id, user_sid, emoji,
                )
            rows = await conn.fetch(
                "SELECT emoji, user_sid FROM playbook.comment_reactions WHERE comment_id=$1::uuid",
                comment_id,
            )
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["emoji"], []).append(r["user_sid"])
    return result


async def db_get_reactions_bulk(comment_ids: list[str]) -> dict[str, dict[str, list[str]]]:
    if not comment_ids:
        return {}
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT comment_id::text, emoji, user_sid FROM playbook.comment_reactions WHERE comment_id = ANY($1::uuid[])",
            comment_ids,
        )
    result: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        cid = r["comment_id"]
        result.setdefault(cid, {}).setdefault(r["emoji"], []).append(r["user_sid"])
    return result

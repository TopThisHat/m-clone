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


async def db_list_sessions(owner_sid: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        select = (
            "SELECT id, title, query, created_at, updated_at, "
            "COALESCE(is_public, FALSE) AS is_public, COALESCE(usage_tokens, 0) AS usage_tokens, "
            "owner_sid, COALESCE(visibility, 'private') AS visibility "
            "FROM playbook.sessions "
        )
        if owner_sid and search:
            rows = await conn.fetch(
                select + "WHERE (owner_sid = $1 OR visibility = 'public') "
                "AND search_vec @@ plainto_tsquery('english', $2) "
                "ORDER BY updated_at DESC",
                owner_sid, search,
            )
        elif owner_sid:
            rows = await conn.fetch(
                select + "WHERE owner_sid = $1 OR visibility = 'public' "
                "ORDER BY updated_at DESC",
                owner_sid,
            )
        elif search:
            rows = await conn.fetch(
                select + "WHERE search_vec @@ plainto_tsquery('english', $1) "
                "ORDER BY updated_at DESC",
                search,
            )
        else:
            rows = await conn.fetch(select + "ORDER BY updated_at DESC")
    return [_row_to_dict(r) for r in rows]


async def db_get_session(session_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT *, COALESCE(is_public, FALSE) AS is_public, "
            "COALESCE(usage_tokens, 0) AS usage_tokens, "
            "COALESCE(visibility, 'private') AS visibility "
            "FROM playbook.sessions WHERE id = $1",
            session_id,
        )
    return _row_to_dict(row) if row else None


async def db_get_public_session(session_id: str) -> dict[str, Any] | None:
    """Return session only if is_public=true."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT *, COALESCE(is_public, FALSE) AS is_public, "
            "COALESCE(usage_tokens, 0) AS usage_tokens, "
            "COALESCE(visibility, 'private') AS visibility "
            "FROM playbook.sessions WHERE id = $1 AND is_public = TRUE",
            session_id,
        )
    return _row_to_dict(row) if row else None


async def db_create_session(data: dict[str, Any]) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.sessions (title, query, report_markdown, message_history, trace_steps, owner_sid, visibility)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
            RETURNING *, COALESCE(is_public, FALSE) AS is_public,
                         COALESCE(usage_tokens, 0) AS usage_tokens,
                         COALESCE(visibility, 'private') AS visibility
            """,
            data["title"],
            data["query"],
            data.get("report_markdown", ""),
            json.dumps(data.get("message_history", [])),
            json.dumps(data.get("trace_steps", [])),
            data.get("owner_sid"),
            data.get("visibility", "private"),
        )
    return _row_to_dict(row)


async def db_update_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "report_markdown", "message_history", "trace_steps", "is_public", "usage_tokens", "visibility", "owner_sid", "parent_session_id"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_session(session_id)

    set_parts = []
    values: list[Any] = []
    idx = 1
    for key, val in fields.items():
        if key in ("message_history", "trace_steps"):
            set_parts.append(f"{key} = ${idx}::jsonb")
            values.append(json.dumps(val))
        else:
            set_parts.append(f"{key} = ${idx}")
            values.append(val)
        idx += 1

    set_parts.append("updated_at = NOW()")
    values.append(session_id)

    sql = (
        f"UPDATE playbook.sessions SET {', '.join(set_parts)} WHERE id = ${idx} "
        "RETURNING *, COALESCE(is_public, FALSE) AS is_public, "
        "COALESCE(usage_tokens, 0) AS usage_tokens, "
        "COALESCE(visibility, 'private') AS visibility"
    )

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else None


async def db_delete_session(session_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM playbook.sessions WHERE id = $1", session_id)
    return result.endswith("1")


# ── Session fork ───────────────────────────────────────────────────────────────

async def db_fork_session(source_id: str, new_owner_sid: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.sessions (title, query, report_markdown, message_history, trace_steps, owner_sid, visibility)
            SELECT 'Fork: ' || title, query, report_markdown, message_history, '[]'::jsonb, $2, 'private'
            FROM playbook.sessions WHERE id=$1::uuid
            RETURNING *, COALESCE(is_public, FALSE) AS is_public,
                         COALESCE(usage_tokens, 0) AS usage_tokens,
                         COALESCE(visibility, 'private') AS visibility
            """,
            source_id, new_owner_sid,
        )
    return _row_to_dict(row)


# ── Session subscriptions ──────────────────────────────────────────────────────

async def db_subscribe(session_id: str, user_sid: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.session_subscriptions (session_id, user_sid) VALUES ($1::uuid, $2) ON CONFLICT DO NOTHING",
            session_id, user_sid,
        )


async def db_unsubscribe(session_id: str, user_sid: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.session_subscriptions WHERE session_id=$1::uuid AND user_sid=$2",
            session_id, user_sid,
        )


async def db_is_subscribed(session_id: str, user_sid: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM playbook.session_subscriptions WHERE session_id=$1::uuid AND user_sid=$2",
            session_id, user_sid,
        )
    return row is not None


async def db_get_subscriber_sids(session_id: str) -> list[str]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_sid FROM playbook.session_subscriptions WHERE session_id=$1::uuid",
            session_id,
        )
    return [r["user_sid"] for r in rows]


# ── Session presence ───────────────────────────────────────────────────────────

async def db_heartbeat_presence(session_id: str, user_sid: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.session_presence (session_id, user_sid, last_seen)
            VALUES ($1::uuid, $2, NOW())
            ON CONFLICT (session_id, user_sid) DO UPDATE SET last_seen=NOW()
            """,
            session_id, user_sid,
        )


async def db_get_active_viewers(session_id: str, window_seconds: int = 30) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sp.user_sid, u.display_name, u.avatar_url
            FROM playbook.session_presence sp
            JOIN playbook.users u ON sp.user_sid = u.sid
            WHERE sp.session_id=$1::uuid AND sp.last_seen > NOW() - ($2 || ' seconds')::interval
            ORDER BY sp.last_seen DESC
            """,
            session_id, str(window_seconds),
        )
    result = []
    for r in rows:
        d = dict(r)
        if "avatar_url" in d and d.get("avatar_url") is None:
            d["avatar_url"] = None
        result.append(d)
    return result


# ── Session diff ───────────────────────────────────────────────────────────────

async def db_get_session_diff(session_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT parent_session_id, report_markdown FROM playbook.sessions WHERE id=$1::uuid",
            session_id,
        )
    if not row or not row["parent_session_id"]:
        return None
    parent_id = str(row["parent_session_id"])
    current_md = row["report_markdown"] or ""
    async with _acquire() as conn:
        parent_row = await conn.fetchrow(
            "SELECT report_markdown, created_at FROM playbook.sessions WHERE id=$1::uuid",
            parent_id,
        )
    if not parent_row:
        return None
    return {
        "current_markdown": current_md,
        "previous_markdown": parent_row["report_markdown"] or "",
        "previous_id": parent_id,
        "previous_date": parent_row["created_at"].isoformat() if parent_row["created_at"] else None,
    }

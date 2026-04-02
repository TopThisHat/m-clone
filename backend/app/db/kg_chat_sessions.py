"""Database layer for KG chat sessions and messages.

All queries are team-scoped and use parameterized asyncpg queries.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg

from ._pool import _acquire


def _session_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    if "updated_at" in d and d["updated_at"] is not None:
        d["updated_at"] = d["updated_at"].isoformat()
    return d


def _message_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "session_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "tool_calls" in d and isinstance(d["tool_calls"], str):
        d["tool_calls"] = json.loads(d["tool_calls"])
    if "entity_highlights" in d and d["entity_highlights"] is not None:
        d["entity_highlights"] = [str(uid) for uid in d["entity_highlights"]]
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_create_chat_session(
    team_id: str,
    user_sid: str,
) -> dict[str, Any]:
    """Create a new KG chat session scoped to a team and user."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_chat_sessions (team_id, user_sid)
            VALUES ($1::uuid, $2)
            RETURNING *
            """,
            team_id,
            user_sid,
        )
    return _session_to_dict(row)


async def db_get_chat_session(
    session_id: str,
    team_id: str,
) -> dict[str, Any] | None:
    """Fetch a chat session by ID, scoped to the team."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM playbook.kg_chat_sessions
            WHERE id = $1::uuid AND team_id = $2::uuid
            """,
            session_id,
            team_id,
        )
    return _session_to_dict(row) if row else None


async def db_list_chat_sessions(
    team_id: str,
    user_sid: str,
) -> list[dict[str, Any]]:
    """List all chat sessions for a user within a team, newest first."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.kg_chat_sessions
            WHERE team_id = $1::uuid AND user_sid = $2
            ORDER BY updated_at DESC
            """,
            team_id,
            user_sid,
        )
    return [_session_to_dict(r) for r in rows]


async def db_add_chat_message(
    session_id: str,
    role: str,
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
    entity_highlights: list[str] | None = None,
) -> dict[str, Any]:
    """Append a message to a chat session and bump session updated_at.

    Args:
        session_id: UUID of the parent session.
        role: One of 'user', 'assistant', 'tool'.
        content: Text content of the message.
        tool_calls: Serialized OpenAI tool_calls array (assistant role).
        tool_call_id: ID from the tool call response (tool role).
        entity_highlights: List of entity UUIDs mentioned in this message.
    """
    tool_calls_json = json.dumps(tool_calls) if tool_calls is not None else None
    highlights_uuids = (
        [UUID(eid) for eid in entity_highlights] if entity_highlights else None
    )

    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_chat_messages
                (session_id, role, content, tool_calls, tool_call_id, entity_highlights)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6::uuid[])
            RETURNING *
            """,
            session_id,
            role,
            content,
            tool_calls_json,
            tool_call_id,
            highlights_uuids,
        )
        # Bump session updated_at
        await conn.execute(
            "UPDATE playbook.kg_chat_sessions SET updated_at = NOW() WHERE id = $1::uuid",
            session_id,
        )
    return _message_to_dict(row)


async def db_get_chat_messages(
    session_id: str,
) -> list[dict[str, Any]]:
    """Return all messages for a session ordered chronologically."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.kg_chat_messages
            WHERE session_id = $1::uuid
            ORDER BY created_at ASC
            """,
            session_id,
        )
    return [_message_to_dict(r) for r in rows]


async def db_delete_chat_session(
    session_id: str,
    team_id: str,
) -> bool:
    """Delete a chat session (cascades to messages). Returns True if deleted."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.kg_chat_sessions
            WHERE id = $1::uuid AND team_id = $2::uuid
            """,
            session_id,
            team_id,
        )
    # asyncpg execute returns "DELETE N" string
    return result.endswith("1")


async def db_cleanup_expired_chat_sessions(
    days: int = 30,
) -> int:
    """Delete sessions older than `days` days. Returns number deleted."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.kg_chat_sessions
            WHERE updated_at < NOW() - ($1 || ' days')::INTERVAL
            """,
            str(days),
        )
    count_str = result.split()[-1]
    return int(count_str) if count_str.isdigit() else 0

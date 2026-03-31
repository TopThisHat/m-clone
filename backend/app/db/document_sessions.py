"""PostgreSQL persistence for document sessions.

Stores the full extracted document list (including text) for each session as
JSONB.  Acts as a durable fallback when Redis keys expire or are evicted.

Public API
----------
pg_upsert_document_session  — write (or overwrite) a session
pg_get_document_session     — read a session; returns None if missing / expired
pg_delete_expired_sessions  — cleanup job; returns number of rows deleted
"""
from __future__ import annotations

import json
import logging

from app.config import settings

from ._pool import _acquire

logger = logging.getLogger(__name__)


async def pg_upsert_document_session(
    session_key: str,
    docs: list[dict],
    ttl_hours: int | None = None,
) -> None:
    """Write (or overwrite) the full docs list for *session_key*.

    Args:
        session_key: UUID string used as the primary key.
        docs: List of doc dicts — each must contain at minimum ``filename``,
              ``text``, ``type``, and ``char_count``.
        ttl_hours: Override TTL in hours.  Defaults to ``settings.redis_ttl_hours``
                   so Redis and PG expiry stay aligned.
    """
    hours = ttl_hours if ttl_hours is not None else settings.redis_ttl_hours
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.document_sessions (session_key, texts, expires_at)
            VALUES ($1::uuid, $2::jsonb, NOW() + ($3 || ' hours')::interval)
            ON CONFLICT (session_key) DO UPDATE
                SET texts      = EXCLUDED.texts,
                    expires_at = EXCLUDED.expires_at
            """,
            session_key,
            json.dumps(docs),
            str(hours),
        )


async def pg_get_document_session(session_key: str) -> list[dict] | None:
    """Return the docs list for *session_key*, or ``None`` if missing/expired."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT texts
            FROM playbook.document_sessions
            WHERE session_key = $1::uuid
              AND expires_at > NOW()
            """,
            session_key,
        )
    if row is None:
        return None
    raw = row["texts"]
    if isinstance(raw, str):
        return json.loads(raw)
    # asyncpg may return the JSONB already decoded
    return list(raw)


async def pg_delete_expired_sessions() -> int:
    """Delete all expired ``document_sessions`` rows.

    Returns the number of rows deleted.  Idempotent — safe to call on every
    scheduler tick.
    """
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.document_sessions WHERE expires_at < NOW()"
        )
    # asyncpg returns e.g. "DELETE 3"
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0

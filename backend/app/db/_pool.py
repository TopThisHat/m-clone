from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


class DatabaseNotConfigured(RuntimeError):
    pass


def _resolve_connection() -> tuple[str, str | None]:
    """Return (dsn, ssl_mode). Prefers AWS secret over DATABASE_URL."""
    if settings.aws_secret_name:
        from app.secrets import build_dsn, get_db_secret
        secret = get_db_secret(settings.aws_secret_name, settings.aws_region)
        return build_dsn(secret), "require"
    if settings.database_url:
        return settings.database_url, None
    raise DatabaseNotConfigured(
        "No database configured. Set DATABASE_URL or AWS_SECRET_NAME."
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _get_lock():
        if _pool is not None:  # another coroutine beat us here
            return _pool
        dsn, ssl_mode = _resolve_connection()
        async def _set_search_path(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path TO playbook, public")

        kwargs: dict[str, Any] = {"dsn": dsn, "init": _set_search_path}
        if ssl_mode:
            kwargs["ssl"] = ssl_mode
        _pool = await asyncpg.create_pool(**kwargs)
        logger.info("DB pool created (ssl=%s, search_path=playbook)", ssl_mode or "off")
        return _pool


async def _reset_pool() -> None:
    """
    Tear down the current pool and evict the cached secret so that the next
    get_pool() call re-fetches credentials and creates a fresh pool.
    Called automatically when a credential-rotation auth error is detected.
    """
    global _pool
    async with _get_lock():
        old_pool, _pool = _pool, None
        if settings.aws_secret_name:
            from app.secrets import invalidate_db_secret
            invalidate_db_secret()
    if old_pool is not None:
        try:
            await old_pool.close()
        except Exception:
            pass
    logger.warning("DB pool reset — fresh credentials will be fetched on next request")


# Errors that indicate the password has changed (rotation).
# asyncpg raises InvalidPasswordError when it can't authenticate a new connection.
_AUTH_ERRORS = (
    asyncpg.exceptions.InvalidPasswordError,
    asyncpg.exceptions.PostgresConnectionError,
)


@asynccontextmanager
async def _acquire():
    """
    Async context manager that yields a DB connection from the pool.

    On the first auth error (InvalidPasswordError / PostgresConnectionError) it
    assumes the secret was rotated, resets the pool, re-fetches the secret, and
    retries the acquire once before re-raising.
    """
    pool = await get_pool()
    try:
        conn = await pool.acquire()
    except _AUTH_ERRORS as exc:
        logger.warning("DB auth error — attempting rotation recovery: %s", exc)
        await _reset_pool()
        pool = await get_pool()
        conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


@asynccontextmanager
async def _acquire_team(team_id: str | None):
    """Async context manager that yields a DB connection with team context set.

    Sets ``SET LOCAL app.current_team_id`` for row-level security policies.
    The SET LOCAL is transaction-scoped and automatically reverts when the
    connection is released back to the pool.

    If team_id is None, the setting is not applied (useful for non-team queries).
    """
    pool = await get_pool()
    try:
        conn = await pool.acquire()
    except _AUTH_ERRORS as exc:
        logger.warning("DB auth error — attempting rotation recovery: %s", exc)
        await _reset_pool()
        pool = await get_pool()
        conn = await pool.acquire()
    try:
        if team_id:
            await conn.execute(
                "SET LOCAL app.current_team_id = $1", team_id,
            )
        yield conn
    finally:
        await pool.release(conn)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

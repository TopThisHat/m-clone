from __future__ import annotations

import asyncio

import asyncpg

from job_runner.config import settings

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> asyncpg.Pool:
    global _pool

    async def _set_search_path(conn: asyncpg.Connection) -> None:
        await conn.execute("SET search_path TO playbook, public")

    _pool = await asyncpg.create_pool(dsn=settings.database_url, init=_set_search_path)
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await asyncio.wait_for(_pool.close(), timeout=5.0)
        except asyncio.TimeoutError:
            _pool.terminate()
        _pool = None

from __future__ import annotations

import asyncpg

from job_runner.config import settings

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn=settings.database_url)
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

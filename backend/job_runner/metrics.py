"""
Lightweight asyncio HTTP server exposing /healthz, /readyz, and /metrics endpoints.
"""
from __future__ import annotations

import json
import time

from aiohttp import web

_start_time = time.time()
_counters: dict[str, int] = {"jobs_dispatched": 0, "jobs_reclaimed": 0}


def inc(key: str, n: int = 1) -> None:
    _counters[key] = _counters.get(key, 0) + n


async def _handle_healthz(request: web.Request) -> web.Response:
    return web.Response(
        text=json.dumps({"status": "ok"}),
        content_type="application/json",
    )


async def _handle_readyz(request: web.Request) -> web.Response:
    result: dict[str, str] = {}
    status_code = 200

    # Check PG pool
    try:
        from app.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        result["pg"] = "ok"
    except Exception:
        result["pg"] = "error"
        status_code = 503

    # Check Redis
    try:
        from app.streams import get_redis
        r = await get_redis()
        await r.ping()
        result["redis"] = "ok"
    except Exception:
        result["redis"] = "error"
        status_code = 503

    result["status"] = "ready" if status_code == 200 else "not_ready"
    return web.Response(
        text=json.dumps(result),
        content_type="application/json",
        status=status_code,
    )


async def _handle_health(request: web.Request) -> web.Response:
    data = {"status": "ok", "uptime_seconds": int(time.time() - _start_time)}
    return web.Response(text=json.dumps(data), content_type="application/json")


async def _handle_metrics(request: web.Request) -> web.Response:
    data = {**_counters, "uptime_seconds": int(time.time() - _start_time)}
    return web.Response(text=json.dumps(data), content_type="application/json")


async def start_metrics_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/healthz", _handle_healthz)
    app.router.add_get("/readyz", _handle_readyz)
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/metrics", _handle_metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

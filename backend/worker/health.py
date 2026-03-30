"""
Minimal asyncio HTTP health server for the worker process.

Endpoints:
  GET /healthz  — liveness: always 200 {"status": "ok"}
  GET /readyz   — readiness: checks PG, Redis, and consumer loop state
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from worker.consumer import WorkflowConsumer


async def _handle_healthz(request: web.Request) -> web.Response:
    return web.Response(
        text=json.dumps({"status": "ok"}),
        content_type="application/json",
    )


def _make_readyz_handler(consumer: "WorkflowConsumer"):
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

        # Check consumer loops: healthy if at least one loop task is still running
        active_loops = sum(1 for t in consumer._loop_tasks if not t.done())
        if active_loops > 0:
            result["consumers"] = "ok"
        else:
            result["consumers"] = "error"
            status_code = 503

        result["status"] = "ready" if status_code == 200 else "not_ready"
        return web.Response(
            text=json.dumps(result),
            content_type="application/json",
            status=status_code,
        )

    return _handle_readyz


async def start_health_server(port: int, consumer: "WorkflowConsumer") -> None:
    """Start the worker health HTTP server on the given port."""
    app = web.Application()
    app.router.add_get("/healthz", _handle_healthz)
    app.router.add_get("/readyz", _make_readyz_handler(consumer))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

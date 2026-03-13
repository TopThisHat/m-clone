"""
Lightweight asyncio HTTP server exposing /health and /metrics endpoints.
"""
from __future__ import annotations

import json
import time

from aiohttp import web

_start_time = time.time()
_counters: dict[str, int] = {"jobs_processed": 0, "jobs_failed": 0, "jobs_dead": 0}
_gauges: dict[str, int] = {"active_jobs": 0}


def inc(key: str, n: int = 1) -> None:
    _counters[key] = _counters.get(key, 0) + n


def set_gauge(key: str, v: int) -> None:
    _gauges[key] = v


async def _handle_health(request: web.Request) -> web.Response:
    data = {"status": "ok", "uptime_seconds": int(time.time() - _start_time)}
    return web.Response(text=json.dumps(data), content_type="application/json")


async def _handle_metrics(request: web.Request) -> web.Response:
    data = {**_counters, **_gauges, "uptime_seconds": int(time.time() - _start_time)}
    return web.Response(text=json.dumps(data), content_type="application/json")


async def start_metrics_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/metrics", _handle_metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

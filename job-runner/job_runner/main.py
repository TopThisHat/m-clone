"""
job-runner entry point.

Start with:
    cd job-runner && python -m job_runner.main
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Allow importing backend app/worker modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import app.agent  # noqa: F401 — registers research_agent tool decorators
import job_runner.workflows  # noqa: F401 — registers all workflow handlers

from job_runner.config import settings
from job_runner.db import close_pool, init_db_pool
from job_runner.worker import WorkerPool

logger = logging.getLogger(__name__)

_pool: WorkerPool | None = None


async def _shutdown(worker: WorkerPool) -> None:
    logger.info("Shutdown signal received — draining…")
    await worker.drain()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    await init_db_pool()
    logger.info("DB pool initialized")

    from job_runner.metrics import start_metrics_server
    await start_metrics_server(settings.metrics_port)
    logger.info("Metrics server listening on port %d", settings.metrics_port)

    worker = WorkerPool()

    _shutdown_triggered = False

    def _make_signal_handler(w: WorkerPool):
        def handler():
            nonlocal _shutdown_triggered
            if _shutdown_triggered:
                return
            _shutdown_triggered = True
            asyncio.create_task(_shutdown(w))
        return handler

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _make_signal_handler(worker))

    try:
        await worker.run()
    finally:
        await close_pool()
        logger.info("job-runner stopped")


if __name__ == "__main__":
    asyncio.run(main())

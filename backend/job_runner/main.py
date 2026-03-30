"""
Job runner entry point — pure dispatcher.

Dequeues jobs from PostgreSQL and publishes them to Redis Streams
for workers to consume. Does NOT execute workflow logic.

Start with:
    cd backend && python -m job_runner.main
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from dotenv import load_dotenv
load_dotenv()

from job_runner.config import settings
from job_runner.dispatcher import Dispatcher

logger = logging.getLogger(__name__)


async def _shutdown(dispatcher: Dispatcher) -> None:
    logger.info("Shutdown signal received — draining...")
    await dispatcher.drain()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Warm the shared DB pool (used by app.job_queue)
    from app.db import get_pool
    await get_pool()
    logger.info("DB pool initialized")

    from job_runner.metrics import start_metrics_server
    await start_metrics_server(settings.metrics_port)
    logger.info("Metrics server listening on port %d", settings.metrics_port)

    from app.streams import get_redis
    r = await get_redis()
    await r.ping()
    logger.info("Redis connection verified")

    dispatcher = Dispatcher()

    _shutdown_triggered = False

    def _make_signal_handler(d: Dispatcher):
        def handler():
            nonlocal _shutdown_triggered
            if _shutdown_triggered:
                return
            _shutdown_triggered = True
            asyncio.create_task(_shutdown(d))
        return handler

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _make_signal_handler(dispatcher))
    else:
        def _win_handler(signum, frame):
            _make_signal_handler(dispatcher)()
        signal.signal(signal.SIGTERM, _win_handler)
        signal.signal(signal.SIGINT, _win_handler)

    try:
        await dispatcher.run()
    finally:
        from app.streams import close_redis
        await close_redis()
        from app.db import close_pool
        await close_pool()
        logger.info("job-runner stopped")


if __name__ == "__main__":
    asyncio.run(main())

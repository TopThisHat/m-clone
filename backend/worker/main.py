"""
Worker entry point — workflow executor.

Consumes jobs from Redis Streams and executes workflow logic
(validation, research, entity extraction). Scale by running
multiple worker instances.

Start with:
    cd backend && python -m worker.main

Environment variables:
    WORKER_STREAMS       — comma-separated streams or "all" (default: all)
    WORKER_CONCURRENCY   — max concurrent jobs (default: 20)
    ENABLE_EXTRACTION    — run entity extraction consumer (default: true)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so 'app' and 'worker' imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import app.agent  # noqa: F401 — registers research_agent tool decorators
import worker.workflows  # noqa: F401 — registers all workflow handlers

from worker.config import settings

logger = logging.getLogger(__name__)


async def _shutdown(consumer, extraction_task) -> None:
    logger.info("Shutdown signal received — draining...")
    await consumer.drain()
    if extraction_task is not None:
        extraction_task.cancel()
        try:
            await extraction_task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Initialize the OpenAI client (same factory the app uses — handles
    # Azure/proxy/standard mode).  Eagerly created so aws_mode fails fast.
    from app.openai_factory import initialize as init_openai
    init_openai()
    logger.info("OpenAI client initialized")

    # Warm the shared DB pool
    from app.db import get_pool
    await get_pool()
    logger.info("DB pool initialized")

    # Start workflow consumer
    from worker.consumer import WorkflowConsumer
    consumer = WorkflowConsumer()

    # Optionally start entity extraction worker
    extraction_task = None
    if settings.enable_extraction:
        from worker.entity_extraction import run_extraction_worker
        extraction_task = asyncio.create_task(run_extraction_worker())
        logger.info("Entity extraction worker started")

    _shutdown_triggered = False

    def _make_signal_handler():
        def handler():
            nonlocal _shutdown_triggered
            if _shutdown_triggered:
                return
            _shutdown_triggered = True
            asyncio.create_task(_shutdown(consumer, extraction_task))
        return handler

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _make_signal_handler())
    else:
        def _win_handler(signum, frame):
            _make_signal_handler()()
        signal.signal(signal.SIGTERM, _win_handler)
        signal.signal(signal.SIGINT, _win_handler)

    try:
        await consumer.run()
    finally:
        from app.streams import close_redis
        await close_redis()
        from app.db import close_pool
        await close_pool()
        logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())

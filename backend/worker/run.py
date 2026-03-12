"""
Backend worker entry point (KG extraction only).

Validation jobs are now handled by the job-runner service.

Start with:
    cd backend && python -m worker.run
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so 'app' and 'worker' imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before any imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import app.agent  # noqa: F401 — registers research_agent tool decorators
from worker.entity_extraction import run_extraction_worker

logger = logging.getLogger(__name__)


async def main() -> None:
    from app.db import get_pool
    await get_pool()  # warm up pool

    logger.info("Starting entity extraction worker")
    await run_extraction_worker()  # runs forever


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())

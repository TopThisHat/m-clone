"""
DBOS worker entry point.

Start with:
    cd backend && python -m worker.run

This process connects to the same PostgreSQL, polls the DBOS system schema
for pending workflows, and executes them with durable checkpointing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so 'app' and 'worker' imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env before any imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import app.agent  # noqa: F401 — registers research_agent tool decorators
from worker import workflows  # noqa: F401 — registers @DBOS.workflow / @DBOS.step decorators
from worker.entity_extraction import run_extraction_worker

logger = logging.getLogger(__name__)


async def main() -> None:
    from dbos import DBOS, DBOSConfig

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        from app.config import settings
        database_url = settings.database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to run the Scout worker")

    config: DBOSConfig = {
        "name": "scout-worker",
        "database_url": database_url,
    }
    DBOS(config=config)
    DBOS.launch()  # starts background executor polling the DB
    logger.info("Scout DBOS worker launched — polling for pending workflows")

    # Start entity extraction consumer alongside DBOS
    asyncio.create_task(run_extraction_worker())
    logger.info("Entity extraction worker task started")

    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())

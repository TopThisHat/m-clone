"""
Asyncio background scheduler for running due monitors.
No external dependencies — pure asyncio loop sleeping 60 s between polls.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


async def _run_monitor(monitor: dict) -> None:
    from app.agent.streaming import stream_research
    from app.db import db_create_session, db_update_monitor_run
    from app.dependencies import get_agent_deps

    final_md: str | None = None
    deps = get_agent_deps()

    try:
        current_event = ""
        async for chunk in stream_research(query=monitor["query"], deps=deps):
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event == "final_report":
                    try:
                        payload = json.loads(line[6:])
                        final_md = payload.get("markdown", "")
                    except Exception:
                        pass
    except Exception as exc:
        logger.error("Monitor %s failed during stream: %s", monitor["id"], exc)
        return

    if final_md:
        date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            await db_create_session({
                "owner_sid": monitor["owner_sid"],
                "title": f"{monitor['label']} \u2014 {date_str}",
                "query": monitor["query"],
                "report_markdown": final_md,
                "message_history": [],
                "trace_steps": [],
            })
        except Exception as exc:
            logger.error("Monitor %s failed to save session: %s", monitor["id"], exc)

    try:
        await db_update_monitor_run(monitor["id"], monitor["frequency"])
    except Exception as exc:
        logger.error("Monitor %s failed to update run time: %s", monitor["id"], exc)


async def _loop() -> None:
    from app.db import db_get_due_monitors, DatabaseNotConfigured

    while True:
        await asyncio.sleep(60)
        try:
            due = await db_get_due_monitors()
        except (DatabaseNotConfigured, Exception) as exc:
            logger.debug("Scheduler poll skipped: %s", exc)
            continue

        for monitor in due:
            asyncio.create_task(_run_monitor(monitor))


def start() -> None:
    global _task
    _task = asyncio.create_task(_loop())
    logger.info("Monitor scheduler started")


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
        logger.info("Monitor scheduler stopped")

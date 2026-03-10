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


async def _trigger_campaign(campaign: dict) -> None:
    from app.db import db_create_validation_job, db_update_campaign_next_run
    try:
        from croniter import croniter
        from datetime import timezone
        cron = croniter(campaign["schedule"])
        next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.error("Campaign %s has invalid schedule '%s': %s", campaign["id"], campaign.get("schedule"), exc)
        return

    try:
        job = await db_create_validation_job(
            campaign_id=campaign["id"],
            triggered_by="scheduler",
        )
    except Exception as exc:
        logger.error("Campaign %s: failed to create validation job: %s", campaign["id"], exc)
        return

    try:
        from dbos import DBOS
        from worker.workflows import validate_job_workflow
        DBOS.start_workflow(validate_job_workflow, job["id"])
        logger.info("Scheduled job %s started for campaign %s", job["id"], campaign["id"])
    except ImportError:
        logger.warning("DBOS not installed — scheduled job %s queued but no worker will process it", job["id"])
    except Exception as exc:
        logger.error("Campaign %s: failed to start DBOS workflow: %s", campaign["id"], exc)

    try:
        await db_update_campaign_next_run(campaign["id"], next_run)
    except Exception as exc:
        logger.error("Campaign %s: failed to update next_run_at: %s", campaign["id"], exc)


async def _loop() -> None:
    from app.db import db_get_due_monitors, db_get_due_campaigns, DatabaseNotConfigured

    while True:
        await asyncio.sleep(60)
        try:
            due = await db_get_due_monitors()
        except (DatabaseNotConfigured, Exception) as exc:
            logger.debug("Scheduler poll skipped: %s", exc)
            continue

        for monitor in due:
            asyncio.create_task(_run_monitor(monitor))

        try:
            due_campaigns = await db_get_due_campaigns()
        except Exception as exc:
            logger.debug("Campaign scheduler poll skipped: %s", exc)
            due_campaigns = []

        for campaign in due_campaigns:
            asyncio.create_task(_trigger_campaign(campaign))


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

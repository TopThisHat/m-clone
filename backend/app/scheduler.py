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
    from app.db import db_create_session, db_list_sessions, db_update_monitor_run
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
                        logger.debug(
                            "Monitor %s: failed to parse final_report SSE payload",
                            monitor["id"], exc_info=True,
                        )
    except Exception as exc:
        logger.error("Monitor %s failed during stream: %s", monitor["id"], exc)
        return

    if final_md:
        date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            # Find the most recent previous session for this monitor query to link as parent
            previous_sessions = await db_list_sessions(owner_sid=monitor["owner_sid"])
            parent_session_id = None
            for s in previous_sessions:
                if s.get("query") == monitor["query"]:
                    parent_session_id = s["id"]
                    break

            session_data: dict = {
                "owner_sid": monitor["owner_sid"],
                "title": f"{monitor['label']} \u2014 {date_str}",
                "query": monitor["query"],
                "report_markdown": final_md,
                "message_history": [],
                "trace_steps": [],
            }
            new_session = await db_create_session(session_data)
            # Set parent_session_id if we found a previous run
            if parent_session_id:
                from app.db import db_update_session
                await db_update_session(new_session["id"], {"parent_session_id": parent_session_id})
        except Exception as exc:
            logger.error("Monitor %s failed to save session: %s", monitor["id"], exc)

    try:
        await db_update_monitor_run(monitor["id"], monitor["frequency"])
    except Exception as exc:
        logger.error("Monitor %s failed to update run time: %s", monitor["id"], exc)


async def _trigger_campaign(campaign: dict) -> None:
    from app.db import db_update_campaign_next_run
    try:
        from croniter import croniter
        from datetime import timezone
        cron = croniter(campaign["schedule"])
        next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.error("Campaign %s has invalid schedule '%s': %s", campaign["id"], campaign.get("schedule"), exc)
        return

    try:
        from app.db import db_create_and_enqueue_validation_job, db_list_entities, db_list_attributes
        ent_page = await db_list_entities(campaign["id"], limit=0)
        attr_page = await db_list_attributes(campaign["id"], limit=0)
        entity_ids = [e["id"] for e in ent_page["items"]]
        attribute_ids = [a["id"] for a in attr_page["items"]]
        job = await db_create_and_enqueue_validation_job(
            campaign_id=campaign["id"],
            triggered_by="scheduler",
            entity_filter=entity_ids,
            attribute_filter=attribute_ids,
        )
        logger.info("Scheduled job %s created and enqueued for campaign %s", job["id"], campaign["id"])
    except Exception as exc:
        logger.error("Campaign %s: failed to create/enqueue validation job: %s", campaign["id"], exc)
        return

    try:
        await db_update_campaign_next_run(campaign["id"], next_run)
    except Exception as exc:
        logger.error("Campaign %s: failed to update next_run_at: %s", campaign["id"], exc)


async def _loop() -> None:
    from app.db import db_get_due_monitors, db_get_due_campaigns, DatabaseNotConfigured
    from app.db._pool import _acquire

    # Unique advisory lock key — only one instance should fire the scheduler tick.
    _SCHEDULER_LOCK_KEY = 8675310

    while True:
        await asyncio.sleep(60)
        try:
            async with _acquire() as conn:
                # pg_try_advisory_lock is session-scoped and non-blocking.
                # Only one instance wins the lock; others skip this tick.
                got_lock: bool = await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1)", _SCHEDULER_LOCK_KEY
                )
                if not got_lock:
                    logger.debug("Scheduler tick skipped — another instance holds the lock")
                    continue

                try:
                    try:
                        due = await db_get_due_monitors()
                    except (DatabaseNotConfigured, Exception) as exc:
                        logger.debug("Scheduler poll skipped: %s", exc)
                        continue

                    try:
                        due_campaigns = await db_get_due_campaigns()
                    except Exception as exc:
                        logger.debug("Campaign scheduler poll skipped: %s", exc)
                        due_campaigns = []
                finally:
                    await conn.execute(
                        "SELECT pg_advisory_unlock($1)", _SCHEDULER_LOCK_KEY
                    )

        except Exception as exc:
            logger.debug("Scheduler poll skipped: %s", exc)
            continue

        for monitor in due:
            asyncio.create_task(_run_monitor(monitor))

        for campaign in due_campaigns:
            asyncio.create_task(_trigger_campaign(campaign))

        asyncio.create_task(_cleanup_document_sessions())


async def _cleanup_document_sessions() -> None:
    """Delete expired document_sessions rows from PostgreSQL."""
    try:
        from app.db.document_sessions import pg_delete_expired_sessions
        deleted = await pg_delete_expired_sessions()
        if deleted:
            logger.info("Scheduler: cleaned up %d expired document_sessions rows", deleted)
    except Exception as exc:
        logger.debug("Scheduler: document_sessions cleanup skipped: %s", exc)


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

"""
WorkflowConsumer: consumes jobs from Redis Streams and executes workflows.

Each consumer instance joins a consumer group, so multiple workers can
process the same stream in parallel without duplicates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
from typing import Any

from worker.config import settings
from worker.registry import registry

logger = logging.getLogger(__name__)


def _calc_backoff(attempts: int, base: float) -> float:
    """Exponential backoff with +/-25% jitter."""
    delay = base * (2 ** attempts)
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    return max(1.0, delay + jitter)


class WorkflowConsumer:
    """
    Consumes from one or more Redis Streams and executes registered workflows.

    Each stream gets its own asyncio task running a consume loop.  A shared
    semaphore bounds total concurrency across all streams.
    """

    def __init__(self, streams: list[str] | None = None) -> None:
        self._streams = streams or settings.get_streams()
        self._sem = asyncio.Semaphore(settings.worker_concurrency)
        self._shutdown = asyncio.Event()
        self._active: set[asyncio.Task] = set()
        self._consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}"
        self._type_sems: dict[str, asyncio.Semaphore] = {
            jtype: asyncio.Semaphore(limit)
            for jtype, limit in settings.per_type_limits.items()
        }

    async def run(self) -> None:
        logger.info(
            "WorkflowConsumer starting (consumer=%s, streams=%s, concurrency=%d)",
            self._consumer_name, self._streams, settings.worker_concurrency,
        )

        # Ensure consumer groups exist
        from app.streams import GROUP_WORKERS, create_consumer_group
        for stream in self._streams:
            await create_consumer_group(stream, GROUP_WORKERS)

        # Start one consume loop per stream
        tasks = [
            asyncio.create_task(self._consume_loop(stream))
            for stream in self._streams
        ]
        try:
            await self._shutdown.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def drain(self, timeout: int = 30) -> None:
        logger.info("WorkflowConsumer draining...")
        self._shutdown.set()
        if self._active:
            logger.info("Waiting for %d in-flight job(s)...", len(self._active))
            done, pending = await asyncio.wait(
                list(self._active), timeout=timeout,
            )
            if pending:
                logger.warning("%d jobs did not finish within drain timeout", len(pending))
        logger.info("WorkflowConsumer drained")

    # ── Consume loop ──────────────────────────────────────────────────────

    async def _consume_loop(self, stream: str) -> None:
        from app.streams import GROUP_WORKERS, consume_jobs

        while not self._shutdown.is_set():
            try:
                messages = await consume_jobs(
                    stream,
                    GROUP_WORKERS,
                    self._consumer_name,
                    count=1,
                    block_ms=5000,
                )
                for msg_id, fields in messages:
                    await self._sem.acquire()
                    try:
                        task = asyncio.create_task(
                            self._process_message(stream, msg_id, fields)
                        )
                        self._active.add(task)
                        task.add_done_callback(
                            lambda t: (self._active.discard(t), self._sem.release())
                        )
                    except Exception:
                        self._sem.release()
                        raise
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Consume loop error on %s: %s", stream, exc)
                await asyncio.sleep(1)

    async def _process_message(
        self, stream: str, msg_id: str, fields: dict[str, str]
    ) -> None:
        """Process a single job message from Redis Stream."""
        from app.job_queue import ack as pg_ack, fail as pg_fail, mark_running
        from app.streams import GROUP_WORKERS, ack_job
        from worker.heartbeat import HeartbeatManager

        job_id = fields.get("job_id", "")
        job_type = fields.get("job_type", "")

        # Reconstruct the job dict that workflows expect
        payload_raw = fields.get("payload", "{}")
        try:
            payload = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            payload = {}

        job: dict[str, Any] = {
            "id": job_id,
            "job_type": job_type,
            "payload": payload,
            "parent_job_id": fields.get("parent_job_id") or None,
            "root_job_id": fields.get("root_job_id") or None,
            "attempts": int(fields.get("attempts", 0)),
            "max_attempts": int(fields.get("max_attempts", 3)),
            "validation_job_id": fields.get("validation_job_id") or None,
        }

        hb = HeartbeatManager(job_id, settings.heartbeat_interval)
        await mark_running(job_id)
        await hb.start()

        try:
            type_sem = self._type_sems.get(job_type)
            timeout = settings.type_timeouts.get(job_type, settings.default_job_timeout)

            if type_sem:
                async def _execute():
                    async with type_sem:
                        await registry.dispatch(job)
                coro = _execute()
            else:
                coro = registry.dispatch(job)

            await asyncio.wait_for(coro, timeout=timeout)
            await pg_ack(job_id)
            logger.info("Job %s (%s) done", job_id, job_type)

        except asyncio.TimeoutError:
            backoff = _calc_backoff(job.get("attempts", 0), settings.default_backoff_base)
            error_msg = f"Job timed out after {timeout}s"
            logger.error("Job %s (%s) timed out", job_id, job_type)
            went_dead = await pg_fail(job_id, error_msg, backoff)
            if went_dead:
                await registry.dispatch_on_dead(job)

        except Exception as exc:
            backoff = _calc_backoff(job.get("attempts", 0), settings.default_backoff_base)
            logger.error(
                "Job %s (%s) failed (attempt %d): %s",
                job_id, job_type, job.get("attempts", 0) + 1, exc,
            )
            went_dead = await pg_fail(job_id, str(exc), backoff)
            if went_dead:
                await registry.dispatch_on_dead(job)

        finally:
            await hb.stop()
            # Always ACK the Redis message — PG is source of truth for retries.
            # If the job failed, PG resets it to 'pending' and the dispatcher
            # will re-publish it to the stream.
            await ack_job(stream, GROUP_WORKERS, msg_id)

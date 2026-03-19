"""
Dispatcher: dequeues jobs from PostgreSQL and publishes them to Redis Streams.

The dispatcher does NOT execute workflow logic — it only routes jobs to the
appropriate Redis Stream for workers to consume.  Reclaim and reconciliation
loops ensure no jobs are lost.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket

import asyncpg

from job_runner.config import settings

logger = logging.getLogger(__name__)


async def _reconcile_finalize(validation_job_id: str, root_queue_job_id: str) -> None:
    """Finalize a stuck validation_job from the reconcile loop."""
    from app.job_queue import finalize_validation_job
    try:
        await finalize_validation_job(validation_job_id, root_queue_job_id)
    except Exception as exc:
        logger.error("Reconcile finalize failed for validation_job %s: %s", validation_job_id, exc)


class Dispatcher:
    """
    Dequeue from PostgreSQL → publish to Redis Streams.

    Loops:
      _poll_loop      — dequeue pending jobs, publish to the right stream
      _listen_loop    — LISTEN on pg_notify channel, wake poll loop
      _reclaim_loop   — reclaim stale jobs (heartbeat timeout)
      _reconcile_loop — finalize stuck validation_jobs
    """

    def __init__(self) -> None:
        self._shutdown = asyncio.Event()
        self._poll_finished = asyncio.Event()
        self._wake = asyncio.Event()
        self._worker_id = f"dispatcher-{socket.gethostname()}:{os.getpid()}"
        self._listen_conn: asyncpg.Connection | None = None

    async def run(self) -> None:
        logger.info("Dispatcher starting (id=%s)", self._worker_id)

        # Ensure consumer groups exist on all dispatch streams
        from app.streams import (
            JOB_TYPE_TO_STREAM,
            GROUP_WORKERS,
            create_consumer_group,
        )
        for stream in set(JOB_TYPE_TO_STREAM.values()):
            await create_consumer_group(stream, GROUP_WORKERS)

        reclaim_task = asyncio.create_task(self._reclaim_loop())
        reconcile_task = asyncio.create_task(self._reconcile_loop())
        listen_task = asyncio.create_task(self._listen_loop())
        try:
            await self._poll_loop()
        finally:
            reclaim_task.cancel()
            reconcile_task.cancel()
            listen_task.cancel()
            await asyncio.gather(reclaim_task, reconcile_task, listen_task, return_exceptions=True)

    async def drain(self, timeout: int = 30) -> None:
        logger.info("Dispatcher draining...")
        self._shutdown.set()
        self._wake.set()
        try:
            await asyncio.wait_for(self._poll_finished.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Poll loop did not finish within %ds during drain", timeout)
        logger.info("Dispatcher drained")

    # ── Internal loops ────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        from app.db import get_pool
        backoff = 1.0
        while not self._shutdown.is_set():
            conn: asyncpg.Connection | None = None
            try:
                pool = await get_pool()
                conn = await pool.acquire()
                self._listen_conn = conn
                await conn.add_listener(settings.listen_channel, self._on_notify)
                logger.debug("LISTEN on channel %s", settings.listen_channel)
                backoff = 1.0
                await self._shutdown.wait()
                break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("LISTEN connection lost (%s), reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
            finally:
                if conn is not None:
                    try:
                        await asyncio.shield(conn.remove_listener(settings.listen_channel, self._on_notify))
                    except Exception:
                        pass
                    try:
                        pool = await get_pool()
                        await asyncio.shield(pool.release(conn))
                    except Exception:
                        pass
                self._listen_conn = None

    def _on_notify(self, conn, pid, channel, payload) -> None:
        self._wake.set()

    async def _reclaim_loop(self) -> None:
        from app.job_queue import reclaim_stale
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(settings.reclaim_interval)
                await reclaim_stale(
                    settings.stale_threshold,
                    listen_channel=settings.listen_channel,
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Reclaim error: %s", exc)

    async def _reconcile_loop(self) -> None:
        """
        Safety-net: find validation_jobs stuck in 'running' where all queue
        children have reached a terminal state but finalization was never
        triggered.  Runs every 60s.
        """
        from app.db import get_pool
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(60)
                pool = await get_pool()
                async with pool.acquire() as conn:
                    stuck = await conn.fetch(
                        """
                        SELECT vj.id AS validation_job_id, root.id AS root_queue_job_id
                        FROM playbook.validation_jobs vj
                        JOIN playbook.job_queue root
                          ON root.validation_job_id = vj.id
                         AND root.job_type = 'validation_campaign'
                         AND root.status IN ('done', 'dead')
                        WHERE vj.status = 'running'
                          AND NOT EXISTS (
                              SELECT 1 FROM playbook.job_queue children
                              WHERE children.root_job_id = root.id
                                AND children.status NOT IN ('done', 'dead')
                          )
                        """
                    )
                for row in stuck:
                    logger.warning(
                        "Reconcile: validation_job %s stuck running with all children terminal — finalizing",
                        row["validation_job_id"],
                    )
                    asyncio.create_task(
                        _reconcile_finalize(
                            str(row["validation_job_id"]),
                            str(row["root_queue_job_id"]),
                        )
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Reconcile error: %s", exc)

    async def _poll_loop(self) -> None:
        from app.job_queue import dequeue
        from app.streams import JOB_TYPE_TO_STREAM, publish_job

        try:
            while not self._shutdown.is_set():
                jobs = await dequeue(self._worker_id, batch_size=10)

                for job in jobs:
                    job_type = job["job_type"]
                    stream = JOB_TYPE_TO_STREAM.get(job_type)
                    if not stream:
                        logger.error(
                            "No stream mapped for job_type=%s (job %s), skipping",
                            job_type, job["id"],
                        )
                        continue

                    # Serialise job for Redis Stream
                    payload_raw = job.get("payload") or {}
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw

                    msg_data = {
                        "job_id": str(job["id"]),
                        "job_type": job_type,
                        "payload": payload,
                        "parent_job_id": str(job["parent_job_id"]) if job.get("parent_job_id") else "",
                        "root_job_id": str(job["root_job_id"]) if job.get("root_job_id") else "",
                        "attempts": str(job.get("attempts", 0)),
                        "max_attempts": str(job.get("max_attempts", 3)),
                        "validation_job_id": str(job["validation_job_id"]) if job.get("validation_job_id") else "",
                    }

                    try:
                        await publish_job(stream, msg_data)
                        logger.debug("Dispatched job %s (%s) → %s", job["id"], job_type, stream)
                        from job_runner import metrics
                        metrics.inc("jobs_dispatched")
                    except Exception as exc:
                        logger.error("Failed to publish job %s to %s: %s", job["id"], stream, exc)
                        # Job stays 'claimed' in PG; reclaim loop will reset it

                if jobs:
                    continue  # immediately try for more

                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._poll_finished.set()

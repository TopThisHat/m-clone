"""
WorkerPool: semaphore-bounded async job executor with LISTEN/NOTIFY + stale reclaim.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import socket

import asyncpg

from job_runner.config import settings
from job_runner.heartbeat import HeartbeatManager
from job_runner.queue import ack, dequeue, fail, mark_running, reclaim_stale
from job_runner.registry import registry

logger = logging.getLogger(__name__)


async def _reconcile_finalize(validation_job_id: str, root_queue_job_id: str) -> None:
    """Finalize a stuck validation_job from the reconcile loop."""
    from job_runner.workflows.validation import finalize_validation_job
    try:
        await finalize_validation_job(validation_job_id, root_queue_job_id)
    except Exception as exc:
        logger.error("Reconcile finalize failed for validation_job %s: %s", validation_job_id, exc)


def _calc_backoff(attempts: int, base: float) -> float:
    """Exponential backoff with ±25% jitter."""
    delay = base * (2 ** attempts)
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    return max(1.0, delay + jitter)


class WorkerPool:
    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(settings.max_concurrency)
        self._shutdown = asyncio.Event()
        self._poll_finished = asyncio.Event()
        self._wake = asyncio.Event()
        self._active: set[asyncio.Task] = set()
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._listen_conn: asyncpg.Connection | None = None
        self._type_sems: dict[str, asyncio.Semaphore] = {
            jtype: asyncio.Semaphore(limit)
            for jtype, limit in settings.per_type_limits.items()
        }

    async def run(self) -> None:
        logger.info("WorkerPool starting (worker_id=%s, max_concurrency=%d)",
                    self._worker_id, settings.max_concurrency)
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
        """
        Signal shutdown and wait for in-flight jobs to finish.

        We wait for _poll_finished before snapshotting _active to close the
        race window where _poll_loop has dequeued jobs but not yet added their
        tasks to _active.
        """
        logger.info("WorkerPool draining…")
        self._shutdown.set()
        self._wake.set()  # unblock any sleeping wait_for
        try:
            await asyncio.wait_for(self._poll_finished.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Poll loop did not finish within %ds during drain", timeout)
        if self._active:
            logger.info("Waiting for %d in-flight job(s)…", len(self._active))
            await asyncio.gather(*list(self._active), return_exceptions=True)
        logger.info("WorkerPool drained")

    # ── Internal loops ────────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        from job_runner.db import get_pool
        pool = await get_pool()
        conn = await pool.acquire()
        self._listen_conn = conn
        try:
            await conn.add_listener(settings.listen_channel, self._on_notify)
            logger.debug("LISTEN on channel %s", settings.listen_channel)
            await self._shutdown.wait()
        finally:
            try:
                await conn.remove_listener(settings.listen_channel, self._on_notify)
            except Exception:
                pass
            await pool.release(conn)

    def _on_notify(self, conn, pid, channel, payload) -> None:
        self._wake.set()

    async def _reclaim_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(settings.reclaim_interval)
                await reclaim_stale(settings.stale_threshold)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Reclaim error: %s", exc)

    async def _reconcile_loop(self) -> None:
        """
        Safety-net: find validation_jobs stuck in 'running' where all queue
        children have reached a terminal state (done/dead) but finalization
        was never triggered (e.g. the pod that ran the last pair crashed after
        ack but before _maybe_finalize completed).
        Runs every 60 s.
        """
        from job_runner.db import get_pool as _get_pool
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(60)
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    stuck = await conn.fetch(
                        """
                        SELECT vj.id AS validation_job_id, root.id AS root_queue_job_id
                        FROM validation_jobs vj
                        JOIN job_queue root
                          ON root.validation_job_id = vj.id
                         AND root.job_type = 'validation_campaign'
                         AND root.status IN ('done', 'dead')
                        WHERE vj.status = 'running'
                          AND NOT EXISTS (
                              SELECT 1 FROM job_queue children
                              WHERE children.root_job_id = root.id
                                AND children.status NOT IN ('done', 'dead')
                          )
                        """
                    )
                for row in stuck:
                    logger.warning(
                        "Reconcile: validation_job %s is stuck running with all children terminal — finalizing",
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
        try:
            while not self._shutdown.is_set():
                free = settings.max_concurrency - len(self._active)
                if free > 0:
                    jobs = await dequeue(self._worker_id, batch_size=min(free, 10))
                    for job in jobs:
                        await self._sem.acquire()
                        try:
                            task = asyncio.create_task(self._run_job(job))
                            self._active.add(task)
                            task.add_done_callback(lambda t: (self._active.discard(t), self._sem.release()))
                        except Exception:
                            self._sem.release()
                            raise
                    if jobs:
                        continue  # immediately try for more

                # Clear before waiting to avoid losing notifications that arrive
                # between the previous iteration and this wait.
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
        finally:
            # Signal drain() that no more tasks will be added to _active.
            self._poll_finished.set()

    async def _run_job(self, job: dict) -> None:
        job_id = str(job["id"])
        job_type = job["job_type"]
        hb = HeartbeatManager(job_id, settings.heartbeat_interval)
        await mark_running(job_id)
        await hb.start()

        from job_runner import metrics
        metrics.set_gauge("active_jobs", len(self._active))

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
            await ack(job_id)
            metrics.inc("jobs_processed")
            logger.info("Job %s (%s) done", job_id, job_type)
        except asyncio.TimeoutError:
            backoff = _calc_backoff(job.get("attempts", 0), settings.default_backoff_base)
            error_msg = f"Job timed out after {timeout}s"
            logger.error("Job %s (%s) timed out", job_id, job_type)
            metrics.inc("jobs_failed")
            went_dead = await fail(job_id, error_msg, backoff)
            if went_dead:
                metrics.inc("jobs_dead")
                await registry.dispatch_on_dead(job)
        except Exception as exc:
            backoff = _calc_backoff(job.get("attempts", 0), settings.default_backoff_base)
            logger.error("Job %s (%s) failed (attempt %d): %s",
                         job_id, job_type, job.get("attempts", 0) + 1, exc)
            metrics.inc("jobs_failed")
            went_dead = await fail(job_id, str(exc), backoff)
            if went_dead:
                metrics.inc("jobs_dead")
                await registry.dispatch_on_dead(job)
        finally:
            await hb.stop()
            metrics.set_gauge("active_jobs", len(self._active))

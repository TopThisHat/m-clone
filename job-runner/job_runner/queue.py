"""
PostgreSQL-native job queue using FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from job_runner.db import get_pool

logger = logging.getLogger(__name__)


async def enqueue(
    job_type: str,
    payload: dict,
    *,
    parent_job_id: str | None = None,
    root_job_id: str | None = None,
    max_attempts: int | None = None,
    priority: int = 0,
    run_at: str | None = None,
    validation_job_id: str | None = None,
) -> str:
    from job_runner.config import settings
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO job_queue
                (job_type, payload, parent_job_id, root_job_id,
                 max_attempts, priority, run_at, validation_job_id)
            VALUES
                ($1, $2::jsonb, $3::uuid, $4::uuid,
                 $5, $6, COALESCE($7::timestamptz, NOW()), $8::uuid)
            RETURNING id
            """,
            job_type,
            json.dumps(payload),
            parent_job_id,
            root_job_id,
            max_attempts if max_attempts is not None else settings.default_max_attempts,
            priority,
            run_at,
            validation_job_id,
        )
        job_id = str(row["id"])
        await conn.execute("SELECT pg_notify($1, $2)", settings.listen_channel, job_id)
    return job_id


async def dequeue(worker_id: str, batch_size: int = 1) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT *
                FROM job_queue
                WHERE status = 'pending' AND run_at <= NOW()
                ORDER BY priority DESC, created_at ASC
                LIMIT $1
                FOR UPDATE SKIP LOCKED
                """,
                batch_size,
            )
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            await conn.execute(
                """
                UPDATE job_queue
                SET status = 'claimed', claimed_at = NOW(), worker_id = $1
                WHERE id = ANY($2)
                """,
                worker_id,
                ids,
            )
    return [dict(r) for r in rows]


async def mark_running(job_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_queue SET status = 'running', started_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def ack(job_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_queue SET status = 'done', completed_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def fail(job_id: str, error: str, backoff_seconds: float = 0) -> bool:
    """
    Record a job failure. Returns True if the job went dead (max attempts exceeded),
    False if it was rescheduled for retry.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT attempts, max_attempts FROM job_queue WHERE id = $1::uuid",
            job_id,
        )
        if not row:
            return False
        new_attempts = row["attempts"] + 1
        if new_attempts >= row["max_attempts"]:
            await conn.execute(
                """
                UPDATE job_queue
                SET status = 'dead', attempts = $2, last_error = $3, completed_at = NOW()
                WHERE id = $1::uuid
                """,
                job_id, new_attempts, error,
            )
            logger.warning("Job %s moved to dead-letter queue after %d attempts", job_id, new_attempts)
            return True
        else:
            await conn.execute(
                """
                UPDATE job_queue
                SET status = 'pending',
                    attempts = $2,
                    last_error = $3,
                    run_at = NOW() + ($4 || ' seconds')::interval,
                    worker_id = NULL
                WHERE id = $1::uuid
                """,
                job_id, new_attempts, error, str(int(backoff_seconds)),
            )
            return False


async def retry_dead(job_id: str) -> bool:
    """
    Reset a dead job back to pending so it will be picked up again.
    Resets attempt counter to 0. Returns True if the job was found and reset.
    """
    from job_runner.config import settings
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE job_queue
            SET status = 'pending',
                attempts = 0,
                last_error = NULL,
                run_at = NOW(),
                worker_id = NULL,
                heartbeat_at = NULL,
                completed_at = NULL
            WHERE id = $1::uuid AND status = 'dead'
            """,
            job_id,
        )
        updated = int(result.split()[-1]) > 0
        if updated:
            await conn.execute("SELECT pg_notify($1, $2)", settings.listen_channel, job_id)
            logger.info("Dead job %s reset to pending", job_id)
    return updated


async def update_heartbeat(job_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE job_queue SET heartbeat_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def reclaim_stale(stale_threshold_seconds: int) -> int:
    from job_runner.config import settings
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE job_queue
            SET status = 'pending', worker_id = NULL, heartbeat_at = NULL
            WHERE status IN ('claimed', 'running')
              AND heartbeat_at < NOW() - ($1 || ' seconds')::interval
            """,
            str(stale_threshold_seconds),
        )
        count = int(result.split()[-1])
        if count > 0:
            await conn.execute("SELECT pg_notify($1, 'reclaim')", settings.listen_channel)
            logger.info("Reclaimed %d stale jobs", count)
        return count

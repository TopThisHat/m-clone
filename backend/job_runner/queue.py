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
            INSERT INTO playbook.job_queue
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
                FROM playbook.job_queue
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
            # Write heartbeat_at immediately on claim so NULL-safe reclaim
            # can recover this job if the worker dies before the first heartbeat tick.
            await conn.execute(
                """
                UPDATE playbook.job_queue
                SET status = 'claimed',
                    claimed_at = NOW(),
                    heartbeat_at = NOW(),
                    worker_id = $1
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
            "UPDATE playbook.job_queue SET status = 'running', started_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def ack(job_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE playbook.job_queue SET status = 'done', completed_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def fail(job_id: str, error: str, backoff_seconds: float = 0) -> bool:
    """
    Record a job failure atomically. Returns True if the job went dead (max
    attempts exceeded), False if it was rescheduled for retry.

    Uses a single UPDATE with CASE WHEN to avoid a TOCTOU read-then-write:
    the attempts increment and dead/retry decision happen in one statement.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE playbook.job_queue
            SET
                attempts    = attempts + 1,
                last_error  = $2,
                status      = CASE
                                WHEN attempts + 1 >= max_attempts THEN 'dead'
                                ELSE 'pending'
                              END,
                completed_at = CASE
                                WHEN attempts + 1 >= max_attempts THEN NOW()
                                ELSE NULL
                               END,
                run_at      = CASE
                                WHEN attempts + 1 >= max_attempts THEN run_at
                                ELSE NOW() + ($3 || ' seconds')::interval
                              END,
                worker_id   = NULL
            WHERE id = $1::uuid
            RETURNING attempts, max_attempts, status
            """,
            job_id, error, str(round(backoff_seconds, 1)),
        )
        if not row:
            return False
        went_dead = row["status"] == "dead"
        if went_dead:
            logger.warning("Job %s moved to dead-letter queue after %d attempts", job_id, row["attempts"])
        return went_dead


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
            UPDATE playbook.job_queue
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
            "UPDATE playbook.job_queue SET heartbeat_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def reclaim_stale(stale_threshold_seconds: int) -> int:
    from job_runner.config import settings
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE playbook.job_queue
            SET status = 'pending', worker_id = NULL, heartbeat_at = NULL
            WHERE status IN ('claimed', 'running')
              AND (
                  heartbeat_at IS NULL
                  OR heartbeat_at < NOW() - ($1 || ' seconds')::interval
              )
            RETURNING id, job_type, worker_id AS old_worker
            """,
            str(stale_threshold_seconds),
        )
        if rows:
            await conn.execute("SELECT pg_notify($1, 'reclaim')", settings.listen_channel)
            for r in rows:
                logger.info("Reclaimed stale job %s (%s) from worker %s",
                            r["id"], r["job_type"], r["old_worker"])
        return len(rows)


async def enqueue_many(
    jobs: list[dict],
    *,
    conn,
) -> list[str]:
    """
    Insert multiple jobs in a single round-trip using unnest arrays.
    Each entry in `jobs` is a dict with keys matching enqueue() keyword args:
      job_type, payload, parent_job_id, root_job_id, max_attempts,
      priority, run_at, validation_job_id
    Returns list of job IDs in insertion order.
    Caller is responsible for managing the transaction and pg_notify.
    """
    from job_runner.config import settings
    if not jobs:
        return []

    for i, j in enumerate(jobs):
        if not j.get("job_type"):
            raise ValueError(f"enqueue_many: job[{i}] missing required field 'job_type'")
        if j.get("validation_job_id") is None and j.get("job_type") == "validation_pair":
            raise ValueError(f"enqueue_many: validation_pair job[{i}] missing 'validation_job_id'")

    job_types = [j["job_type"] for j in jobs]
    payloads = [json.dumps(j.get("payload", {})) for j in jobs]
    parent_ids = [j.get("parent_job_id") for j in jobs]
    root_ids = [j.get("root_job_id") for j in jobs]
    max_attempts_list = [j.get("max_attempts", settings.default_max_attempts) for j in jobs]
    priorities = [j.get("priority", 0) for j in jobs]
    run_ats = [j.get("run_at") for j in jobs]
    validation_job_ids = [j.get("validation_job_id") for j in jobs]

    rows = await conn.fetch(
        """
        INSERT INTO playbook.job_queue
            (job_type, payload, parent_job_id, root_job_id,
             max_attempts, priority, run_at, validation_job_id)
        SELECT
            t.job_type, t.payload, t.parent_job_id, t.root_job_id,
            t.max_attempts, t.priority, COALESCE(t.run_at, NOW()), t.validation_job_id
        FROM unnest(
            $1::text[], $2::jsonb[], $3::uuid[], $4::uuid[],
            $5::int[], $6::int[], $7::timestamptz[], $8::uuid[]
        ) AS t(job_type, payload, parent_job_id, root_job_id,
               max_attempts, priority, run_at, validation_job_id)
        RETURNING id
        """,
        job_types, payloads, parent_ids, root_ids,
        max_attempts_list, priorities, run_ats, validation_job_ids,
    )
    return [str(r["id"]) for r in rows]

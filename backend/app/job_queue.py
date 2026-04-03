"""
Shared PostgreSQL job queue operations.

Used by both job_runner (orchestrator) and worker (executor).
PostgreSQL remains the source of truth for job state; Redis Streams
are only the dispatch mechanism.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default settings — callers can override via keyword args where applicable.
# ---------------------------------------------------------------------------
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_LISTEN_CHANNEL = "job_available"


async def _get_pool():
    from app.db import get_pool
    return await get_pool()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

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
    listen_channel: str = _DEFAULT_LISTEN_CHANNEL,
) -> str:
    pool = await _get_pool()
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
            json.dumps(_sanitize_payload(payload)),
            parent_job_id,
            root_job_id,
            max_attempts if max_attempts is not None else _DEFAULT_MAX_ATTEMPTS,
            priority,
            run_at,
            validation_job_id,
        )
        job_id = str(row["id"])
        await conn.execute("SELECT pg_notify($1, $2)", listen_channel, job_id)
    return job_id


def _sanitize_payload(payload: dict) -> dict:
    """Ensure all values in a job payload are JSON-serializable.

    Converts non-serializable values (functions, classes, etc.) to their
    string representation and logs a warning so the root cause can be tracked.
    """
    clean: dict = {}
    for k, v in payload.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            clean[k] = v
        elif isinstance(v, (list, tuple)):
            clean[k] = [
                item if isinstance(item, (str, int, float, bool, type(None)))
                else str(item)
                for item in v
            ]
        elif isinstance(v, dict):
            clean[k] = _sanitize_payload(v)
        elif callable(v):
            logger.error(
                "enqueue payload key %r has callable value %r — "
                "this is a bug; converting to string",
                k, v,
            )
            clean[k] = str(v)
        else:
            clean[k] = str(v)
    return clean


async def enqueue_many(
    jobs: list[dict],
    *,
    conn,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> list[str]:
    """
    Insert multiple jobs in a single round-trip using unnest arrays.
    Each entry in `jobs` is a dict with keys matching enqueue() keyword args:
      job_type, payload, parent_job_id, root_job_id, max_attempts,
      priority, run_at, validation_job_id
    Returns list of job IDs in insertion order.
    Caller is responsible for managing the transaction and pg_notify.
    """
    if not jobs:
        return []

    for i, j in enumerate(jobs):
        if not j.get("job_type"):
            raise ValueError(f"enqueue_many: job[{i}] missing required field 'job_type'")
        if j.get("validation_job_id") is None and j.get("job_type") in ("validation_pair", "validation_cluster"):
            raise ValueError(f"enqueue_many: {j['job_type']} job[{i}] missing 'validation_job_id'")

    job_types = [j["job_type"] for j in jobs]
    payloads = [json.dumps(_sanitize_payload(j.get("payload", {}))) for j in jobs]
    parent_ids = [j.get("parent_job_id") for j in jobs]
    root_ids = [j.get("root_job_id") for j in jobs]
    max_attempts_list = [j.get("max_attempts", max_attempts) for j in jobs]
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


# ---------------------------------------------------------------------------
# Dequeue
# ---------------------------------------------------------------------------

async def dequeue(worker_id: str, batch_size: int = 1) -> list[dict[str, Any]]:
    from app.streams import JOB_TYPE_TO_STREAM
    known_types = list(JOB_TYPE_TO_STREAM.keys())
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE playbook.job_queue
            SET status = 'claimed',
                claimed_at = NOW(),
                heartbeat_at = NOW(),
                worker_id = $1
            WHERE id IN (
                SELECT id
                FROM playbook.job_queue
                WHERE status = 'pending'
                  AND run_at <= NOW()
                  AND job_type = ANY($3::text[])
                ORDER BY priority DESC, created_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            worker_id,
            batch_size,
            known_types,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

async def mark_running(job_id: str) -> bool:
    """Transition a job from claimed → running. Returns False if the job was already reclaimed."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE playbook.job_queue SET status = 'running', started_at = NOW() WHERE id = $1::uuid AND status = 'claimed'",
            job_id,
        )
    return int(result.split()[-1]) > 0


async def ack(job_id: str) -> bool:
    """Transition a job from running → done. Returns False if the job is no longer running."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE playbook.job_queue SET status = 'done', completed_at = NOW() WHERE id = $1::uuid AND status = 'running'",
            job_id,
        )
    return int(result.split()[-1]) > 0


async def fail(job_id: str, error: str, backoff_seconds: float = 0) -> bool:
    """
    Record a job failure atomically. Returns True if the job went dead (max
    attempts exceeded), False if it was rescheduled for retry.
    """
    pool = await _get_pool()
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
                                ELSE NOW() + make_interval(secs => $3::float)
                              END,
                worker_id   = NULL
            WHERE id = $1::uuid
            RETURNING attempts, max_attempts, status
            """,
            job_id, error, round(backoff_seconds, 1),
        )
        if not row:
            return False
        went_dead = row["status"] == "dead"
        if went_dead:
            logger.warning("Job %s moved to dead-letter queue after %d attempts", job_id, row["attempts"])
        return went_dead


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

async def update_job_progress(job_id: str, progress: dict[str, Any]) -> None:
    """Merge *progress* data into the job's payload JSONB column.

    This uses ``jsonb_concat`` (``||``) so existing payload keys are preserved
    and only the keys present in *progress* are upserted.  Callers typically
    pass ``items_completed``, ``items_total``, ``items_failed``, and
    ``results`` from batch data-processing workflows.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE playbook.job_queue
            SET payload = COALESCE(payload, '{}'::jsonb) || $2::jsonb
            WHERE id = $1::uuid
            """,
            job_id,
            json.dumps(_sanitize_payload(progress)),
        )


# ---------------------------------------------------------------------------
# Heartbeat & reclaim
# ---------------------------------------------------------------------------

async def update_heartbeat(job_id: str) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE playbook.job_queue SET heartbeat_at = NOW() WHERE id = $1::uuid",
            job_id,
        )


async def reclaim_stale(
    stale_threshold_seconds: int,
    listen_channel: str = _DEFAULT_LISTEN_CHANNEL,
) -> int:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH stale AS (
                SELECT id
                FROM playbook.job_queue
                WHERE status IN ('claimed', 'running')
                  AND (
                      heartbeat_at IS NULL
                      OR heartbeat_at < NOW() - make_interval(secs => $1::float)
                  )
                FOR UPDATE SKIP LOCKED
            )
            UPDATE playbook.job_queue q
            SET status = 'pending', worker_id = NULL, heartbeat_at = NULL
            FROM stale
            WHERE q.id = stale.id
            RETURNING q.id, q.job_type, q.worker_id AS old_worker
            """,
            float(stale_threshold_seconds),
        )
        if rows:
            await conn.execute("SELECT pg_notify($1, 'reclaim')", listen_channel)
            for r in rows:
                logger.info("Reclaimed stale job %s (%s) from worker %s",
                            r["id"], r["job_type"], r["old_worker"])
        return len(rows)


async def retry_dead(
    job_id: str,
    listen_channel: str = _DEFAULT_LISTEN_CHANNEL,
) -> bool:
    """
    Reset a dead job back to pending so it will be picked up again.
    Resets attempt counter to 0. Returns True if the job was found and reset.
    """
    pool = await _get_pool()
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
            await conn.execute("SELECT pg_notify($1, $2)", listen_channel, job_id)
            logger.info("Dead job %s reset to pending", job_id)
    return updated


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------

async def finalize_validation_job(validation_job_id: str, root_queue_job_id: str) -> None:
    """
    Finalize a validation_job once all its pair children have reached a terminal
    state (done or dead).

    Uses a single CTE statement to atomically count pair outcomes and apply the
    status update.  Called by both the worker (after last pair completes) and
    the dispatcher's reconcile loop (safety-net for missed finalizations).
    """
    from app.db import db_get_job_combined_report, db_recompute_scores

    pool = await _get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Row-level lock to prevent concurrent finalization
            locked = await conn.fetchrow(
                """
                SELECT id FROM playbook.validation_jobs
                WHERE id = $1::uuid AND status = 'running'
                FOR UPDATE SKIP LOCKED
                """,
                validation_job_id,
            )
            if not locked:
                logger.debug("Validation job %s already finalized or locked by another process", validation_job_id)
                return

            row = await conn.fetchrow(
                """
                WITH counts AS (
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'dead') AS dead_count,
                        COUNT(*) FILTER (WHERE status = 'done') AS done_count,
                        COUNT(*) AS total
                    FROM playbook.job_queue
                    WHERE root_job_id = $1::uuid
                ),
                upd AS (
                    UPDATE playbook.validation_jobs
                    SET
                        status = CASE
                            WHEN (SELECT dead_count = total AND total > 0 FROM counts) THEN 'failed'
                            ELSE 'done'
                        END,
                        error = CASE
                            WHEN (SELECT dead_count = total AND total > 0 FROM counts)
                                THEN 'All ' || (SELECT dead_count FROM counts)::text || ' pair job(s) exhausted retries'
                            WHEN (SELECT dead_count > 0 FROM counts)
                                THEN (SELECT dead_count FROM counts)::text
                                     || ' of ' || (SELECT total FROM counts)::text || ' pair(s) failed'
                            ELSE NULL
                        END,
                        completed_at = NOW()
                    WHERE id = $2::uuid
                      AND status = 'running'
                      AND NOT EXISTS (
                          SELECT 1 FROM playbook.job_queue
                          WHERE root_job_id = $1::uuid
                            AND status NOT IN ('done', 'dead')
                      )
                    RETURNING id
                )
                SELECT
                    (SELECT id        FROM upd)    AS updated_id,
                    (SELECT dead_count FROM counts) AS dead_count,
                    (SELECT done_count FROM counts) AS done_count,
                    (SELECT total      FROM counts) AS total
                """,
                root_queue_job_id,
                validation_job_id,
            )

    updated_id = row["updated_id"] if row else None
    dead_count = (row["dead_count"] or 0) if row else 0
    done_count = (row["done_count"] or 0) if row else 0
    total      = (row["total"]      or 0) if row else 0
    final_status = "failed" if (dead_count == total and total > 0) else "done"

    if updated_id is None:
        logger.debug("Validation job %s already finalized or still has pending children", validation_job_id)
        return

    logger.info(
        "Validation job %s finalized -> %s (%d done, %d dead of %d total)",
        validation_job_id, final_status, done_count, dead_count, total,
    )

    if final_status == "done":
        try:
            await db_recompute_scores(validation_job_id)
        except Exception as exc:
            logger.error("Validation job %s: score recompute failed: %s", validation_job_id, exc)

        try:
            # Look up campaign team_id for team-scoped KG extraction
            campaign_team_id = None
            try:
                campaign_row = await pool.fetchrow(
                    """
                    SELECT c.team_id::text
                    FROM playbook.validation_jobs vj
                    JOIN playbook.campaigns c ON c.id = vj.campaign_id
                    WHERE vj.id = $1::uuid
                    """,
                    validation_job_id,
                )
                if campaign_row:
                    campaign_team_id = campaign_row["team_id"]
            except Exception as exc:
                logger.warning("Validation job %s: campaign team_id lookup failed: %s", validation_job_id, exc)

            combined_report = await db_get_job_combined_report(validation_job_id)
            if combined_report:
                from app.streams import publish_for_extraction
                await publish_for_extraction(validation_job_id, combined_report, team_id=campaign_team_id)
                logger.info("Validation job %s: published combined report for KG extraction (team_id=%s)", validation_job_id, campaign_team_id)
        except Exception as exc:
            logger.warning("Validation job %s: failed to publish for KG extraction: %s", validation_job_id, exc)
    else:
        logger.error("Validation job %s FAILED: all %d pairs dead", validation_job_id, dead_count)

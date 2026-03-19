from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _job_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    if d.get("completed_at"):
        d["completed_at"] = d["completed_at"].isoformat()
    return d


async def db_create_job(job_id: str, query: str, webhook_url: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.research_jobs (id, query, webhook_url, status)
            VALUES ($1::uuid, $2, $3, 'queued')
            RETURNING *
            """,
            job_id,
            query,
            webhook_url,
        )
    return _job_row_to_dict(row)


async def db_update_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "result_markdown", "error", "completed_at"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return None

    set_parts = []
    values: list[Any] = []
    idx = 1
    for key, val in fields.items():
        set_parts.append(f"{key} = ${idx}")
        values.append(val)
        idx += 1

    values.append(job_id)
    sql = f"UPDATE playbook.research_jobs SET {', '.join(set_parts)} WHERE id = ${idx} RETURNING *"

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _job_row_to_dict(row) if row else None


async def db_get_job(job_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.research_jobs WHERE id = $1::uuid", job_id)
    return _job_row_to_dict(row) if row else None


# ── Dead-letter management ─────────────────────────────────────────────────────

async def db_list_dead_jobs(campaign_id: str) -> list[dict[str, Any]]:
    """Return dead queue jobs for a campaign (newest first, max 200)."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT jq.id, jq.job_type, jq.payload, jq.attempts, jq.last_error,
                   jq.created_at, jq.completed_at
            FROM playbook.job_queue jq
            WHERE jq.validation_job_id IN (
                SELECT id FROM playbook.validation_jobs WHERE campaign_id = $1::uuid
            ) AND jq.status = 'dead'
            ORDER BY jq.completed_at DESC
            LIMIT 200
            """,
            campaign_id,
        )
    return [dict(r) for r in rows]


async def db_get_queue_job_owner(job_id: str) -> dict[str, Any] | None:
    """Return campaign_id for a queue job, or None if not found."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT vj.campaign_id
            FROM playbook.job_queue jq
            JOIN playbook.validation_jobs vj ON vj.id = jq.validation_job_id
            WHERE jq.id = $1::uuid
            """,
            job_id,
        )
    return dict(row) if row else None


async def db_retry_dead_job(job_id: str) -> bool:
    """Reset a dead job back to pending so it can be retried."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            UPDATE playbook.job_queue
            SET status = 'pending', attempts = 0, last_error = NULL,
                run_at = NOW(), worker_id = NULL, heartbeat_at = NULL, completed_at = NULL
            WHERE id = $1::uuid AND status = 'dead'
            """,
            job_id,
        )
        updated = int(result.split()[-1]) > 0
        if updated:
            await conn.execute(
                "SELECT pg_notify('job_available', $1)", job_id
            )
    return updated

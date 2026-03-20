from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _campaign_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at", "last_run_at", "next_run_at", "last_completed_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


def _entity_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


def _attribute_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_create_campaign(owner_sid: str, name: str, description: str | None,
                             schedule: str | None, team_id: str | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.campaigns (owner_sid, name, description, schedule, team_id)
            VALUES ($1, $2, $3, $4, $5::uuid)
            RETURNING *
            """,
            owner_sid, name, description, schedule, team_id,
        )
    return _campaign_row_to_dict(row)


_CAMPAIGN_COUNTS_SQL = """
    SELECT c.*,
           (SELECT COUNT(*) FROM playbook.entities WHERE campaign_id = c.id)::int      AS entity_count,
           (SELECT COUNT(*) FROM playbook.attributes WHERE campaign_id = c.id)::int    AS attribute_count,
           (SELECT COUNT(*) FROM playbook.validation_results vr
            JOIN playbook.entities e ON e.id = vr.entity_id
            WHERE e.campaign_id = c.id)::int                                  AS result_count,
           (SELECT MAX(completed_at) FROM playbook.validation_jobs
            WHERE campaign_id = c.id AND status = 'done')                     AS last_completed_at
"""

async def db_list_campaigns(owner_sid: str, team_id: str | None = None) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        if team_id:
            rows = await conn.fetch(
                f"""
                {_CAMPAIGN_COUNTS_SQL}
                FROM playbook.campaigns c
                JOIN playbook.team_members tm ON tm.team_id = c.team_id
                WHERE c.team_id = $1::uuid AND tm.sid = $2
                ORDER BY c.updated_at DESC
                """,
                team_id, owner_sid,
            )
        else:
            rows = await conn.fetch(
                f"""
                {_CAMPAIGN_COUNTS_SQL}
                FROM playbook.campaigns c
                WHERE c.owner_sid = $1 AND c.team_id IS NULL
                ORDER BY c.updated_at DESC
                """,
                owner_sid,
            )
    return [_campaign_row_to_dict(r) for r in rows]


async def db_get_campaign(campaign_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.campaigns WHERE id = $1::uuid", campaign_id)
    return _campaign_row_to_dict(row) if row else None


async def db_update_campaign(campaign_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "description", "schedule", "is_active", "next_run_at"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_campaign(campaign_id)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [campaign_id]
    sql = (
        f"UPDATE playbook.campaigns SET {', '.join(set_parts)}, updated_at = NOW() "
        f"WHERE id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _campaign_row_to_dict(row) if row else None


async def db_delete_campaign(campaign_id: str, owner_sid: str) -> bool:
    """Delete campaign if user is the owner, or a member of the owning team."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.campaigns
            WHERE id = $1::uuid
              AND (
                owner_sid = $2
                OR team_id IN (
                    SELECT team_id FROM playbook.team_members WHERE sid = $2
                )
              )
            """,
            campaign_id, owner_sid,
        )
    return result.endswith("1")


async def db_clone_campaign(source_id: str, owner_sid: str) -> dict[str, Any]:
    async with _acquire() as conn:
        async with conn.transaction():
            source = await conn.fetchrow("SELECT * FROM playbook.campaigns WHERE id = $1::uuid", source_id)
            new_row = await conn.fetchrow(
                """
                INSERT INTO playbook.campaigns (owner_sid, name, description, schedule)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                owner_sid,
                (source["name"] or "") + " (copy)",
                source["description"],
                source["schedule"],
            )
            new_id = new_row["id"]
            await conn.execute(
                """
                INSERT INTO playbook.entities (id, campaign_id, label, description, gwm_id, metadata, created_at)
                SELECT gen_random_uuid(), $1::uuid, TRIM(label), description, NULLIF(TRIM(gwm_id), ''), metadata, NOW()
                FROM playbook.entities WHERE campaign_id = $2::uuid
                """,
                new_id, source_id,
            )
            await conn.execute(
                """
                INSERT INTO playbook.attributes (id, campaign_id, label, description, weight, created_at)
                SELECT gen_random_uuid(), $1::uuid, TRIM(label), description, weight, NOW()
                FROM playbook.attributes WHERE campaign_id = $2::uuid
                """,
                new_id, source_id,
            )
    return _campaign_row_to_dict(new_row)


async def db_cancel_job(job_id: str) -> bool:
    async with _acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE playbook.validation_jobs SET status='failed', error='Cancelled by user', completed_at=NOW()
                WHERE id = $1::uuid AND status IN ('queued', 'running') RETURNING id
                """,
                job_id,
            )
            if row:
                await conn.execute(
                    """
                    UPDATE playbook.job_queue SET status='dead', completed_at=NOW()
                    WHERE validation_job_id = $1::uuid AND status NOT IN ('done', 'dead')
                    """,
                    job_id,
                )
    return row is not None


# ── Scout: Campaign scheduling ─────────────────────────────────────────────────

async def db_get_due_campaigns() -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.campaigns
            WHERE is_active = TRUE
              AND schedule IS NOT NULL
              AND next_run_at <= NOW()
            ORDER BY next_run_at ASC
            """
        )
    return [_campaign_row_to_dict(r) for r in rows]


async def db_update_campaign_next_run(campaign_id: str, next_run_at: Any) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE playbook.campaigns SET last_run_at = NOW(), next_run_at = $1 WHERE id = $2::uuid",
            next_run_at, campaign_id,
        )


# ── Scout: Stats ────────────────────────────────────────────────────────────────

async def db_get_campaign_stats(owner_sid: str, team_id: str | None = None) -> dict[str, Any]:
    """Return aggregate stats across all accessible campaigns.

    Uses separate subqueries instead of a massive multi-table JOIN to avoid
    Cartesian product amplification that gets exponentially slower as data grows.
    """
    if team_id:
        campaign_filter = """
            SELECT c.id FROM playbook.campaigns c
            JOIN playbook.team_members tm ON tm.team_id = c.team_id AND tm.sid = $1
            WHERE c.team_id = $2::uuid
        """
        args: tuple = (owner_sid, team_id)
    else:
        campaign_filter = """
            SELECT c.id FROM playbook.campaigns c
            WHERE c.owner_sid = $1 AND c.team_id IS NULL
        """
        args = (owner_sid,)

    async with _acquire() as conn:
        row = await conn.fetchrow(
            f"""
            WITH cids AS ({campaign_filter})
            SELECT
                (SELECT COUNT(*) FROM cids)::int AS campaigns,
                (SELECT COUNT(*) FROM playbook.entities
                 WHERE campaign_id IN (SELECT id FROM cids))::int AS entities,
                (SELECT COUNT(*) FROM playbook.validation_results vr
                 JOIN playbook.entities e ON e.id = vr.entity_id
                 WHERE e.campaign_id IN (SELECT id FROM cids))::int AS results,
                (SELECT COUNT(*) FROM playbook.validation_jobs
                 WHERE campaign_id IN (SELECT id FROM cids)
                   AND created_at > NOW() - INTERVAL '7 days')::int AS jobs_last_7_days,
                (SELECT COUNT(DISTINCT k.gwm_id || ':' || k.attribute_label)
                 FROM playbook.entity_attribute_knowledge k
                 JOIN playbook.entities e ON e.gwm_id = k.gwm_id
                 WHERE e.campaign_id IN (SELECT id FROM cids)
                   AND e.gwm_id IS NOT NULL)::int AS knowledge_entries
            """,
            *args,
        )
    return dict(row) if row else {"campaigns": 0, "entities": 0, "results": 0, "jobs_last_7_days": 0, "knowledge_entries": 0}


# ── Scout: Cross-campaign import ───────────────────────────────────────────────

async def db_import_entities(target_campaign_id: str, source_campaign_id: str) -> list[dict[str, Any]]:
    """
    Copy entities from source campaign to target campaign, skipping duplicates.
    Pre-filters gwm_id conflicts, then uses ON CONFLICT for label uniqueness.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $2::uuid, TRIM(label), description, NULLIF(TRIM(gwm_id), ''), metadata
            FROM playbook.entities src
            WHERE src.campaign_id = $1::uuid
              AND (src.gwm_id IS NULL OR NOT EXISTS (
                  SELECT 1 FROM playbook.entities tgt
                  WHERE tgt.campaign_id = $2::uuid
                    AND LOWER(TRIM(tgt.gwm_id)) = LOWER(TRIM(src.gwm_id))
              ))
            ON CONFLICT (campaign_id, (LOWER(TRIM(label)))) DO NOTHING
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    return [_entity_row_to_dict(r) for r in rows]


async def db_import_attributes(target_campaign_id: str, source_campaign_id: str) -> list[dict[str, Any]]:
    """
    Copy attributes from source campaign to target campaign, skipping label duplicates.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO playbook.attributes (campaign_id, label, description, weight)
            SELECT $2::uuid, TRIM(label), description, weight
            FROM playbook.attributes
            WHERE campaign_id = $1::uuid
            ON CONFLICT (campaign_id, (LOWER(TRIM(label)))) DO NOTHING
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    return [_attribute_row_to_dict(r) for r in rows]


# ── CSV Export ────────────────────────────────────────────────────────────────

async def db_export_campaign_results(campaign_id: str) -> list[dict[str, Any]]:
    """Return the latest result per entity x attribute for a campaign, for CSV export."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (r.entity_id, r.attribute_id)
                   e.label AS entity_label,
                   e.gwm_id,
                   a.label AS attribute_label,
                   r.present,
                   r.confidence,
                   r.evidence,
                   es.total_score,
                   es.attributes_present,
                   es.attributes_checked,
                   r.created_at
            FROM playbook.validation_results r
            JOIN playbook.entities e ON e.id = r.entity_id
            JOIN playbook.attributes a ON a.id = r.attribute_id
            JOIN playbook.validation_jobs vj ON vj.id = r.job_id
            LEFT JOIN playbook.entity_scores es ON es.entity_id = r.entity_id AND es.campaign_id = $1::uuid
            WHERE vj.campaign_id = $1::uuid
            ORDER BY r.entity_id, r.attribute_id, r.created_at DESC
            """,
            campaign_id,
        )
    return [dict(r) for r in rows]

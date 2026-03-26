from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from fastapi import HTTPException

from ._pool import _acquire
from app.models.campaign import CampaignStatus, VALID_STATUS_TRANSITIONS

logger = logging.getLogger(__name__)


def _campaign_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id", "team_id", "program_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at", "last_run_at", "next_run_at", "last_completed_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    # Convert Decimal avg_scout_score to float for JSON serialisation
    if "avg_scout_score" in d and d["avg_scout_score"] is not None:
        d["avg_scout_score"] = float(d["avg_scout_score"])
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
            WHERE campaign_id = c.id AND status = 'done')                     AS last_completed_at,
           (SELECT ROUND(AVG(es.total_score)::numeric, 2)
            FROM playbook.entity_scores es
            WHERE es.campaign_id = c.id)                                      AS avg_scout_score,
           pc.program_id,
           prg.name                                                           AS program_name
"""

_CAMPAIGN_JOINS_SQL = """
    LEFT JOIN playbook.program_campaigns pc ON pc.campaign_id = c.id
    LEFT JOIN playbook.programs prg ON prg.id = pc.program_id
"""

async def db_list_campaigns(owner_sid: str, team_id: str | None = None) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        if team_id:
            rows = await conn.fetch(
                f"""
                {_CAMPAIGN_COUNTS_SQL}
                FROM playbook.campaigns c
                {_CAMPAIGN_JOINS_SQL}
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
                {_CAMPAIGN_JOINS_SQL}
                WHERE c.owner_sid = $1 AND c.team_id IS NULL
                ORDER BY c.updated_at DESC
                """,
                owner_sid,
            )
    return [_campaign_row_to_dict(r) for r in rows]


async def db_get_campaign(campaign_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            f"""
            {_CAMPAIGN_COUNTS_SQL}
            FROM playbook.campaigns c
            {_CAMPAIGN_JOINS_SQL}
            WHERE c.id = $1::uuid
            """,
            campaign_id,
        )
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
                INSERT INTO playbook.campaigns (owner_sid, name, description, schedule, team_id)
                VALUES ($1, $2, $3, $4, $5::uuid)
                RETURNING *
                """,
                owner_sid,
                (source["name"] or "") + " (copy)",
                source["description"],
                source["schedule"],
                str(source["team_id"]) if source["team_id"] else None,
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

async def db_import_entities(target_campaign_id: str, source_campaign_id: str) -> dict[str, Any]:
    """Copy entities from source campaign to target campaign, skipping duplicates.

    Returns structured result: ``{"inserted": [...], "skipped": int, "total_requested": int}``.

    CTE deduplicates on label, ON CONFLICT DO NOTHING catches gwm_id and
    label collisions with rows already in the target campaign.
    """
    async with _acquire() as conn:
        total_requested = await conn.fetchval(
            "SELECT COUNT(*) FROM playbook.entities WHERE campaign_id = $1::uuid AND TRIM(COALESCE(label, '')) != ''",
            source_campaign_id,
        )
        rows = await conn.fetch(
            """
            WITH source AS (
                SELECT
                    TRIM(label) AS label,
                    description,
                    NULLIF(TRIM(gwm_id), '') AS gwm_id,
                    metadata
                FROM playbook.entities
                WHERE campaign_id = $1::uuid
                  AND TRIM(COALESCE(label, '')) != ''
            )
            INSERT INTO playbook.entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $2::uuid, s.label, s.description, s.gwm_id, s.metadata
            FROM source s
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    inserted = [_entity_row_to_dict(r) for r in rows]
    return {
        "inserted": inserted,
        "skipped": total_requested - len(inserted),
        "total_requested": total_requested,
    }


async def db_import_attributes(target_campaign_id: str, source_campaign_id: str) -> dict[str, Any]:
    """Copy attributes from source campaign to target campaign, skipping label duplicates.

    Returns structured result: ``{"inserted": [...], "skipped": int, "total_requested": int}``.

    Deduplication relies on ON CONFLICT DO NOTHING against the target
    campaign's unique indexes (label). No CTE-level dedup is performed.
    """
    async with _acquire() as conn:
        total_requested = await conn.fetchval(
            "SELECT COUNT(*) FROM playbook.attributes WHERE campaign_id = $1::uuid AND TRIM(COALESCE(label, '')) != ''",
            source_campaign_id,
        )
        rows = await conn.fetch(
            """
            WITH source AS (
                SELECT
                    TRIM(label) AS label,
                    description,
                    weight
                FROM playbook.attributes
                WHERE campaign_id = $1::uuid
                  AND TRIM(COALESCE(label, '')) != ''
            )
            INSERT INTO playbook.attributes (campaign_id, label, description, weight)
            SELECT $2::uuid, s.label, s.description, s.weight
            FROM source s
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    inserted = [_attribute_row_to_dict(r) for r in rows]
    return {
        "inserted": inserted,
        "skipped": total_requested - len(inserted),
        "total_requested": total_requested,
    }


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


# ── Campaign Lifecycle ────────────────────────────────────────────────────────

async def db_transition_campaign_status(
    campaign_id: str,
    new_status: CampaignStatus,
    user_sid: str,
) -> dict[str, Any]:
    """Transition a campaign's status with validation and audit logging.

    The access check, state read, and write are all performed inside a single
    serialisable transaction with a FOR UPDATE lock to eliminate the TOCTOU gap
    between the ownership check and the status update.

    Raises:
        HTTPException(403): caller does not own or belong to this campaign
        HTTPException(404): campaign not found
        HTTPException(400): invalid transition
    """
    async with _acquire() as conn:
        async with conn.transaction():
            # Lock the row to prevent concurrent transitions and to read the
            # authoritative ownership/status atomically.
            row = await conn.fetchrow(
                """
                SELECT id, status, owner_sid, team_id
                FROM playbook.campaigns
                WHERE id = $1::uuid
                FOR UPDATE
                """,
                campaign_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Campaign not found")

            # Access check inside the lock — eliminates TOCTOU race.
            team_id = row["team_id"]
            if team_id is not None:
                is_member = await conn.fetchval(
                    "SELECT 1 FROM playbook.team_members WHERE team_id = $1 AND sid = $2",
                    team_id, user_sid,
                )
                if not is_member:
                    raise HTTPException(status_code=403, detail="Forbidden")
            elif str(row["owner_sid"]) != user_sid:
                raise HTTPException(status_code=403, detail="Forbidden")

            old_status_str: str = row["status"]
            try:
                old_status = CampaignStatus(old_status_str)
            except ValueError:
                # Existing row has a status that predates the enum; treat as draft
                old_status = CampaignStatus.draft

            allowed = VALID_STATUS_TRANSITIONS.get(old_status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid status transition: {old_status.value} -> {new_status.value}. "
                        f"Allowed transitions from '{old_status.value}': "
                        f"{sorted(s.value for s in allowed) if allowed else 'none'}"
                    ),
                )

            # Update the campaign status
            await conn.execute(
                """
                UPDATE playbook.campaigns
                SET status = $1, updated_at = NOW()
                WHERE id = $2::uuid
                """,
                new_status.value, campaign_id,
            )

            # Write audit log
            await conn.execute(
                """
                INSERT INTO playbook.campaign_status_audit
                    (campaign_id, old_status, new_status, changed_by_sid)
                VALUES ($1::uuid, $2, $3, $4)
                """,
                campaign_id, old_status.value, new_status.value, user_sid,
            )

            # Re-fetch with computed counts so the response matches CampaignOut
            updated_row = await conn.fetchrow(
                f"""
                {_CAMPAIGN_COUNTS_SQL}
                FROM playbook.campaigns c
                {_CAMPAIGN_JOINS_SQL}
                WHERE c.id = $1::uuid
                """,
                campaign_id,
            )

    logger.info(
        "Campaign %s status: %s -> %s (by %s)",
        campaign_id, old_status.value, new_status.value, user_sid,
    )
    return _campaign_row_to_dict(updated_row)


async def db_get_campaign_status_audit(campaign_id: str) -> list[dict[str, Any]]:
    """Return the status audit trail for a campaign, newest first."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, campaign_id, old_status, new_status, changed_by_sid, changed_at
            FROM playbook.campaign_status_audit
            WHERE campaign_id = $1::uuid
            ORDER BY changed_at DESC
            """,
            campaign_id,
        )
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["campaign_id"] = str(d["campaign_id"])
        if d.get("changed_at"):
            d["changed_at"] = d["changed_at"].isoformat()
        result.append(d)
    return result

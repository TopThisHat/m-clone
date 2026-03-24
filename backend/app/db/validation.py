from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from ._pool import _acquire

logger = logging.getLogger(__name__)


def _job_vrow_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "started_at", "completed_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    # Convert UUID arrays to list of strings
    for arr_field in ("entity_filter", "attribute_filter"):
        if arr_field in d and d[arr_field] is not None:
            d[arr_field] = [str(u) for u in d[arr_field]]
    return d


def _result_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "job_id", "entity_id", "attribute_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


def _score_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("entity_id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
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


async def db_create_validation_job(campaign_id: str, triggered_by: str,
                                   triggered_sid: str | None = None,
                                   entity_filter: list[str] | None = None,
                                   attribute_filter: list[str] | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.validation_jobs
                (campaign_id, triggered_by, triggered_sid, entity_filter, attribute_filter)
            VALUES ($1::uuid, $2, $3, $4::uuid[], $5::uuid[])
            RETURNING *
            """,
            campaign_id, triggered_by, triggered_sid,
            entity_filter or None, attribute_filter or None,
        )
    return _job_vrow_to_dict(row)


async def db_create_and_enqueue_validation_job(
    campaign_id: str,
    triggered_by: str,
    triggered_sid: str | None = None,
    entity_filter: list[str] | None = None,
    attribute_filter: list[str] | None = None,
) -> dict[str, Any]:
    """
    Atomically create a validation_job AND insert a job_queue entry in one
    transaction. If either operation fails nothing is committed, preventing
    orphaned validation_jobs that no worker will ever process.
    """
    import json as _json
    async with _acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.validation_jobs
                    (campaign_id, triggered_by, triggered_sid, entity_filter, attribute_filter)
                VALUES ($1::uuid, $2, $3, $4::uuid[], $5::uuid[])
                RETURNING *
                """,
                campaign_id, triggered_by, triggered_sid,
                entity_filter or None, attribute_filter or None,
            )
            job_id = str(row["id"])
            await conn.execute(
                """
                INSERT INTO playbook.job_queue (job_type, payload, validation_job_id)
                VALUES ('validation_campaign', $1::jsonb, $2::uuid)
                """,
                _json.dumps({"validation_job_id": job_id}),
                job_id,
            )
            await conn.execute("SELECT pg_notify('job_available', $1)", job_id)
    return _job_vrow_to_dict(row)


async def db_list_validation_jobs(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM playbook.validation_jobs WHERE campaign_id = $1::uuid ORDER BY created_at DESC",
            campaign_id,
        )
    return [_job_vrow_to_dict(r) for r in rows]


async def db_get_validation_job(job_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.validation_jobs WHERE id = $1::uuid", job_id)
    return _job_vrow_to_dict(row) if row else None


async def db_update_validation_job(job_id: str, **kwargs: Any) -> dict[str, Any] | None:
    allowed = {"status", "total_pairs", "completed_pairs", "error", "started_at", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return await db_get_validation_job(job_id)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [job_id]
    sql = f"UPDATE playbook.validation_jobs SET {', '.join(set_parts)} WHERE id = ${len(values)}::uuid RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _job_vrow_to_dict(row) if row else None


async def db_get_job_details(job_id: str) -> tuple[list[dict], list[dict]]:
    """Return (entities, attributes) for a job, respecting entity/attribute filters."""
    async with _acquire() as conn:
        job = await conn.fetchrow("SELECT * FROM playbook.validation_jobs WHERE id = $1::uuid", job_id)
        if not job:
            return [], []
        campaign_id = job["campaign_id"]
        entity_filter = job["entity_filter"]
        attribute_filter = job["attribute_filter"]

        if entity_filter:
            entity_rows = await conn.fetch(
                "SELECT * FROM playbook.entities WHERE id = ANY($1::uuid[]) AND campaign_id = $2::uuid",
                entity_filter, campaign_id,
            )
        else:
            entity_rows = await conn.fetch(
                "SELECT * FROM playbook.entities WHERE campaign_id = $1::uuid",
                campaign_id,
            )

        if attribute_filter:
            attr_rows = await conn.fetch(
                "SELECT * FROM playbook.attributes WHERE id = ANY($1::uuid[]) AND campaign_id = $2::uuid",
                attribute_filter, campaign_id,
            )
        else:
            attr_rows = await conn.fetch(
                "SELECT * FROM playbook.attributes WHERE campaign_id = $1::uuid",
                campaign_id,
            )

    entities = [_entity_row_to_dict(r) for r in entity_rows]
    attributes = [_attribute_row_to_dict(r) for r in attr_rows]
    return entities, attributes


async def db_increment_job_progress(job_id: str) -> None:
    """
    Set completed_pairs to the actual count of results for this job.
    Using COUNT instead of += 1 makes this idempotent: if a pair job is
    reclaimed and re-runs after already inserting its result (ON CONFLICT DO
    UPDATE), the count stays correct and never exceeds total_pairs.
    """
    async with _acquire() as conn:
        await conn.execute(
            """
            UPDATE playbook.validation_jobs
            SET completed_pairs = (
                SELECT COUNT(*) FROM playbook.validation_results WHERE job_id = $1::uuid
            )
            WHERE id = $1::uuid
            """,
            job_id,
        )


# ── Scout: Validation Results ──────────────────────────────────────────────────

async def db_insert_result(job_id: str, entity_id: str, attribute_id: str,
                           result: dict[str, Any], report_md: str,
                           update_knowledge: bool = True) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.validation_results
                (job_id, entity_id, attribute_id, present, confidence, evidence, report_md)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
            ON CONFLICT (job_id, entity_id, attribute_id) DO UPDATE SET
                present = EXCLUDED.present,
                confidence = EXCLUDED.confidence,
                evidence = EXCLUDED.evidence,
                report_md = EXCLUDED.report_md
            """,
            job_id, entity_id, attribute_id,
            result.get("present", False),
            result.get("confidence"),
            result.get("evidence"),
            report_md,
        )
        if update_knowledge:
            # Check if entity has gwm_id before attempting knowledge upsert
            has_gwm_id = await conn.fetchval(
                "SELECT gwm_id IS NOT NULL FROM playbook.entities WHERE id = $1::uuid",
                entity_id,
            )
            if not has_gwm_id:
                logger.warning(
                    "db_insert_result: skipping knowledge cache upsert for entity_id=%s — NULL gwm_id",
                    entity_id,
                )
            else:
                # Upsert knowledge cache with team_id scoping.
                # Uses eak_gwm_attr_team_unique index for conflict detection.
                await conn.execute(
                    """
                    INSERT INTO playbook.entity_attribute_knowledge
                        (gwm_id, attribute_label, present, confidence, evidence,
                         source_job_id, source_campaign_id, source_campaign_name,
                         entity_label, team_id, research_source, research_session_count)
                    SELECT
                        e.gwm_id,
                        a.label,
                        $4,
                        $5,
                        $6,
                        $1::uuid,
                        j.campaign_id,
                        c.name,
                        e.label,
                        c.team_id,
                        'campaign',
                        1
                    FROM playbook.entities e
                    JOIN playbook.attributes a ON a.id = $3::uuid
                    JOIN playbook.validation_jobs j ON j.id = $1::uuid
                    JOIN playbook.campaigns c ON c.id = j.campaign_id
                    WHERE e.id = $2::uuid AND e.gwm_id IS NOT NULL
                    ON CONFLICT (gwm_id, attribute_label,
                                 COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid))
                    DO UPDATE SET
                        present = EXCLUDED.present,
                        confidence = EXCLUDED.confidence,
                        evidence = EXCLUDED.evidence,
                        source_job_id = EXCLUDED.source_job_id,
                        source_campaign_id = EXCLUDED.source_campaign_id,
                        source_campaign_name = EXCLUDED.source_campaign_name,
                        entity_label = EXCLUDED.entity_label,
                        research_session_count = playbook.entity_attribute_knowledge.research_session_count + 1,
                        last_updated = NOW()
                    """,
                    job_id, entity_id, attribute_id,
                    result.get("present", False),
                    result.get("confidence"),
                    result.get("evidence"),
                )


async def db_list_results(job_id: str, entity_id: str | None = None,
                          attribute_id: str | None = None,
                          present: bool | None = None,
                          limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conditions = ["r.job_id = $1::uuid"]
    values: list[Any] = [job_id]
    idx = 2
    if entity_id:
        conditions.append(f"r.entity_id = ${idx}::uuid")
        values.append(entity_id)
        idx += 1
    if attribute_id:
        conditions.append(f"r.attribute_id = ${idx}::uuid")
        values.append(attribute_id)
        idx += 1
    if present is not None:
        conditions.append(f"r.present = ${idx}")
        values.append(present)
        idx += 1
    values.extend([limit, offset])
    sql = (
        f"SELECT r.*, e.label AS entity_label, a.label AS attribute_label "
        f"FROM playbook.validation_results r "
        f"JOIN playbook.entities e ON r.entity_id = e.id "
        f"JOIN playbook.attributes a ON r.attribute_id = a.id "
        f"WHERE {' AND '.join(conditions)} "
        f"ORDER BY r.created_at DESC LIMIT ${idx} OFFSET ${idx+1}"
    )
    async with _acquire() as conn:
        rows = await conn.fetch(sql, *values)
    return [_result_row_to_dict(r) for r in rows]


# ── Scout: Entity Scores ───────────────────────────────────────────────────────

async def db_get_scores(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT es.*, e.label AS entity_label, e.gwm_id
            FROM playbook.entity_scores es
            JOIN playbook.entities e ON es.entity_id = e.id
            WHERE es.campaign_id = $1::uuid
            ORDER BY es.total_score DESC
            """,
            campaign_id,
        )
    return [_score_row_to_dict(r) for r in rows]


async def db_recompute_scores(job_id: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.entity_scores
                (entity_id, campaign_id, total_score, attributes_present, attributes_checked, last_updated)
            SELECT
                r.entity_id,
                j.campaign_id,
                SUM(CASE WHEN r.present THEN a.weight ELSE 0 END),
                COUNT(CASE WHEN r.present THEN 1 END),
                COUNT(*),
                NOW()
            FROM playbook.validation_results r
            JOIN playbook.validation_jobs j ON r.job_id = j.id
            JOIN playbook.attributes a ON r.attribute_id = a.id
            WHERE r.job_id = $1::uuid
            GROUP BY r.entity_id, j.campaign_id
            ON CONFLICT (entity_id, campaign_id) DO UPDATE SET
                total_score = EXCLUDED.total_score,
                attributes_present = EXCLUDED.attributes_present,
                attributes_checked = EXCLUDED.attributes_checked,
                last_updated = NOW()
            """,
            job_id,
        )


async def db_get_live_scores(job_id: str) -> list[dict[str, Any]]:
    """Compute scores on-the-fly from validation_results for an in-progress job."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                r.entity_id,
                j.campaign_id,
                e.label AS entity_label,
                e.gwm_id,
                SUM(CASE WHEN r.present THEN a.weight ELSE 0 END) AS total_score,
                COUNT(CASE WHEN r.present THEN 1 END)::int AS attributes_present,
                COUNT(*)::int AS attributes_checked,
                MAX(r.created_at) AS last_updated
            FROM playbook.validation_results r
            JOIN playbook.validation_jobs j ON r.job_id = j.id
            JOIN playbook.attributes a ON r.attribute_id = a.id
            JOIN playbook.entities e ON r.entity_id = e.id
            WHERE r.job_id = $1::uuid
            GROUP BY r.entity_id, j.campaign_id, e.label, e.gwm_id
            ORDER BY SUM(CASE WHEN r.present THEN a.weight ELSE 0 END) DESC
            """,
            job_id,
        )
    return [_score_row_to_dict(r) for r in rows]


async def db_get_entity_cross_campaign(gwm_id: str) -> list[dict[str, Any]]:
    """Get validation results for an entity (by gwm_id) across all campaigns."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                r.present, r.confidence, r.evidence, r.created_at,
                a.label AS attribute_label,
                c.name AS campaign_name, c.id AS campaign_id,
                es.total_score
            FROM playbook.validation_results r
            JOIN playbook.entities e ON r.entity_id = e.id
            JOIN playbook.attributes a ON r.attribute_id = a.id
            JOIN playbook.campaigns c ON e.campaign_id = c.id
            LEFT JOIN playbook.entity_scores es ON es.entity_id = e.id AND es.campaign_id = c.id
            WHERE e.gwm_id = $1
            ORDER BY c.name, a.label
            """,
            gwm_id,
        )
    result = []
    for row in rows:
        d = dict(row)
        for f in ("campaign_id",):
            if d.get(f):
                d[f] = str(d[f])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result


async def db_get_job_combined_report(job_id: str) -> str:
    """Return all report markdowns for a validation job concatenated together."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.label AS entity_label, a.label AS attribute_label, r.report_md
            FROM playbook.validation_results r
            JOIN playbook.entities e ON r.entity_id = e.id
            JOIN playbook.attributes a ON r.attribute_id = a.id
            WHERE r.job_id = $1::uuid AND r.report_md IS NOT NULL AND r.report_md != ''
            """,
            job_id,
        )
    parts = [
        f"## {row['entity_label']} — {row['attribute_label']}\n\n{row['report_md']}"
        for row in rows
    ]
    return "\n\n---\n\n".join(parts)


# ── Trends & Comparison ──────────────────────────────────────────────────────

async def db_get_score_trends(campaign_id: str, entity_id: str | None = None) -> list[dict[str, Any]]:
    """Per-entity score at each completed job over time."""
    entity_filter = ""
    args: list[Any] = [campaign_id]
    if entity_id:
        entity_filter = " AND r.entity_id = $2::uuid"
        args.append(entity_id)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT vj.id AS job_id,
                   vj.completed_at,
                   e.id AS entity_id,
                   e.label AS entity_label,
                   CASE WHEN COUNT(*) > 0
                        THEN ROUND(SUM(CASE WHEN r.present THEN a.weight ELSE 0 END)::numeric
                             / NULLIF(SUM(a.weight), 0)::numeric, 4)
                        ELSE 0 END AS score
            FROM playbook.validation_jobs vj
            JOIN playbook.validation_results r ON r.job_id = vj.id
            JOIN playbook.entities e ON e.id = r.entity_id
            JOIN playbook.attributes a ON a.id = r.attribute_id
            WHERE vj.campaign_id = $1::uuid AND vj.status = 'done'{entity_filter}
            GROUP BY vj.id, vj.completed_at, e.id, e.label
            ORDER BY vj.completed_at ASC, e.label ASC
            """,
            *args,
        )
    result = []
    for r in rows:
        d = dict(r)
        for f in ("job_id", "entity_id"):
            if d.get(f):
                d[f] = str(d[f])
        if d.get("completed_at"):
            d["completed_at"] = d["completed_at"].isoformat()
        if d.get("score") is not None:
            d["score"] = float(d["score"])
        result.append(d)
    return result


async def db_compare_jobs(job_a: str, job_b: str) -> list[dict[str, Any]]:
    """FULL OUTER JOIN two job results to find added/removed/changed pairs."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(a.entity_id, b.entity_id) AS entity_id,
                   COALESCE(ea.label, eb.label) AS entity_label,
                   COALESCE(a.attribute_id, b.attribute_id) AS attribute_id,
                   COALESCE(aa.label, ab.label) AS attribute_label,
                   a.present AS present_a,
                   b.present AS present_b,
                   a.confidence AS confidence_a,
                   b.confidence AS confidence_b,
                   CASE
                       WHEN a.entity_id IS NULL THEN 'added'
                       WHEN b.entity_id IS NULL THEN 'removed'
                       WHEN a.present != b.present THEN 'changed'
                       ELSE 'unchanged'
                   END AS diff_status
            FROM playbook.validation_results a
            FULL OUTER JOIN playbook.validation_results b
                ON a.entity_id = b.entity_id AND a.attribute_id = b.attribute_id AND b.job_id = $2::uuid
            LEFT JOIN playbook.entities ea ON ea.id = a.entity_id
            LEFT JOIN playbook.entities eb ON eb.id = b.entity_id
            LEFT JOIN playbook.attributes aa ON aa.id = a.attribute_id
            LEFT JOIN playbook.attributes ab ON ab.id = b.attribute_id
            WHERE (a.job_id = $1::uuid OR a.job_id IS NULL)
              AND (b.job_id = $2::uuid OR b.job_id IS NULL)
            ORDER BY entity_label, attribute_label
            """,
            job_a, job_b,
        )
    result = []
    for r in rows:
        d = dict(r)
        for f in ("entity_id", "attribute_id"):
            if d.get(f):
                d[f] = str(d[f])
        if d.get("confidence_a") is not None:
            d["confidence_a"] = float(d["confidence_a"])
        if d.get("confidence_b") is not None:
            d["confidence_b"] = float(d["confidence_b"])
        result.append(d)
    return result


# ── Batch knowledge cache lookup ───────────────────────────────────────────────

async def db_insert_results_batch(job_id: str, hits: list[dict[str, Any]]) -> None:
    """Insert validation results for cache hits in a single round-trip using unnest."""
    if not hits:
        return
    entity_ids = [hit["entity_id"] for hit in hits]
    attribute_ids = [hit["attribute_id"] for hit in hits]
    presents = [hit["present"] for hit in hits]
    confidences = [hit.get("confidence") for hit in hits]
    evidences = [hit.get("evidence") for hit in hits]
    async with _acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO playbook.validation_results
                    (job_id, entity_id, attribute_id, present, confidence, evidence, report_md)
                SELECT $1::uuid, unnest($2::uuid[]), unnest($3::uuid[]),
                       unnest($4::bool[]), unnest($5::float[]), unnest($6::text[]), ''
                ON CONFLICT (job_id, entity_id, attribute_id) DO UPDATE SET
                    present    = EXCLUDED.present,
                    confidence = EXCLUDED.confidence,
                    evidence   = EXCLUDED.evidence
                """,
                job_id, entity_ids, attribute_ids, presents, confidences, evidences,
            )
            await conn.execute(
                """
                UPDATE playbook.validation_jobs
                SET completed_pairs = (
                    SELECT COUNT(*) FROM playbook.validation_results WHERE job_id = $1::uuid
                )
                WHERE id = $1::uuid
                """,
                job_id,
            )

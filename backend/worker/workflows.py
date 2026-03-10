"""
DBOS durable workflows for Scout validation jobs.
Each entity × attribute pair is an independently checkpointed, retryable step.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from dbos import DBOS

from .research import run_research
from .llm import determine_presence

logger = logging.getLogger(__name__)


@DBOS.step()
async def get_job_pairs_step(job_id: str) -> list[tuple[str, str]]:
    from app.db import db_get_job_details, db_update_validation_job
    entities, attributes = await db_get_job_details(job_id)
    pairs = [(str(e["id"]), str(a["id"])) for e in entities for a in attributes]
    await db_update_validation_job(
        job_id,
        status="running",
        total_pairs=len(pairs),
        started_at=datetime.now(timezone.utc),
    )
    logger.info("Job %s: %d pairs to validate", job_id, len(pairs))
    return pairs


@DBOS.step(retries_allowed=True, max_attempts=3, backoff_rate=2.0)
async def validate_pair_step(job_id: str, entity_id: str, attribute_id: str) -> None:
    from app.db import (
        db_get_entity,
        db_get_attribute,
        db_insert_result,
        db_increment_job_progress,
        db_lookup_knowledge,
    )
    entity = await db_get_entity(entity_id)
    attribute = await db_get_attribute(attribute_id)
    if not entity or not attribute:
        logger.warning("Job %s: entity %s or attribute %s not found, skipping", job_id, entity_id, attribute_id)
        await db_increment_job_progress(job_id)
        return

    # Cache check: if entity has gwm_id, look up the global knowledge store
    gwm_id = entity.get("gwm_id")
    if gwm_id:
        cached = await db_lookup_knowledge(gwm_id, attribute["label"])
        if cached:
            logger.info(
                "Job %s: cache hit for gwm_id=%s × %s (from %s)",
                job_id, gwm_id, attribute["label"], cached.get("source_campaign_name"),
            )
            result = {
                "present": cached["present"],
                "confidence": cached.get("confidence"),
                "evidence": cached.get("evidence"),
            }
            # update_knowledge=False to preserve original source in knowledge table
            await db_insert_result(job_id, entity_id, attribute_id, result, "", update_knowledge=False)
            await db_increment_job_progress(job_id)
            return

    query = f"{entity['label']}: {attribute['label']}. {attribute.get('description') or ''}"
    report_md = await run_research(query)
    result = await determine_presence(entity, attribute, report_md)
    await db_insert_result(job_id, entity_id, attribute_id, result, report_md)
    await db_increment_job_progress(job_id)
    logger.debug(
        "Job %s: %s × %s → present=%s confidence=%.2f",
        job_id, entity.get("label"), attribute.get("label"),
        result.get("present"), result.get("confidence", 0),
    )


@DBOS.step()
async def finalize_job_step(job_id: str) -> None:
    from app.db import db_recompute_scores, db_update_validation_job, db_get_job_combined_report
    await db_recompute_scores(job_id)
    await db_update_validation_job(
        job_id,
        status="done",
        completed_at=datetime.now(timezone.utc),
    )
    logger.info("Job %s: finalized", job_id)

    try:
        from app.queue import publish_for_extraction
        combined_report = await db_get_job_combined_report(job_id)
        if combined_report:
            await publish_for_extraction(job_id, combined_report)
            logger.info("Job %s: published combined report for KG extraction", job_id)
    except Exception as exc:
        logger.warning("Job %s: failed to publish for KG extraction: %s", job_id, exc)


@DBOS.workflow()
async def validate_job_workflow(job_id: str) -> None:
    """
    Orchestrates validation of all entity × attribute pairs for a job.
    Each pair is independently checkpointed and retried by DBOS.
    """
    try:
        pairs = await get_job_pairs_step(job_id)
        # Fan-out: each pair is independently checkpointed and retried by DBOS
        await asyncio.gather(*[
            validate_pair_step(job_id, entity_id, attr_id)
            for entity_id, attr_id in pairs
        ])
        await finalize_job_step(job_id)
    except Exception as exc:
        from app.db import db_update_validation_job
        logger.error("Job %s failed: %s", job_id, exc)
        await db_update_validation_job(job_id, status="failed", error=str(exc))
        raise

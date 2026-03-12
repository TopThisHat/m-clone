"""
Validation workflows: campaign fan-out + per-pair research/scoring.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing backend app/worker modules without code duplication
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))

from job_runner.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)


@registry.register("validation_campaign")
class ValidationCampaignWorkflow(BaseWorkflow):
    """
    Fan-out: fetches entity × attribute pairs and enqueues one validation_pair
    job per pair.

    payload: {"validation_job_id": str}
    """

    async def run(self) -> None:
        from app.db import db_get_job_details, db_update_validation_job
        from job_runner.queue import enqueue

        job_id = self.payload["validation_job_id"]

        entities, attributes = await db_get_job_details(job_id)
        pairs = [(str(e["id"]), str(a["id"])) for e in entities for a in attributes]

        await db_update_validation_job(
            job_id,
            status="running",
            total_pairs=len(pairs),
            started_at=datetime.now(timezone.utc),
        )
        logger.info("ValidationCampaign job=%s: fanning out %d pairs", job_id, len(pairs))

        campaign_id = str(entities[0]["campaign_id"]) if entities else None

        for entity_id, attribute_id in pairs:
            await enqueue(
                "validation_pair",
                payload={
                    "validation_job_id": job_id,
                    "campaign_id": campaign_id,
                    "entity_id": entity_id,
                    "attribute_id": attribute_id,
                },
                parent_job_id=self.job_id,
                root_job_id=self.job_id,
                validation_job_id=job_id,
                max_attempts=3,
            )


async def finalize_validation_job(validation_job_id: str, root_queue_job_id: str) -> None:
    """
    Finalize a validation_job once all its pair children have reached a terminal
    state (done or dead). Determines final status:
      - 'done'   if all pairs completed successfully
      - 'failed' if every pair went dead
      - 'done'   (partial) if some pairs succeeded and some died
    Called by _maybe_finalize, on_dead, and the reconcile loop.
    """
    from app.db import db_get_job_combined_report, db_recompute_scores, db_update_validation_job
    from job_runner.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        counts = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'dead') AS dead_count,
                COUNT(*) FILTER (WHERE status = 'done') AS done_count,
                COUNT(*) AS total
            FROM job_queue
            WHERE root_job_id = $1::uuid
            """,
            root_queue_job_id,
        )

    dead_count = counts["dead_count"] or 0
    done_count = counts["done_count"] or 0
    total = counts["total"] or 0

    if dead_count == total:
        # Every pair failed — mark as failed
        await db_update_validation_job(
            validation_job_id,
            status="failed",
            error=f"All {dead_count} pair job(s) exhausted retries",
            completed_at=datetime.now(timezone.utc),
        )
        logger.error("Validation job %s FAILED: all %d pairs dead", validation_job_id, dead_count)
        return

    # At least some pairs succeeded — compute scores and mark done (partial if any dead)
    await db_recompute_scores(validation_job_id)
    final_status = "done"
    error = f"{dead_count} of {total} pair(s) failed" if dead_count else None
    await db_update_validation_job(
        validation_job_id,
        status=final_status,
        error=error,
        completed_at=datetime.now(timezone.utc),
    )
    logger.info(
        "Validation job %s finalized: %d done, %d dead of %d total",
        validation_job_id, done_count, dead_count, total,
    )

    try:
        combined_report = await db_get_job_combined_report(validation_job_id)
        if combined_report:
            from app.queue import publish_for_extraction
            await publish_for_extraction(validation_job_id, combined_report)
            logger.info("Validation job %s: published combined report for KG extraction", validation_job_id)
    except Exception as exc:
        logger.warning("Validation job %s: failed to publish for KG extraction: %s", validation_job_id, exc)


@registry.register("validation_pair")
class ValidationPairWorkflow(BaseWorkflow):
    """
    Run research + LLM scoring for one entity × attribute pair.

    payload: {"validation_job_id", "campaign_id", "entity_id", "attribute_id"}
    """

    async def run(self) -> None:
        from app.db import (
            db_get_attribute,
            db_get_entity,
            db_increment_job_progress,
            db_insert_result,
            db_lookup_knowledge,
        )
        from worker.llm import determine_presence
        from worker.research import run_research

        p = self.payload
        job_id = p["validation_job_id"]
        entity_id = p["entity_id"]
        attribute_id = p["attribute_id"]

        entity = await db_get_entity(entity_id)
        attribute = await db_get_attribute(attribute_id)

        if not entity or not attribute:
            logger.warning(
                "validation_pair job=%s: entity %s or attribute %s not found, skipping",
                job_id, entity_id, attribute_id,
            )
            await db_increment_job_progress(job_id)
            await self._maybe_finalize(job_id)
            return

        # Cache check
        gwm_id = entity.get("gwm_id")
        if gwm_id:
            cached = await db_lookup_knowledge(gwm_id, attribute["label"])
            if cached:
                logger.info(
                    "validation_pair job=%s: cache hit gwm_id=%s × %s",
                    job_id, gwm_id, attribute["label"],
                )
                result = {
                    "present": cached["present"],
                    "confidence": cached.get("confidence"),
                    "evidence": cached.get("evidence"),
                }
                await db_insert_result(job_id, entity_id, attribute_id, result, "", update_knowledge=False)
                await db_increment_job_progress(job_id)
                await self._maybe_finalize(job_id)
                return

        query = f"{entity['label']}: {attribute['label']}. {attribute.get('description') or ''}"
        report_md = await run_research(query)
        result = await determine_presence(entity, attribute, report_md)
        await db_insert_result(job_id, entity_id, attribute_id, result, report_md)
        await db_increment_job_progress(job_id)
        logger.debug(
            "validation_pair job=%s: %s × %s → present=%s confidence=%.2f",
            job_id, entity.get("label"), attribute.get("label"),
            result.get("present"), result.get("confidence", 0),
        )
        await self._maybe_finalize(job_id)

    @classmethod
    async def on_dead(cls, job: dict) -> None:
        """
        Called when this pair job exhausted all retries.
        Check if it was the last sibling — if so, finalize the parent validation_job.
        """
        from job_runner.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            own = await conn.fetchrow(
                "SELECT root_job_id, payload FROM job_queue WHERE id = $1::uuid",
                str(job["id"]),
            )
        if own is None or own["root_job_id"] is None:
            return

        root_id = str(own["root_job_id"])
        validation_job_id = (own["payload"] or {}).get("validation_job_id")
        if not validation_job_id:
            return

        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM job_queue
                WHERE root_job_id = $1::uuid
                  AND status NOT IN ('done', 'dead')
                """,
                root_id,
            )
        if pending == 0:
            await finalize_validation_job(validation_job_id, root_id)

    async def _maybe_finalize(self, validation_job_id: str) -> None:
        """Check if all siblings are terminal; if so, finalize the validation_job."""
        from job_runner.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            own = await conn.fetchrow(
                "SELECT root_job_id FROM job_queue WHERE id = $1::uuid",
                self.job_id,
            )
            if own is None or own["root_job_id"] is None:
                return
            root_id = str(own["root_job_id"])
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM job_queue
                WHERE root_job_id = $1::uuid
                  AND status NOT IN ('done', 'dead')
                """,
                root_id,
            )
        if pending == 0:
            await finalize_validation_job(validation_job_id, root_id)

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
        from job_runner.db import get_pool
        from job_runner.config import settings as _settings
        from job_runner.queue import enqueue_many

        job_id = self.payload["validation_job_id"]

        entities, attributes = await db_get_job_details(job_id)
        pairs = [(str(e["id"]), str(a["id"])) for e in entities for a in attributes]
        campaign_id = str(entities[0]["campaign_id"]) if entities else None

        logger.info("ValidationCampaign job=%s: fanning out %d pairs", job_id, len(pairs))

        # All pair enqueues happen in a single transaction along with the
        # status update. If the process crashes mid-loop nothing is committed,
        # so on retry we start fresh with a clean fan-out.
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Idempotency: skip if pairs already enqueued for this root job
                # (handles the case where the campaign job itself is retried)
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM job_queue WHERE root_job_id = $1::uuid",
                    self.job_id,
                )
                if existing > 0:
                    logger.info(
                        "ValidationCampaign job=%s: %d pairs already enqueued, skipping fan-out",
                        job_id, existing,
                    )
                else:
                    pair_jobs = [
                        {
                            "job_type": "validation_pair",
                            "payload": {
                                "validation_job_id": job_id,
                                "campaign_id": campaign_id,
                                "entity_id": entity_id,
                                "attribute_id": attribute_id,
                            },
                            "parent_job_id": self.job_id,
                            "root_job_id": self.job_id,
                            "validation_job_id": job_id,
                            "max_attempts": _settings.default_max_attempts,
                        }
                        for entity_id, attribute_id in pairs
                    ]
                    await enqueue_many(pair_jobs, conn=conn)

                await conn.execute(
                    """
                    UPDATE validation_jobs
                    SET status = 'running', total_pairs = $2, started_at = $3
                    WHERE id = $1::uuid AND status = 'queued'
                    """,
                    job_id, len(pairs), datetime.now(timezone.utc),
                )
                # Notify workers about the new batch
                await conn.execute(
                    "SELECT pg_notify($1, $2)",
                    _settings.listen_channel,
                    job_id,
                )


async def finalize_validation_job(validation_job_id: str, root_queue_job_id: str) -> None:
    """
    Finalize a validation_job once all its pair children have reached a terminal
    state (done or dead).

    Uses a conditional UPDATE (WHERE status = 'running') as an atomic compare-and-swap
    so that concurrent callers (on_dead hook, _maybe_finalize, reconcile loop) are
    all safe: exactly one wins the race and proceeds; the rest are silent no-ops.

    Final status:
      - 'failed' if every pair went dead
      - 'done'   otherwise (with error note if some pairs died)
    """
    from app.db import db_get_job_combined_report, db_recompute_scores
    from job_runner.db import get_pool

    pool = await get_pool()

    # Count terminal outcomes for all pair children
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

    if dead_count == total and total > 0:
        final_status = "failed"
        error = f"All {dead_count} pair job(s) exhausted retries"
    else:
        final_status = "done"
        error = f"{dead_count} of {total} pair(s) failed" if dead_count else None

    # Atomic CAS: only the first caller transitions 'running' → final_status.
    # If validation_job is already done/failed (another worker beat us), RETURNING
    # yields no rows and we skip the expensive score recompute + publish.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE validation_jobs
            SET status = $2, error = $3, completed_at = NOW()
            WHERE id = $1::uuid AND status = 'running'
            RETURNING id
            """,
            validation_job_id,
            final_status,
            error,
        )

    if row is None:
        # Another worker already finalized this job — nothing to do.
        logger.debug("Validation job %s already finalized by another worker", validation_job_id)
        return

    logger.info(
        "Validation job %s finalized → %s (%d done, %d dead of %d total)",
        validation_job_id, final_status, done_count, dead_count, total,
    )

    if final_status == "done":
        try:
            await db_recompute_scores(validation_job_id)
        except Exception as exc:
            logger.error("Validation job %s: score recompute failed: %s", validation_job_id, exc)

        try:
            combined_report = await db_get_job_combined_report(validation_job_id)
            if combined_report:
                from app.queue import publish_for_extraction
                await publish_for_extraction(validation_job_id, combined_report)
                logger.info("Validation job %s: published combined report for KG extraction", validation_job_id)
        except Exception as exc:
            logger.warning("Validation job %s: failed to publish for KG extraction: %s", validation_job_id, exc)
    else:
        logger.error("Validation job %s FAILED: all %d pairs dead", validation_job_id, dead_count)


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
        root_job_id and payload are already in the job dict from dequeue; no extra
        DB query needed.
        """
        from job_runner.db import get_pool

        root_id = str(job["root_job_id"]) if job.get("root_job_id") else None
        if not root_id:
            return
        payload = job.get("payload") or {}
        validation_job_id = payload.get("validation_job_id")
        if not validation_job_id:
            return

        pool = await get_pool()
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
        """
        Check if all siblings are terminal; if so, finalize the validation_job.

        This is called from within run(), before ack(), so the current job is
        still 'running' in job_queue. We exclude our own job_id from the pending
        count so that the last pair job can trigger finalization immediately
        instead of waiting up to 60s for the reconcile loop.

        The result has already been inserted by the time we're called, so
        finalize_validation_job will see the full, correct result set when it
        recomputes scores.
        """
        from job_runner.db import get_pool
        pool = await get_pool()
        # root_job_id is available in the original job dict from dequeue.
        root_id = str(self.job["root_job_id"]) if self.job.get("root_job_id") else None
        if not root_id:
            return
        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM job_queue
                WHERE root_job_id = $1::uuid
                  AND id != $2::uuid
                  AND status NOT IN ('done', 'dead')
                """,
                root_id, self.job_id,
            )
        if pending == 0:
            await finalize_validation_job(validation_job_id, root_id)

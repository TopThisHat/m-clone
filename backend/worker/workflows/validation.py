"""
Validation workflows: campaign fan-out + per-pair research/scoring.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from worker.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)


@registry.register("validation_campaign")
class ValidationCampaignWorkflow(BaseWorkflow):
    """
    Fan-out: fetches entity x attribute pairs and enqueues one validation_pair
    job per pair.

    payload: {"validation_job_id": str}
    """

    @classmethod
    async def on_dead(cls, job: dict) -> None:
        """
        Called when the campaign fan-out job exhausts all retries.
        Mark the validation_job as failed so it is not stuck in 'queued' forever.
        """
        from app.db import db_update_validation_job
        raw = job.get("payload") or {}
        payload = json.loads(raw) if isinstance(raw, str) else raw
        validation_job_id = payload.get("validation_job_id")
        if not validation_job_id:
            return
        try:
            await db_update_validation_job(
                validation_job_id,
                status="failed",
                error="Campaign fan-out job exhausted all retries",
            )
            logger.error(
                "ValidationCampaign job=%s: fan-out dead after max retries, marked validation_job failed",
                validation_job_id,
            )
        except Exception as exc:
            logger.error(
                "ValidationCampaign on_dead: failed to mark validation_job %s failed: %s",
                validation_job_id, exc,
            )

    async def run(self) -> None:
        from app.db import db_get_job_details, db_update_validation_job
        from app.db import get_pool
        from app.job_queue import enqueue_many
        from worker.config import settings as _settings

        job_id = self.payload["validation_job_id"]

        entities, attributes = await db_get_job_details(job_id)
        pairs = [(str(e["id"]), str(a["id"])) for e in entities for a in attributes]
        campaign_id = str(entities[0]["campaign_id"]) if entities else None

        logger.info("ValidationCampaign job=%s: fanning out %d pairs", job_id, len(pairs))

        # Pre-enqueue cache deduplication
        from app.db import db_insert_results_batch, db_lookup_knowledge_batch

        entity_map = {str(e["id"]): e for e in entities}
        attr_map = {str(a["id"]): a for a in attributes}

        gwm_pairs = [
            (entity_map[eid]["gwm_id"], attr_map[aid]["label"])
            for eid, aid in pairs
            if entity_map[eid].get("gwm_id")
        ]
        cache_hits = await db_lookup_knowledge_batch(gwm_pairs, max_age_hours=_settings.knowledge_cache_ttl_hours)

        hit_set = {
            (eid, aid) for eid, aid in pairs
            if entity_map[eid].get("gwm_id")
            and (entity_map[eid]["gwm_id"], attr_map[aid]["label"]) in cache_hits
        }
        miss_pairs = [(eid, aid) for eid, aid in pairs if (eid, aid) not in hit_set]

        if hit_set:
            cached_results = [
                {
                    "entity_id": eid,
                    "attribute_id": aid,
                    **cache_hits[(entity_map[eid]["gwm_id"], attr_map[aid]["label"])],
                }
                for eid, aid in hit_set
            ]
            logger.info(
                "ValidationCampaign job=%s: %d cache hits, %d pairs need research",
                job_id, len(hit_set), len(miss_pairs),
            )
            await db_insert_results_batch(job_id, cached_results)

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Idempotency: skip if pairs already enqueued for this root job
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM playbook.job_queue WHERE root_job_id = $1::uuid",
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
                        for entity_id, attribute_id in miss_pairs
                    ]
                    await enqueue_many(pair_jobs, conn=conn, max_attempts=_settings.default_max_attempts)

                await conn.execute(
                    """
                    UPDATE playbook.validation_jobs
                    SET status = 'running', total_pairs = $2, started_at = $3
                    WHERE id = $1::uuid AND status = 'queued'
                    """,
                    job_id, len(pairs), datetime.now(timezone.utc),
                )
                # Notify the dispatcher about the new batch
                if miss_pairs:
                    await conn.execute(
                        "SELECT pg_notify('job_available', $1)",
                        job_id,
                    )

        # If all pairs were cache hits, finalize immediately
        if not miss_pairs:
            logger.info(
                "ValidationCampaign job=%s: all %d pairs were cache hits, finalizing",
                job_id, len(pairs),
            )
            from app.job_queue import finalize_validation_job as _finalize
            await _finalize(job_id, self.job_id)


@registry.register("validation_pair")
class ValidationPairWorkflow(BaseWorkflow):
    """
    Run research + LLM scoring for one entity x attribute pair.

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

        # Cancellation check
        from app.db import db_get_validation_job
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_pair job=%s: parent cancelled, skipping", job_id)
            await db_increment_job_progress(job_id)
            await self._maybe_finalize(job_id)
            return

        # Cache check
        from worker.config import settings as _settings
        gwm_id = entity.get("gwm_id")
        if gwm_id:
            cached = await db_lookup_knowledge(gwm_id, attribute["label"], max_age_hours=_settings.knowledge_cache_ttl_hours)
            if cached:
                logger.info(
                    "validation_pair job=%s: cache hit gwm_id=%s x %s",
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

        # Post-research cancellation check
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_pair job=%s: parent cancelled after research, skipping LLM", job_id)
            await db_increment_job_progress(job_id)
            await self._maybe_finalize(job_id)
            return

        result = await determine_presence(entity, attribute, report_md)
        await db_insert_result(job_id, entity_id, attribute_id, result, report_md)
        await db_increment_job_progress(job_id)
        logger.debug(
            "validation_pair job=%s: %s x %s -> present=%s confidence=%.2f",
            job_id, entity.get("label"), attribute.get("label"),
            result.get("present"), result.get("confidence", 0),
        )
        await self._maybe_finalize(job_id)

    @classmethod
    async def on_dead(cls, job: dict) -> None:
        from app.db import get_pool

        root_id = str(job["root_job_id"]) if job.get("root_job_id") else None
        if not root_id:
            return
        raw = job.get("payload") or {}
        payload = json.loads(raw) if isinstance(raw, str) else raw
        validation_job_id = payload.get("validation_job_id")
        if not validation_job_id:
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM playbook.job_queue
                WHERE root_job_id = $1::uuid
                  AND status NOT IN ('done', 'dead')
                """,
                root_id,
            )
        if pending == 0:
            from app.job_queue import finalize_validation_job as _finalize
            await _finalize(validation_job_id, root_id)

    async def _maybe_finalize(self, validation_job_id: str) -> None:
        """
        Check if all siblings are terminal; if so, finalize the validation_job.
        Excludes our own job_id from the pending count so the last pair job
        can trigger finalization immediately.
        """
        from app.db import get_pool
        pool = await get_pool()
        root_id = str(self.job["root_job_id"]) if self.job.get("root_job_id") else None
        if not root_id:
            return
        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM playbook.job_queue
                WHERE root_job_id = $1::uuid
                  AND id != $2::uuid
                  AND status NOT IN ('done', 'dead')
                """,
                root_id, self.job_id,
            )
        if pending == 0:
            from app.job_queue import finalize_validation_job as _finalize
            await _finalize(validation_job_id, root_id)

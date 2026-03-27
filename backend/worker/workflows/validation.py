"""
Validation workflows: campaign fan-out + cluster-based research/scoring.

Workflow hierarchy:
  validation_campaign  →  groups attributes into clusters, fans out per (entity, cluster)
  validation_cluster   →  researches one cluster of attributes for one entity
  validation_pair      →  (legacy) single entity×attribute pair — kept for backward compat
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from worker.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)

# Maximum number of cluster jobs to enqueue per batch insert.
# Per job queue expert: batch-enqueue in chunks so the dispatcher can start
# claiming jobs immediately instead of waiting for one massive INSERT.
_ENQUEUE_BATCH_SIZE = 500


# ── Shared helper ────────────────────────────────────────────────────────────

async def _maybe_finalize(job: dict, job_id_self: str, validation_job_id: str) -> None:
    """
    Check if all sibling jobs under the same root are terminal; if so,
    finalize the validation_job. Excludes our own job_id from the pending
    count so the last job can trigger finalization immediately.
    """
    from app.db import get_pool

    root_id = str(job["root_job_id"]) if job.get("root_job_id") else None
    if not root_id:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending = await conn.fetchval(
            """
            SELECT COUNT(*) FROM playbook.job_queue
            WHERE root_job_id = $1::uuid
              AND id != $2::uuid
              AND status NOT IN ('done', 'dead')
            """,
            root_id, job_id_self,
        )
    if pending == 0:
        from app.job_queue import finalize_validation_job as _finalize
        await _finalize(validation_job_id, root_id)


async def _on_dead_check_finalize(job: dict) -> None:
    """Common on_dead logic: if all siblings are terminal, finalize."""
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


# ── Campaign fan-out ─────────────────────────────────────────────────────────

@registry.register("validation_campaign")
class ValidationCampaignWorkflow(BaseWorkflow):
    """
    Fan-out: clusters attributes, checks staleness, enqueues validation_cluster
    jobs for each (entity, cluster) that needs research.

    payload: {"validation_job_id": str}
    """

    @classmethod
    async def on_dead(cls, job: dict) -> None:
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
                "ValidationCampaign job=%s: fan-out dead after max retries",
                validation_job_id,
            )
        except Exception as exc:
            logger.error(
                "ValidationCampaign on_dead: failed to mark validation_job %s failed: %s",
                validation_job_id, exc,
            )

    async def run(self) -> None:
        from app.db import (
            db_get_campaign,
            db_get_job_details,
            db_insert_results_batch,
            db_update_validation_job,
            get_pool,
        )
        from app.db.knowledge import db_check_staleness_batch
        from app.job_queue import enqueue_many
        from worker.config import settings as _settings
        from worker.workflows.attribute_clustering import get_or_create_clusters

        job_id = self.payload["validation_job_id"]

        entities, attributes = await db_get_job_details(job_id)
        if not entities or not attributes:
            logger.warning("ValidationCampaign job=%s: no entities or attributes", job_id)
            await db_update_validation_job(job_id, status="done", error="No entities or attributes")
            return

        campaign_id = str(entities[0]["campaign_id"])
        total_pairs = len(entities) * len(attributes)

        # Get campaign for team_id
        campaign = await db_get_campaign(campaign_id)
        team_id = campaign.get("team_id") if campaign else None

        logger.info(
            "ValidationCampaign job=%s: %d entities x %d attributes = %d pairs",
            job_id, len(entities), len(attributes), total_pairs,
        )

        # ── Step 1: Cluster attributes ────────────────────────────────
        try:
            clusters = await get_or_create_clusters(campaign_id, attributes)
        except Exception as exc:
            logger.error("ValidationCampaign job=%s: clustering failed: %s", job_id, exc)
            await db_update_validation_job(job_id, status="failed", error=f"Attribute clustering failed: {exc}")
            return

        logger.info(
            "ValidationCampaign job=%s: %d attribute clusters created",
            job_id, len(clusters),
        )

        # Build lookup maps
        attr_map = {str(a["id"]): a for a in attributes}

        # ── Step 2: Batch staleness check ─────────────────────────────
        # Build all (gwm_id, attribute_label) pairs for staleness check
        staleness_pairs = []
        for e in entities:
            gwm_id = e.get("gwm_id")
            if gwm_id:
                for a in attributes:
                    staleness_pairs.append((gwm_id, a["label"]))

        staleness_map: dict[tuple[str, str], dict] = {}
        if staleness_pairs:
            try:
                staleness_map = await db_check_staleness_batch(staleness_pairs, team_id=team_id)
            except Exception as exc:
                logger.warning("ValidationCampaign job=%s: staleness check failed, proceeding without cache: %s", job_id, exc)

        # ── Step 3: Determine which (entity, cluster) pairs need research
        cached_results: list[dict] = []
        cluster_jobs_to_enqueue: list[dict] = []

        for entity in entities:
            eid = str(entity["id"])
            gwm_id = entity.get("gwm_id")

            for cluster in clusters:
                cluster_attr_ids = cluster["attribute_ids"]

                # Check staleness for each attribute in this cluster
                all_fresh = True
                cluster_cached = []

                for aid in cluster_attr_ids:
                    attr = attr_map.get(aid)
                    if not attr:
                        continue  # attribute deleted since clustering

                    if gwm_id and (gwm_id, attr["label"]) in staleness_map:
                        entry = staleness_map[(gwm_id, attr["label"])]
                        tier = entry.get("tier", "expired")
                        cached = entry.get("cached_result")

                        if tier in ("fresh", "warm") and cached:
                            # Cache hit — use cached result
                            cluster_cached.append({
                                "entity_id": eid,
                                "attribute_id": aid,
                                "present": cached.get("present", False),
                                "confidence": cached.get("confidence"),
                                "evidence": cached.get("evidence"),
                            })
                        else:
                            all_fresh = False
                    else:
                        all_fresh = False

                if all_fresh and len(cluster_cached) == len(cluster_attr_ids):
                    # All attributes in this cluster are fresh — use cache
                    cached_results.extend(cluster_cached)
                else:
                    # Need research for this (entity, cluster)
                    # Substitute {entity} in the research question
                    question = cluster.get("research_question_template", "")
                    question = question.replace("{entity}", entity["label"])

                    cluster_jobs_to_enqueue.append({
                        "job_type": "validation_cluster",
                        "payload": {
                            "validation_job_id": job_id,
                            "campaign_id": campaign_id,
                            "entity_id": eid,
                            "cluster_id": cluster.get("id", ""),
                            "attribute_ids": cluster_attr_ids,
                            "research_question": question,
                            "team_id": team_id,
                        },
                        "parent_job_id": self.job_id,
                        "root_job_id": self.job_id,
                        "validation_job_id": job_id,
                        "max_attempts": _settings.default_max_attempts,
                    })

        # ── Step 4: Insert cached results ─────────────────────────────
        if cached_results:
            await db_insert_results_batch(job_id, cached_results)
            logger.info(
                "ValidationCampaign job=%s: %d cache hits, %d cluster jobs to enqueue",
                job_id, len(cached_results), len(cluster_jobs_to_enqueue),
            )

        # ── Step 5: Enqueue cluster jobs in batches ───────────────────
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Idempotency: skip if jobs already enqueued for this root
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM playbook.job_queue WHERE root_job_id = $1::uuid",
                    self.job_id,
                )
                if existing > 0:
                    logger.info(
                        "ValidationCampaign job=%s: %d jobs already enqueued, skipping fan-out",
                        job_id, existing,
                    )
                elif cluster_jobs_to_enqueue:
                    # Batch enqueue in chunks per job queue expert rec
                    for i in range(0, len(cluster_jobs_to_enqueue), _ENQUEUE_BATCH_SIZE):
                        chunk = cluster_jobs_to_enqueue[i:i + _ENQUEUE_BATCH_SIZE]
                        await enqueue_many(chunk, conn=conn, max_attempts=_settings.default_max_attempts)
                        # Notify after each chunk so dispatcher can start immediately
                        await conn.execute("SELECT pg_notify('job_available', $1)", job_id)

                await conn.execute(
                    """
                    UPDATE playbook.validation_jobs
                    SET status = 'running', total_pairs = $2, started_at = $3
                    WHERE id = $1::uuid AND status = 'queued'
                    """,
                    job_id, total_pairs, datetime.now(timezone.utc),
                )

        # If all pairs were cache hits, finalize immediately
        if not cluster_jobs_to_enqueue:
            logger.info(
                "ValidationCampaign job=%s: all %d pairs were cache hits, finalizing",
                job_id, total_pairs,
            )
            from app.job_queue import finalize_validation_job as _finalize
            await _finalize(job_id, self.job_id)


# ── Cluster-based validation ─────────────────────────────────────────────────

@registry.register("validation_cluster")
class ValidationClusterWorkflow(BaseWorkflow):
    """
    Research a cluster of attributes for one entity.

    Runs a single research query covering all attributes in the cluster,
    then uses multi-attribute verification to extract per-attribute verdicts.

    payload: {
        "validation_job_id": str,
        "campaign_id": str,
        "entity_id": str,
        "cluster_id": str,
        "attribute_ids": [str, ...],
        "research_question": str,  # with {entity} already substituted
    }
    """

    async def run(self) -> None:
        from app.db import (
            db_get_attribute,
            db_get_entity,
            db_get_validation_job,
            db_increment_job_progress,
            db_insert_result,
        )
        from worker.llm import verify_attributes_from_report
        from worker.research import run_research

        p = self.payload
        job_id = p["validation_job_id"]
        entity_id = p["entity_id"]
        attribute_ids = p["attribute_ids"]

        # Load entity
        entity = await db_get_entity(entity_id)
        if not entity:
            logger.warning("validation_cluster job=%s: entity %s not found, skipping", job_id, entity_id)
            for _ in attribute_ids:
                await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # Load attributes (filter out any deleted)
        attributes = []
        valid_attr_ids = []
        for aid in attribute_ids:
            attr = await db_get_attribute(aid)
            if attr:
                attributes.append(attr)
                valid_attr_ids.append(aid)

        if not attributes:
            logger.warning("validation_cluster job=%s: no valid attributes for entity %s", job_id, entity_id)
            for _ in attribute_ids:
                await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # Cancellation check
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_cluster job=%s: parent cancelled, skipping", job_id)
            for _ in valid_attr_ids:
                await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # ── Research ──────────────────────────────────────────────────
        research_question = p.get("research_question", "")
        if not research_question:
            # Fallback: build question from entity + attribute labels
            attr_labels = ", ".join(a["label"] for a in attributes)
            research_question = f"{entity['label']}: {attr_labels}"

        report_md = await run_research(research_question)

        # Post-research cancellation check
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_cluster job=%s: parent cancelled after research, skipping LLM", job_id)
            for _ in valid_attr_ids:
                await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # ── Multi-attribute verification ──────────────────────────────
        results = await verify_attributes_from_report(entity, attributes, report_md)

        # ── Store results + update progress ───────────────────────────
        low_conf_count = 0
        for aid, attr, result in zip(valid_attr_ids, attributes, results):
            await db_insert_result(job_id, entity_id, aid, result, report_md)
            await db_increment_job_progress(job_id)
            if result.get("confidence", 0) < 0.5:
                low_conf_count += 1

        # Log cluster-level summary
        logger.info(
            "validation_cluster job=%s: entity=%s cluster=%s — %d attrs verified (%d low-confidence)",
            job_id, entity.get("label"), p.get("cluster_id", "?"),
            len(results), low_conf_count,
        )

        await _maybe_finalize(self.job, self.job_id, job_id)

    @classmethod
    async def on_dead(cls, job: dict) -> None:
        # Per job queue expert: don't fail the entire campaign for one dead cluster.
        # Just log and check if all siblings are terminal.
        raw = job.get("payload") or {}
        payload = json.loads(raw) if isinstance(raw, str) else raw
        attr_count = len(payload.get("attribute_ids", []))
        logger.warning(
            "validation_cluster on_dead: cluster with %d attributes died for entity=%s",
            attr_count, payload.get("entity_id"),
        )
        await _on_dead_check_finalize(job)


# ── Legacy per-pair validation (kept for backward compat) ────────────────────

@registry.register("validation_pair")
class ValidationPairWorkflow(BaseWorkflow):
    """
    Run research + LLM scoring for one entity x attribute pair.
    LEGACY — new campaigns use validation_cluster instead.

    payload: {"validation_job_id", "campaign_id", "entity_id", "attribute_id"}
    """

    async def run(self) -> None:
        from app.db import (
            db_get_attribute,
            db_get_entity,
            db_get_validation_job,
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
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # Cancellation check
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_pair job=%s: parent cancelled, skipping", job_id)
            await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        # Cache check
        from worker.config import settings as _settings

        gwm_id = entity.get("gwm_id")
        team_id = p.get("team_id")
        if not gwm_id:
            logger.warning(
                "validation_pair job=%s: entity %s has NULL gwm_id, skipping knowledge cache",
                job_id, entity.get("label"),
            )
        if gwm_id:
            cached = await db_lookup_knowledge(
                gwm_id, attribute["label"],
                team_id=team_id,
                max_age_hours=_settings.knowledge_cache_ttl_hours,
            )
            if cached:
                logger.info("validation_pair job=%s: cache hit gwm_id=%s x %s", job_id, gwm_id, attribute["label"])
                result = {
                    "present": cached["present"],
                    "confidence": cached.get("confidence"),
                    "evidence": cached.get("evidence"),
                }
                await db_insert_result(job_id, entity_id, attribute_id, result, "", update_knowledge=False)
                await db_increment_job_progress(job_id)
                await _maybe_finalize(self.job, self.job_id, job_id)
                return

        query = f"{entity['label']}: {attribute['label']}. {attribute.get('description') or ''}"
        report_md = await run_research(query)

        # Post-research cancellation check
        vj = await db_get_validation_job(job_id)
        if vj and vj.get("status") == "failed":
            logger.info("validation_pair job=%s: parent cancelled after research, skipping LLM", job_id)
            await db_increment_job_progress(job_id)
            await _maybe_finalize(self.job, self.job_id, job_id)
            return

        result = await determine_presence(entity, attribute, report_md)
        await db_insert_result(job_id, entity_id, attribute_id, result, report_md)
        await db_increment_job_progress(job_id)
        logger.debug(
            "validation_pair job=%s: %s x %s -> present=%s confidence=%.2f",
            job_id, entity.get("label"), attribute.get("label"),
            result.get("present"), result.get("confidence", 0),
        )
        await _maybe_finalize(self.job, self.job_id, job_id)

    @classmethod
    async def on_dead(cls, job: dict) -> None:
        await _on_dead_check_finalize(job)

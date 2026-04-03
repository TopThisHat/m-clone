"""Batch data processing workflows for the multi-mode agent engine.

Handles large-scale entity resolution, enrichment, and extraction jobs
that are offloaded from the inline agent execution via submit_batch_job.
"""
from __future__ import annotations

import logging
from typing import Any

from worker.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)


@registry.register("data_processing_batch_client_lookup")
class BatchClientLookupWorkflow(BaseWorkflow):
    """Process a batch of person names through client resolution.

    Payload schema:
        items: list[dict] -- each with 'name' and optional 'company'
        options: dict -- operation-specific options
        user_sid: str | None -- authenticated user
    """

    async def run(self) -> None:
        items = self.payload.get("items", [])
        options = self.payload.get("options", {})
        total = len(items)

        logger.info("BatchClientLookup starting: %d items (job %s)", total, self.job_id)

        if not items:
            await self._update_progress(0, 0, 0, [])
            return

        results: list[dict[str, Any]] = []
        completed = 0
        failed = 0

        for i, item in enumerate(items):
            name = item.get("name", "")
            company = item.get("company")

            try:
                result = await self._resolve_client(name, company)
                results.append({"index": i, "name": name, "status": "ok", **result})
            except Exception as exc:
                logger.warning("Item %d failed (%s): %s", i, name, exc)
                results.append({"index": i, "name": name, "status": "error", "error": str(exc)})
                failed += 1

            completed += 1

            # Update progress every 10 items or at completion
            if completed % 10 == 0 or completed == total:
                await self._update_progress(completed, total, failed, results)

        logger.info(
            "BatchClientLookup complete: %d/%d processed, %d failed (job %s)",
            completed, total, failed, self.job_id,
        )

    async def _resolve_client(self, name: str, company: str | None = None) -> dict:
        """Resolve a single client name. Uses the client resolver if available."""
        try:
            from app.agent.client_resolver import resolve_client
            result = await resolve_client(name, company=company)
            return {
                "gwm_id": result.get("gwm_id"),
                "confidence": result.get("confidence", 0.0),
                "match_found": result.get("match_found", False),
            }
        except ImportError:
            # Client resolver not available -- return stub
            logger.debug("client_resolver not available, returning stub for %s", name)
            return {"gwm_id": None, "confidence": 0.0, "match_found": False}
        except Exception as exc:
            raise RuntimeError(f"Resolution failed for {name}: {exc}") from exc

    async def _update_progress(
        self, completed: int, total: int, failed: int, results: list[dict],
    ) -> None:
        """Update job progress in the database."""
        try:
            from app.job_queue import update_job_progress
            await update_job_progress(self.job_id, {
                "items_completed": completed,
                "items_total": total,
                "items_failed": failed,
                "results": results,
            })
        except ImportError:
            logger.debug("update_job_progress not available")
        except Exception as exc:
            logger.warning("Failed to update progress for job %s: %s", self.job_id, exc)


@registry.register("data_processing_batch_enrichment")
class BatchEnrichmentWorkflow(BaseWorkflow):
    """Enrich a batch of entities with additional attributes.

    Payload schema:
        items: list[dict] -- each with 'entity_id' and optional context fields
        options: dict -- enrichment-specific options
        user_sid: str | None -- authenticated user
    """

    async def run(self) -> None:
        items = self.payload.get("items", [])
        total = len(items)

        logger.info("BatchEnrichment starting: %d items (job %s)", total, self.job_id)

        if not items:
            await self._update_progress(0, 0, 0, [])
            return

        results: list[dict[str, Any]] = []
        completed = 0
        failed = 0

        for i, item in enumerate(items):
            entity_id = item.get("entity_id", "")

            try:
                result = await self._enrich_entity(item)
                results.append({"index": i, "entity_id": entity_id, "status": "ok", **result})
            except Exception as exc:
                logger.warning("Item %d failed (entity_id=%s): %s", i, entity_id, exc)
                results.append({"index": i, "entity_id": entity_id, "status": "error", "error": str(exc)})
                failed += 1

            completed += 1

            if completed % 10 == 0 or completed == total:
                await self._update_progress(completed, total, failed, results)

        logger.info(
            "BatchEnrichment complete: %d/%d processed, %d failed (job %s)",
            completed, total, failed, self.job_id,
        )

    async def _enrich_entity(self, item: dict) -> dict:
        """Enrich a single entity. Stub -- real implementation depends on enrichment provider."""
        # Placeholder: subclasses or future implementations will override
        return {"enriched": True, "attributes_added": 0}

    async def _update_progress(
        self, completed: int, total: int, failed: int, results: list[dict],
    ) -> None:
        """Update job progress in the database."""
        try:
            from app.job_queue import update_job_progress
            await update_job_progress(self.job_id, {
                "items_completed": completed,
                "items_total": total,
                "items_failed": failed,
                "results": results,
            })
        except ImportError:
            logger.debug("update_job_progress not available")
        except Exception as exc:
            logger.warning("Failed to update progress for job %s: %s", self.job_id, exc)


@registry.register("data_processing_batch_extraction")
class BatchExtractionWorkflow(BaseWorkflow):
    """Extract structured data from a batch of text inputs.

    Payload schema:
        items: list[dict] -- each with 'text' and optional metadata
        options: dict -- extraction-specific options (e.g. schema, fields)
        user_sid: str | None -- authenticated user
    """

    async def run(self) -> None:
        items = self.payload.get("items", [])
        total = len(items)

        logger.info("BatchExtraction starting: %d items (job %s)", total, self.job_id)

        if not items:
            await self._update_progress(0, 0, 0, [])
            return

        results: list[dict[str, Any]] = []
        completed = 0
        failed = 0

        for i, item in enumerate(items):
            text = item.get("text", "")

            try:
                result = await self._extract_from_text(item)
                results.append({"index": i, "status": "ok", **result})
            except Exception as exc:
                logger.warning("Item %d failed: %s", i, exc)
                results.append({"index": i, "status": "error", "error": str(exc)})
                failed += 1

            completed += 1

            if completed % 10 == 0 or completed == total:
                await self._update_progress(completed, total, failed, results)

        logger.info(
            "BatchExtraction complete: %d/%d processed, %d failed (job %s)",
            completed, total, failed, self.job_id,
        )

    async def _extract_from_text(self, item: dict) -> dict:
        """Extract structured data from text. Stub -- real implementation depends on extraction logic."""
        # Placeholder: subclasses or future implementations will override
        return {"extracted": True, "entities_found": 0}

    async def _update_progress(
        self, completed: int, total: int, failed: int, results: list[dict],
    ) -> None:
        """Update job progress in the database."""
        try:
            from app.job_queue import update_job_progress
            await update_job_progress(self.job_id, {
                "items_completed": completed,
                "items_total": total,
                "items_failed": failed,
                "results": results,
            })
        except ImportError:
            logger.debug("update_job_progress not available")
        except Exception as exc:
            logger.warning("Failed to update progress for job %s: %s", self.job_id, exc)

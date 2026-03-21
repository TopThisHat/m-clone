"""
Entity & Relationship Extraction Worker.

Consumes reports from the Redis 'entity_extraction' stream, calls GPT-4o-mini
to extract named entities and relationships, deduplicates them against the
global knowledge graph in PostgreSQL, and detects/logs predicate conflicts.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# NOTE: LLM calls use app.openai_factory.get_openai_client() (imported lazily
# inside extract_entities_and_relationships) so the worker gets the same
# Azure/proxy/standard client the app uses.


# ── Pydantic models for LLM structured output ──────────────────────────────────

class ExtractedEntity(BaseModel):
    name: str
    type: str  # person | company | sports_team | location | product | other
    aliases: list[str] = []


class ExtractedRelationship(BaseModel):
    subject: str
    predicate: str
    predicate_family: str  # ownership | employment | transaction | location | partnership
    object: str
    confidence: float = 1.0
    evidence: str = ""


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []


# ── LLM extraction ─────────────────────────────────────────────────────────────

async def extract_entities_and_relationships(report_md: str) -> ExtractionResult:
    """
    Call GPT-4o-mini to extract named entities and relationships from a report.
    Returns an ExtractionResult (may be empty on failure).
    """
    prompt = f"""Extract named entities and relationships from the following research report.

Return ONLY valid JSON matching this schema:
{{
  "entities": [
    {{"name": "string", "type": "person|company|sports_team|location|product|other", "aliases": ["alt name", ...]}}
  ],
  "relationships": [
    {{
      "subject": "entity name",
      "predicate": "owns|employs|acquired|sold|located_in|partnered_with|...",
      "predicate_family": "ownership|employment|transaction|location|partnership",
      "object": "entity name",
      "confidence": 0.0-1.0,
      "evidence": "brief quote or explanation"
    }}
  ]
}}

Only include entities and relationships that are clearly stated in the report.
Use canonical, full names for entities. Use "sports_team" type for sports franchises/clubs
(not "company"). Predicate families must be one of:
ownership, employment, transaction, location, partnership.

Research report:
{report_md[:8000]}"""

    try:
        from app.openai_factory import get_openai_client

        resp = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
        raw = json.loads(resp.choices[0].message.content)
        return ExtractionResult.model_validate(raw)
    except Exception as exc:
        logger.error("extract_entities_and_relationships failed: %s", exc)
        return ExtractionResult()


# ── Consumer loop ──────────────────────────────────────────────────────────────

async def _process_message(session_id: str, report_md: str) -> None:
    """Process one extraction message: extract, deduplicate, and store."""
    from app.db import db_find_or_create_entity, db_upsert_relationship

    result = await extract_entities_and_relationships(report_md)
    if not result.entities and not result.relationships:
        logger.debug("Extraction for session_id=%s yielded no results", session_id)
        return

    # Pre-create all entities and build name→id map
    entity_id_map: dict[str, str] = {}
    for ent in result.entities:
        try:
            eid = await db_find_or_create_entity(ent.name, ent.type, ent.aliases)
            entity_id_map[ent.name.lower().strip()] = eid
        except Exception as exc:
            logger.warning("db_find_or_create_entity failed for '%s': %s", ent.name, exc)

    # Process relationships
    for rel in result.relationships:
        try:
            subject_key = rel.subject.lower().strip()
            object_key = rel.object.lower().strip()

            # Ensure subject/object entities exist even if not in extraction list
            if subject_key not in entity_id_map:
                eid = await db_find_or_create_entity(rel.subject, "other", [])
                entity_id_map[subject_key] = eid
            if object_key not in entity_id_map:
                eid = await db_find_or_create_entity(rel.object, "other", [])
                entity_id_map[object_key] = eid

            subject_id = entity_id_map[subject_key]
            object_id = entity_id_map[object_key]

            outcome = await db_upsert_relationship(
                subject_id=subject_id,
                predicate=rel.predicate,
                predicate_family=rel.predicate_family,
                object_id=object_id,
                confidence=rel.confidence,
                evidence=rel.evidence or None,
                source_session_id=session_id,
            )
            if outcome["status"] == "conflict":
                logger.info(
                    "KG conflict detected for session=%s: '%s' → '%s' superseded by '%s'",
                    session_id, outcome.get("old_id"), rel.predicate, outcome.get("new_id"),
                )
        except Exception as exc:
            logger.warning(
                "Relationship upsert failed for '%s' %s '%s': %s",
                rel.subject, rel.predicate, rel.object, exc,
            )

    logger.info(
        "KG extraction complete for session=%s: %d entities, %d relationships",
        session_id, len(result.entities), len(result.relationships),
    )


async def run_extraction_worker() -> None:
    """
    Long-running consumer loop. Reads from the Redis 'entity_extraction' stream
    and processes each message via the LLM extraction pipeline.
    """
    from app.streams import create_extraction_group as create_consumer_group, consume_extraction_next as consume_next, ack_extraction as ack_message

    await create_consumer_group()
    logger.info("Entity extraction worker started")

    while True:
        try:
            msg = await consume_next()
            if msg is None:
                continue
            msg_id, data = msg
            session_id = data.get("session_id", "")
            report_md = data.get("report_md", "")
            try:
                await _process_message(session_id, report_md)
            except Exception as exc:
                logger.error("Error processing extraction message %s: %s", msg_id, exc)
            finally:
                await ack_message(msg_id)
        except asyncio.CancelledError:
            logger.info("Entity extraction worker cancelled")
            break
        except Exception as exc:
            logger.error("Unexpected error in extraction worker loop: %s", exc)
            await asyncio.sleep(1)

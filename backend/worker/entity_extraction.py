"""
Entity & Relationship Extraction Worker.

Consumes reports from the Redis 'entity_extraction' stream, calls GPT-4o-mini
to extract named entities and relationships, deduplicates them against the
global knowledge graph in PostgreSQL, and detects/logs predicate conflicts.

Relationship consistency:
  - All predicates are normalized to a canonical set before insertion
  - Existing relationships are checked before upserting to prevent duplicates
  - Table structures in documents are preserved via markdown formatting
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Pydantic models for LLM structured output ──────────────────────────────────

class ExtractedEntity(BaseModel):
    name: str
    type: str  # person | company | sports_team | location | product | other
    aliases: list[str] = []
    disambiguation_context: str = ""


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

async def extract_entities_and_relationships(
    report_md: str,
    is_document: bool = False,
) -> ExtractionResult:
    """
    Call GPT-4o-mini to extract named entities and relationships from text.

    When is_document=True, uses an enhanced prompt that emphasizes:
    - Table structure preservation (markdown tables → relationships)
    - Canonical predicate usage
    - Disambiguation context for people
    """
    from app.predicate_normalization import get_canonical_predicates_prompt

    canonical_section = get_canonical_predicates_prompt()

    document_instructions = ""
    if is_document:
        document_instructions = """
IMPORTANT — Document Processing Rules:
1. This text was extracted from an uploaded document. Pay special attention to
   tables and structured data. Each row in a table often represents a distinct
   entity or relationship.
2. If a table has columns like "Name", "Role", "Team/Company", interpret each
   row as: the person (Name) has the role (Role) at the organization (Team/Company).
   For example: "John Smith | Owner | Dallas Cowboys" → John Smith OWNS Dallas Cowboys.
3. Preserve ALL structured relationships. Do not skip rows.
4. For ownership relationships, always use "owns" (not "buys", "purchased", etc.).
5. For employment relationships, use the most specific predicate available
   (ceo_of, president_of, board_member_of, etc.) rather than generic "employs".
"""

    prompt = f"""Extract named entities and relationships from the following text.

Return ONLY valid JSON matching this schema:
{{
  "entities": [
    {{"name": "string", "type": "person|company|sports_team|location|product|other", "aliases": ["alt name", ...], "disambiguation_context": "brief context to identify this entity uniquely, e.g. role/title/affiliation"}}
  ],
  "relationships": [
    {{
      "subject": "entity name",
      "predicate": "canonical predicate from the list below",
      "predicate_family": "ownership|employment|transaction|location|partnership",
      "object": "entity name",
      "confidence": 0.0-1.0,
      "evidence": "brief quote or explanation"
    }}
  ]
}}

{canonical_section}

Only include entities and relationships that are clearly stated in the text.
Use canonical, full names for entities. Use "sports_team" type for sports franchises/clubs
(not "company"). For each entity, provide a "disambiguation_context" that helps distinguish
people with the same name (e.g. "CEO of Goldman Sachs", "NFL quarterback").
{document_instructions}
Text to extract from:
{report_md[:12000]}"""

    try:
        from app.openai_factory import get_openai_client

        resp = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=4000,
        )
        raw = json.loads(resp.choices[0].message.content)
        return ExtractionResult.model_validate(raw)
    except Exception as exc:
        logger.error("extract_entities_and_relationships failed: %s", exc)
        return ExtractionResult()


# ── Relationship dedup check ──────────────────────────────────────────────────

async def _relationship_already_exists(
    conn: Any,
    subject_id: str,
    object_id: str,
    predicate: str,
    predicate_family: str,
) -> bool:
    """Check if an equivalent relationship already exists (active, same canonical predicate)."""
    row = await conn.fetchrow(
        """
        SELECT id FROM playbook.kg_relationships
        WHERE subject_id = $1::uuid AND object_id = $2::uuid
          AND predicate = $3 AND predicate_family = $4
          AND is_active = TRUE
        """,
        subject_id, object_id, predicate, predicate_family,
    )
    if row:
        return True

    # Also check reverse direction for symmetric relationships
    symmetric_families = {"partnership"}
    if predicate_family in symmetric_families:
        row = await conn.fetchrow(
            """
            SELECT id FROM playbook.kg_relationships
            WHERE subject_id = $2::uuid AND object_id = $1::uuid
              AND predicate_family = $3
              AND is_active = TRUE
            """,
            subject_id, object_id, predicate_family,
        )
        if row:
            return True

    return False


# ── Consumer loop ──────────────────────────────────────────────────────────────

async def _process_message(
    session_id: str,
    report_md: str,
    team_id: str | None = None,
    is_document: bool = False,
) -> dict[str, int]:
    """Process one extraction message: extract, normalize, deduplicate, and store.

    Returns counts: {"entities": N, "relationships": N, "skipped_duplicates": N}
    """
    from app.db import db_find_or_create_entity, db_upsert_relationship
    from app.db._pool import _acquire
    from app.predicate_normalization import normalize_predicate

    result = await extract_entities_and_relationships(report_md, is_document=is_document)
    if not result.entities and not result.relationships:
        logger.debug("Extraction for session_id=%s yielded no results", session_id)
        return {"entities": 0, "relationships": 0, "skipped_duplicates": 0}

    # Pre-create all entities and build name→id map
    entity_id_map: dict[str, str] = {}
    for ent in result.entities:
        try:
            eid = await db_find_or_create_entity(
                ent.name, ent.type, ent.aliases,
                team_id=team_id,
                disambiguation_context=ent.disambiguation_context,
            )
            entity_id_map[ent.name.lower().strip()] = eid
        except Exception as exc:
            logger.warning("db_find_or_create_entity failed for '%s': %s", ent.name, exc)

    # Process relationships with normalization and dedup
    skipped = 0
    inserted = 0
    async with _acquire() as conn:
        for rel in result.relationships:
            try:
                subject_key = rel.subject.lower().strip()
                object_key = rel.object.lower().strip()

                # Ensure subject/object entities exist
                if subject_key not in entity_id_map:
                    eid = await db_find_or_create_entity(rel.subject, "other", [], team_id=team_id)
                    entity_id_map[subject_key] = eid
                if object_key not in entity_id_map:
                    eid = await db_find_or_create_entity(rel.object, "other", [], team_id=team_id)
                    entity_id_map[object_key] = eid

                subject_id = entity_id_map[subject_key]
                object_id = entity_id_map[object_key]

                # Normalize predicate to canonical form
                canonical_pred, canonical_family = normalize_predicate(
                    rel.predicate, rel.predicate_family
                )

                # Check if relationship already exists before upserting
                exists = await _relationship_already_exists(
                    conn, subject_id, object_id, canonical_pred, canonical_family
                )
                if exists:
                    logger.debug(
                        "Skipping duplicate relationship: %s %s %s",
                        rel.subject, canonical_pred, rel.object,
                    )
                    skipped += 1
                    continue

                outcome = await db_upsert_relationship(
                    subject_id=subject_id,
                    predicate=canonical_pred,
                    predicate_family=canonical_family,
                    object_id=object_id,
                    confidence=rel.confidence,
                    evidence=rel.evidence or None,
                    source_session_id=session_id,
                    team_id=team_id,
                )
                if outcome["status"] == "conflict":
                    logger.info(
                        "KG conflict detected for session=%s: '%s' → '%s' superseded by '%s'",
                        session_id, outcome.get("old_id"), canonical_pred, outcome.get("new_id"),
                    )
                if outcome["status"] != "duplicate":
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "Relationship upsert failed for '%s' %s '%s': %s",
                    rel.subject, rel.predicate, rel.object, exc,
                )

    logger.info(
        "KG extraction complete for session=%s: %d entities, %d relationships inserted, %d duplicates skipped",
        session_id, len(result.entities), inserted, skipped,
    )
    return {
        "entities": len(result.entities),
        "relationships": inserted,
        "skipped_duplicates": skipped,
    }


_MAX_EXTRACTION_RETRIES = 3
_RETRY_KEY_TTL = 3600  # 1 hour


async def _get_extraction_retry_count(session_id: str, msg_id: str) -> int:
    """Get the retry count for an extraction message from Redis."""
    try:
        from app.streams import get_redis
        r = await get_redis()
        key = f"extraction_retries:{session_id}:{msg_id}"
        count = await r.get(key)
        return int(count) if count else 0
    except Exception:
        return 0


async def _increment_extraction_retry(session_id: str, msg_id: str) -> int:
    """Increment and return the retry count for an extraction message."""
    try:
        from app.streams import get_redis
        r = await get_redis()
        key = f"extraction_retries:{session_id}:{msg_id}"
        count = await r.incr(key)
        await r.expire(key, _RETRY_KEY_TTL)
        return count
    except Exception:
        return 0


async def run_extraction_worker() -> None:
    """
    Long-running consumer loop. Reads from the Redis 'entity_extraction' stream
    and processes each message via the LLM extraction pipeline.

    ACKs only on success. On failure, leaves the message unacked for redelivery
    up to _MAX_EXTRACTION_RETRIES times, then ACKs to prevent infinite loops.
    """
    from app.streams import (
        create_extraction_group as create_consumer_group,
        consume_extraction_next as consume_next,
        ack_extraction as ack_message,
    )

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
            team_id = data.get("team_id") or None
            is_document = data.get("is_document", "false").lower() == "true"
            try:
                await _process_message(
                    session_id, report_md,
                    team_id=team_id, is_document=is_document,
                )
                # ACK only on success
                await ack_message(msg_id)
            except Exception as exc:
                retry_count = await _increment_extraction_retry(session_id, msg_id)
                if retry_count >= _MAX_EXTRACTION_RETRIES:
                    logger.error(
                        "Extraction permanently failed for session=%s msg=%s after %d retries: %s",
                        session_id, msg_id, retry_count, exc,
                    )
                    await ack_message(msg_id)
                else:
                    logger.error(
                        "Extraction failed for session=%s msg=%s (attempt %d/%d), will retry: %s",
                        session_id, msg_id, retry_count, _MAX_EXTRACTION_RETRIES, exc,
                    )
                    # Leave unacked — consumer group will redeliver
        except asyncio.CancelledError:
            logger.info("Entity extraction worker cancelled")
            break
        except Exception as exc:
            logger.error("Unexpected error in extraction worker loop: %s", exc)
            await asyncio.sleep(1)

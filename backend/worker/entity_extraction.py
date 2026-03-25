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
    max_chars: int | None = 12_000,
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
{report_md[:max_chars] if max_chars else report_md}"""

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
        # Re-raise rate-limit errors so callers (e.g. _extract_batch) can retry
        exc_str = str(exc).lower()
        if "429" in str(exc) or "rate" in exc_str:
            raise
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


_BATCH_SEMAPHORE_LIMIT = 5
_BATCH_MAX_RETRIES = 2


def _merge_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Merge multiple extraction results into a single result."""
    merged_entities: list[ExtractedEntity] = []
    merged_rels: list[ExtractedRelationship] = []
    for r in results:
        merged_entities.extend(r.entities)
        merged_rels.extend(r.relationships)
    return ExtractionResult(entities=merged_entities, relationships=merged_rels)


async def _extract_document_batched(report_md: str) -> ExtractionResult:
    """Extract entities from a document using batched concurrent calls.

    - With page markers: split by pages → batch_page_texts → extract per batch.
    - Without page markers: RecursiveChunker(chunk_size=3500) → batch → extract.

    Each batch is error-isolated: failures log the page range and return empty
    results without blocking other batches. Rate-limit (429) errors are retried
    with exponential backoff up to _BATCH_MAX_RETRIES times.
    """
    from app.document_chunking import batch_page_texts, has_page_markers, split_by_pages

    if has_page_markers(report_md):
        pages = split_by_pages(report_md)
    else:
        # No page markers: split into ~3500-char paragraph groups to preserve
        # entity context across paragraph boundaries
        from chonkie import RecursiveChunker
        rc = RecursiveChunker(tokenizer="character", chunk_size=3500)
        chunks = rc.chunk(report_md)
        pages = [(i + 1, c.text) for i, c in enumerate(chunks)]

    batches = batch_page_texts(pages, target_chars=10_000)
    if not batches:
        return ExtractionResult()

    # Build page-range labels for error logging
    page_nums = [p[0] for p in pages]
    batch_labels: list[str] = []
    idx = 0
    for batch_text in batches:
        batch_pages: list[int] = []
        chars = 0
        while idx < len(pages) and chars < len(batch_text):
            batch_pages.append(page_nums[idx])
            chars += len(pages[idx][1])
            idx += 1
        if batch_pages:
            batch_labels.append(f"pages {batch_pages[0]}-{batch_pages[-1]}")
        else:
            batch_labels.append("unknown pages")

    sem = asyncio.Semaphore(_BATCH_SEMAPHORE_LIMIT)

    async def _extract_batch(batch_idx: int, batch_text: str) -> ExtractionResult:
        label = batch_labels[batch_idx]
        for attempt in range(_BATCH_MAX_RETRIES + 1):
            try:
                async with sem:
                    return await extract_entities_and_relationships(
                        batch_text, is_document=True, max_chars=None,
                    )
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "rate" in str(exc).lower()
                if is_rate_limit and attempt < _BATCH_MAX_RETRIES:
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        "Rate limit on batch %d (%s), retrying in %ds (attempt %d/%d): %s",
                        batch_idx, label, delay, attempt + 1, _BATCH_MAX_RETRIES, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "Batch %d (%s) failed after %d attempt(s): %s",
                    batch_idx, label, attempt + 1, exc,
                )
                return ExtractionResult()
        return ExtractionResult()

    results = await asyncio.gather(*[_extract_batch(i, b) for i, b in enumerate(batches)])

    successful = sum(1 for r in results if r.entities or r.relationships)
    if successful < len(batches):
        logger.warning(
            "Batched extraction: %d/%d batches returned results",
            successful, len(batches),
        )

    return _merge_results(list(results))


# ── Consumer loop ──────────────────────────────────────────────────────────────

async def _process_message(
    session_id: str,
    report_md: str,
    team_id: str | None = None,
    is_document: bool = False,
) -> dict[str, int]:
    """Process one extraction message: extract, normalize, deduplicate, and store.

    For document mode (is_document=True):
    - If text has page markers: split by pages, batch via batch_page_texts,
      then extract per batch with concurrency (semaphore=5).
    - If no page markers: RecursiveChunker(chunk_size=3500) for paragraph
      groups, then batch and extract.
    For non-document mode: single extract call with report_md[:12000].

    Returns counts: {"entities": N, "relationships": N, "skipped_duplicates": N}
    """
    from app.db import db_find_or_create_entity, db_upsert_relationship
    from app.db._pool import _acquire
    from app.predicate_normalization import normalize_predicate

    if is_document:
        result = await _extract_document_batched(report_md)
    else:
        result = await extract_entities_and_relationships(report_md, is_document=False)

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


async def _get_extraction_retry_count(session_id: str, msg_id: str) -> int:
    """Get the retry count for an extraction message from PostgreSQL."""
    try:
        pool = await _get_extraction_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT attempt_count FROM playbook.failed_extraction_tasks
                WHERE session_id = $1 AND msg_id = $2
                """,
                session_id, msg_id,
            )
            return row["attempt_count"] if row else 0
    except Exception:
        return 0


async def _increment_extraction_retry(
    session_id: str, msg_id: str, error: str, team_id: str | None = None,
) -> int:
    """Increment and return the retry count, persisted in PostgreSQL."""
    try:
        pool = await _get_extraction_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.failed_extraction_tasks
                    (session_id, msg_id, attempt_count, last_error, team_id)
                VALUES ($1, $2, 1, $3, $4)
                ON CONFLICT (session_id, msg_id) DO UPDATE
                    SET attempt_count = failed_extraction_tasks.attempt_count + 1,
                        last_error = EXCLUDED.last_error,
                        updated_at = NOW()
                RETURNING attempt_count
                """,
                session_id, msg_id, error, team_id,
            )
            return row["attempt_count"] if row else 0
    except Exception as exc:
        logger.warning("Failed to persist extraction retry for session=%s: %s", session_id, exc)
        return 0


async def _get_extraction_pool():
    from app.db import get_pool
    return await get_pool()


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
                retry_count = await _increment_extraction_retry(
                    session_id, msg_id, str(exc), team_id=team_id,
                )
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

"""
Entity & Relationship Extraction Worker.

Consumes reports from the Redis 'entity_extraction' stream, calls GPT-5.1
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
    type: str  # person | sports_team | sports_league | company | pe_fund | sports_foundation | transaction_event | location | life_event | media_rights_deal
    aliases: list[str] = []
    disambiguation_context: str = ""


class ExtractedRelationship(BaseModel):
    subject: str
    predicate: str
    predicate_family: str  # ownership | investment | role | deal_network | affinity | life_event | location
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
    Call GPT-5.1 to extract named entities and relationships from text.

    When is_document=True, uses an enhanced prompt that emphasizes:
    - Table structure preservation (markdown tables → relationships)
    - Canonical predicate usage
    - Disambiguation context for people
    """
    from app.kg_ontology import get_lm_prompt_section

    canonical_section = get_lm_prompt_section()

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
    {{"name": "string", "type": "person|sports_team|sports_league|company|pe_fund|sports_foundation|transaction_event|location|life_event|media_rights_deal", "aliases": ["alt name", ...], "disambiguation_context": "brief context to identify this entity uniquely, e.g. role/title/affiliation"}}
  ],
  "relationships": [
    {{
      "subject": "entity name",
      "predicate": "canonical predicate from the list below",
      "predicate_family": "ownership|investment|role|deal_network|affinity|life_event|location",
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
If an entity does not fit any of the listed types, DO NOT extract it.
{document_instructions}
Text to extract from:
{report_md[:max_chars] if max_chars else report_md}"""

    try:
        from app.openai_factory import get_openai_client

        resp = await get_openai_client().chat.completions.create(
            model="gpt-5.1",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_completion_tokens=4000,
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
    team_id: str,
) -> bool:
    """Check if an equivalent relationship already exists (active, same canonical predicate).

    Uses the ontology's per-predicate symmetry flag to decide whether to check
    the reverse direction (e.g. ``co_owns`` is symmetric but ``owns`` is not,
    even though both belong to the ``ownership`` family).

    The check is scoped to the given ``team_id`` so that identical
    relationships in different teams are not treated as duplicates.
    """
    from app.kg_ontology import RELATIONSHIP_FAMILIES

    row = await conn.fetchrow(
        """
        SELECT id FROM playbook.kg_relationships
        WHERE subject_id = $1::uuid AND object_id = $2::uuid
          AND predicate = $3 AND predicate_family = $4
          AND team_id = $5::uuid
          AND is_active = TRUE
        """,
        subject_id, object_id, predicate, predicate_family, team_id,
    )
    if row:
        return True

    # Check reverse direction only for symmetric predicates (per-predicate, not per-family)
    is_symmetric = False
    fam = RELATIONSHIP_FAMILIES.get(predicate_family)
    if fam:
        pred_spec = fam.predicates.get(predicate)
        if pred_spec:
            is_symmetric = pred_spec.symmetric

    if is_symmetric:
        row = await conn.fetchrow(
            """
            SELECT id FROM playbook.kg_relationships
            WHERE subject_id = $2::uuid AND object_id = $1::uuid
              AND predicate = $3 AND predicate_family = $4
              AND team_id = $5::uuid
              AND is_active = TRUE
            """,
            subject_id, object_id, predicate, predicate_family, team_id,
        )
        if row:
            return True

    return False


_BATCH_SEMAPHORE_LIMIT = 5
_BATCH_MAX_RETRIES = 2


def _merge_results(results: list[ExtractionResult]) -> ExtractionResult:
    """Merge multiple ExtractionResults, deduplicating by entity name and relationship triple."""
    seen_entities: set[str] = set()
    seen_rels: set[tuple[str, str, str]] = set()
    merged_entities: list[ExtractedEntity] = []
    merged_rels: list[ExtractedRelationship] = []
    for r in results:
        for ent in r.entities:
            key = ent.name.lower().strip()
            if key not in seen_entities:
                seen_entities.add(key)
                merged_entities.append(ent)
        for rel in r.relationships:
            key = (rel.subject.lower().strip(), rel.predicate, rel.object.lower().strip())
            if key not in seen_rels:
                seen_rels.add(key)
                merged_rels.append(rel)
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


# ── KG storage (shared by single-message and chunk-merge paths) ────────────────

async def _store_extraction_result(
    session_id: str,
    result: ExtractionResult,
    team_id: str | None = None,
    enable_client_lookup: bool = False,
) -> dict[str, int]:
    """Persist an ExtractionResult into the knowledge graph.

    Normalises predicates, deduplicates relationships, and optionally runs
    GWM client ID lookup for person entities.  Called by both the single-message
    path and the chunk-merge path so the KG write logic is never duplicated.

    Returns counts: {"entities": N, "relationships": N, "skipped_duplicates": N,
        "filtered_by_unknown_predicate": N, "filtered_by_relevance": N,
        "client_lookups": N}
    """
    from app.config import settings
    from app.db import db_find_or_create_entity, db_flag_entity_for_review, db_upsert_relationship
    from app.db._pool import _acquire
    from app.kg_ontology import (
        ALLOWED_ENTITY_TYPE_NAMES,
        normalize_predicate,
        should_keep_relationship,
    )

    # DB layer requires a non-None team_id; fall back to master team
    effective_team_id: str = team_id or settings.kg_master_team_id

    if not result.entities and not result.relationships:
        logger.debug("Extraction for session_id=%s yielded no results", session_id)
        return {
            "entities": 0,
            "relationships": 0,
            "skipped_duplicates": 0,
            "filtered_by_unknown_predicate": 0,
            "filtered_by_relevance": 0,
            "client_lookups": 0,
        }

    # Pre-create all entities and build name→id map (skip invalid types)
    entity_id_map: dict[str, str] = {}
    entities_created = 0
    for ent in result.entities:
        if ent.type not in ALLOWED_ENTITY_TYPE_NAMES:
            logger.debug(
                "Skipping entity '%s' with invalid type '%s' (not in ontology)",
                ent.name, ent.type,
            )
            continue
        try:
            entity_id, resolution_mode = await db_find_or_create_entity(
                ent.name, ent.type, ent.aliases,
                team_id=effective_team_id,
                disambiguation_context=ent.disambiguation_context,
            )
            logger.info(
                "entity_resolved session=%s team=%s entity=%s mode=%s id=%s",
                session_id, effective_team_id, ent.name, resolution_mode, entity_id,
            )
            if resolution_mode == "master_copy":
                await db_flag_entity_for_review(entity_id, effective_team_id, "sourced_from_master")
            entity_id_map[ent.name.lower().strip()] = entity_id
            entities_created += 1
        except Exception as exc:
            logger.warning("db_find_or_create_entity failed for '%s': %s", ent.name, exc)

    # Process relationships: normalize → check None → check relevance → dedup → upsert
    skipped = 0
    inserted = 0
    filtered_by_unknown_predicate = 0
    filtered_by_relevance = 0
    async with _acquire() as conn:
        for rel in result.relationships:
            try:
                norm_result = normalize_predicate(rel.predicate, rel.predicate_family)
                if norm_result is None:
                    logger.debug(
                        "Skipping relationship with unknown predicate: %s %s %s",
                        rel.subject, rel.predicate, rel.object,
                    )
                    filtered_by_unknown_predicate += 1
                    continue

                canonical_pred, canonical_family = norm_result

                if not should_keep_relationship(canonical_family, canonical_pred, rel.confidence):
                    logger.debug(
                        "Filtered by relevance: %s %s %s (family=%s, confidence=%.2f)",
                        rel.subject, canonical_pred, rel.object, canonical_family, rel.confidence,
                    )
                    filtered_by_relevance += 1
                    continue

                subject_key = rel.subject.lower().strip()
                object_key = rel.object.lower().strip()

                if subject_key not in entity_id_map:
                    entity_id, resolution_mode = await db_find_or_create_entity(
                        rel.subject, "person", [], team_id=effective_team_id,
                    )
                    logger.info(
                        "entity_resolved session=%s team=%s entity=%s mode=%s id=%s",
                        session_id, effective_team_id, rel.subject, resolution_mode, entity_id,
                    )
                    if resolution_mode == "master_copy":
                        await db_flag_entity_for_review(entity_id, effective_team_id, "sourced_from_master")
                    entity_id_map[subject_key] = entity_id
                if object_key not in entity_id_map:
                    entity_id, resolution_mode = await db_find_or_create_entity(
                        rel.object, "person", [], team_id=effective_team_id,
                    )
                    logger.info(
                        "entity_resolved session=%s team=%s entity=%s mode=%s id=%s",
                        session_id, effective_team_id, rel.object, resolution_mode, entity_id,
                    )
                    if resolution_mode == "master_copy":
                        await db_flag_entity_for_review(entity_id, effective_team_id, "sourced_from_master")
                    entity_id_map[object_key] = entity_id

                subject_id = entity_id_map[subject_key]
                object_id = entity_id_map[object_key]

                exists = await _relationship_already_exists(
                    conn, subject_id, object_id, canonical_pred, canonical_family,
                    team_id=effective_team_id,
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
                    team_id=effective_team_id,
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
        "KG extraction complete for session=%s: %d entities (%d created), "
        "%d relationships inserted, %d duplicates skipped, "
        "%d filtered by unknown predicate, %d filtered by relevance",
        session_id, len(result.entities), entities_created, inserted, skipped,
        filtered_by_unknown_predicate, filtered_by_relevance,
    )

    client_lookups = 0
    if enable_client_lookup:
        person_names = [ent.name for ent in result.entities if ent.type == "person"]
        if person_names:
            try:
                from app.agent.batch_resolver import batch_resolve_clients
                people = [{"name": n} for n in person_names]
                lookup_results = await batch_resolve_clients(people)
                matched = sum(1 for r in lookup_results if r.get("status") == "matched")
                client_lookups = len(lookup_results)
                logger.info(
                    "Client lookup complete for session=%s: %d/%d persons matched",
                    session_id, matched, client_lookups,
                )
            except Exception as exc:
                logger.warning("Client lookup failed for session=%s: %s", session_id, exc)

    return {
        "entities": entities_created,
        "relationships": inserted,
        "skipped_duplicates": skipped,
        "filtered_by_unknown_predicate": filtered_by_unknown_predicate,
        "filtered_by_relevance": filtered_by_relevance,
        "client_lookups": client_lookups,
    }


# ── Consumer loop ──────────────────────────────────────────────────────────────

async def _process_message(
    session_id: str,
    report_md: str,
    team_id: str | None = None,
    is_document: bool = False,
    enable_client_lookup: bool = False,
) -> dict[str, int]:
    """Process one extraction message: extract, normalise, deduplicate, and store.

    For document mode (is_document=True):
    - If text has page markers: split by pages → batch → extract per batch.
    - Otherwise: RecursiveChunker(chunk_size=3500) → batch → extract.
    For non-document mode: single extract call with report_md[:12000].

    Returns counts: {"entities": N, "relationships": N, "skipped_duplicates": N,
        "filtered_by_unknown_predicate": N, "filtered_by_relevance": N,
        "client_lookups": N}
    """
    if is_document:
        result = await _extract_document_batched(report_md)
    else:
        result = await extract_entities_and_relationships(report_md, is_document=False)

    return await _store_extraction_result(session_id, result, team_id, enable_client_lookup)


_MAX_EXTRACTION_RETRIES = 3
_CHUNK_MAX_RETRIES = 2
_CHUNK_PROGRESS_TTL = 3600  # 1 hour


async def _process_chunk(
    session_id: str,
    chunk_index: int,
    total_chunks: int,
    report_md: str,
    team_id: str | None = None,
    is_document: bool = False,
    enable_client_lookup: bool = False,
) -> dict[str, int]:
    """Process a single chunk from a fan-out extraction job.

    Retries LLM extraction up to ``_CHUNK_MAX_RETRIES`` times on failure, then
    marks the chunk as failed rather than raising.  Progress is tracked in a
    Redis hash (``extraction_progress:{session_id}``).  The worker that
    increments ``done_count`` to equal ``total_chunks`` is responsible for
    merging all partial results and writing to the knowledge graph.

    Returns non-zero counts only for the final (merge-triggering) worker; all
    other workers return zero counts since KG writes haven't happened yet.
    """
    from app.redis_client import get_redis as _get_redis

    progress_key = f"extraction_progress:{session_id}"
    chunk_field = f"chunk:{chunk_index}"

    result = ExtractionResult()
    failed = False

    for attempt in range(_CHUNK_MAX_RETRIES + 1):
        try:
            if is_document:
                result = await _extract_document_batched(report_md)
            else:
                result = await extract_entities_and_relationships(report_md, is_document=False)
            failed = False
            break
        except Exception as exc:
            if attempt < _CHUNK_MAX_RETRIES:
                delay = 2 ** attempt
                logger.warning(
                    "Chunk %d/%d for session=%s failed, retrying in %ds (attempt %d/%d): %s",
                    chunk_index, total_chunks - 1, session_id, delay,
                    attempt + 1, _CHUNK_MAX_RETRIES, exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Chunk %d/%d for session=%s permanently failed after %d retries: %s",
                    chunk_index, total_chunks - 1, session_id, _CHUNK_MAX_RETRIES + 1, exc,
                )
                failed = True

    _empty_counts: dict[str, int] = {
        "entities": 0,
        "relationships": 0,
        "skipped_duplicates": 0,
        "filtered_by_unknown_predicate": 0,
        "filtered_by_relevance": 0,
        "client_lookups": 0,
    }

    try:
        r = await _get_redis()

        # Persist chunk result so the merger can read it
        chunk_payload = (
            json.dumps({"failed": True, "entities": [], "relationships": []})
            if failed
            else result.model_dump_json()
        )
        await r.hset(
            progress_key,
            mapping={
                chunk_field: chunk_payload,
                f"status:{chunk_index}": "failed" if failed else "done",
            },
        )
        await r.expire(progress_key, _CHUNK_PROGRESS_TTL)

        # Atomic counter — exactly one worker sees done_count == total_chunks
        done_count = int(await r.hincrby(progress_key, "done_count", 1))

        logger.debug(
            "Chunk %d/%d stored for session=%s (done=%d/%d, failed=%s)",
            chunk_index, total_chunks - 1, session_id, done_count, total_chunks, failed,
        )

        if done_count == total_chunks:
            logger.info(
                "All %d chunks complete for session=%s — merging results",
                total_chunks, session_id,
            )
            return await _merge_and_store_chunks(
                session_id, total_chunks, team_id, enable_client_lookup,
            )

    except Exception as exc:
        logger.error(
            "Chunk progress tracking failed for session=%s chunk=%d: %s",
            session_id, chunk_index, exc,
        )
        # Redis unavailable: fall back to storing this chunk's result directly
        if not failed:
            return await _store_extraction_result(session_id, result, team_id, enable_client_lookup)

    return _empty_counts


async def _merge_and_store_chunks(
    session_id: str,
    total_chunks: int,
    team_id: str | None = None,
    enable_client_lookup: bool = False,
) -> dict[str, int]:
    """Collect all chunk results from Redis, merge, and write to the knowledge graph.

    Called by the final worker for a given ``session_id``.  Failed chunks
    contribute empty results so partial results are still preserved.
    """
    from app.redis_client import get_redis as _get_redis

    progress_key = f"extraction_progress:{session_id}"
    _empty_counts: dict[str, int] = {
        "entities": 0,
        "relationships": 0,
        "skipped_duplicates": 0,
        "filtered_by_unknown_predicate": 0,
        "filtered_by_relevance": 0,
        "client_lookups": 0,
    }

    try:
        r = await _get_redis()
        results: list[ExtractionResult] = []
        failed_chunks = 0

        for i in range(total_chunks):
            raw = await r.hget(progress_key, f"chunk:{i}")
            if not raw:
                logger.warning("Missing chunk %d data for session=%s", i, session_id)
                failed_chunks += 1
                continue
            try:
                parsed = json.loads(raw)
                if parsed.get("failed"):
                    failed_chunks += 1
                else:
                    results.append(ExtractionResult.model_validate(parsed))
            except Exception as exc:
                logger.warning(
                    "Failed to deserialise chunk %d for session=%s: %s", i, session_id, exc,
                )
                failed_chunks += 1

        if failed_chunks:
            logger.warning(
                "Merging with %d/%d failed chunks for session=%s",
                failed_chunks, total_chunks, session_id,
            )

        if not results:
            logger.warning("No successful chunk results to merge for session=%s", session_id)
            return _empty_counts

        merged = _merge_results(results)
        logger.info(
            "Merged %d/%d chunks for session=%s: %d entities, %d relationships",
            len(results), total_chunks, session_id,
            len(merged.entities), len(merged.relationships),
        )
        return await _store_extraction_result(session_id, merged, team_id, enable_client_lookup)

    except Exception as exc:
        logger.error("Chunk merge failed for session=%s: %s", session_id, exc)
        return _empty_counts


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
            enable_client_lookup = data.get("enable_client_lookup", "false").lower() == "true"
            chunk_index_raw = data.get("chunk_index")
            total_chunks_raw = data.get("total_chunks")
            is_chunked = chunk_index_raw is not None and total_chunks_raw is not None
            try:
                if is_chunked:
                    await _process_chunk(
                        session_id,
                        int(chunk_index_raw),
                        int(total_chunks_raw),
                        report_md,
                        team_id=team_id,
                        is_document=is_document,
                        enable_client_lookup=enable_client_lookup,
                    )
                else:
                    await _process_message(
                        session_id, report_md,
                        team_id=team_id, is_document=is_document,
                        enable_client_lookup=enable_client_lookup,
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

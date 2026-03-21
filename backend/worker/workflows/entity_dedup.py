"""
LLM-assisted entity deduplication (Layer 3).

When pg_trgm returns ambiguous candidates (0.4 <= similarity < 0.85),
this module uses an LLM to confirm whether entities are the same.

Supports batch dedup for imports: groups candidates by target entity
to minimize LLM calls (per devil's advocate recommendation).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

_DEDUP_SEM = asyncio.Semaphore(5)  # limit concurrent LLM dedup calls

# Similarity thresholds
AUTO_MERGE_THRESHOLD = 0.85  # auto-merge without LLM
LLM_CONFIRM_THRESHOLD = 0.4  # ask LLM for confirmation
LLM_CONFIDENCE_THRESHOLD = 0.7  # LLM must be this confident to merge


async def llm_confirm_entity_match(
    new_entity: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Ask LLM whether new_entity is the same real-world entity as candidate.

    Returns: {"same_entity": bool, "confidence": float, "reason": str}
    """
    prompt = f"""Are these the same real-world entity?

Entity A: {new_entity}
Entity B: {candidate['name']} (type: {candidate.get('entity_type', 'unknown')}, aliases: {candidate.get('aliases', [])})

Consider:
- Different name formats (e.g., "JP Morgan" vs "JPMorgan Chase & Co.")
- Parent companies vs subsidiaries (these are DIFFERENT entities)
- Abbreviations and ticker symbols

Answer with JSON: {{"same_entity": true|false, "confidence": 0.0-1.0, "reason": "brief explanation"}}"""

    try:
        async with _DEDUP_SEM:
            resp = await get_openai_client().chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=200,
            )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.error("llm_confirm_entity_match failed for '%s' vs '%s': %s", new_entity, candidate.get("name"), exc)
        return {"same_entity": False, "confidence": 0.0, "reason": f"Error: {exc}"}


async def deduplicate_entity(
    name: str,
    entity_type: str,
    aliases: list[str],
    team_id: str | None = None,
) -> dict[str, Any]:
    """
    Three-layer deduplication for a single entity.

    Returns: {
        "action": "existing" | "created",
        "entity_id": str,
        "merged_into": str | None,  # name of entity we merged into
    }
    """
    from app.db.knowledge_graph import (
        db_find_or_create_entity,
        db_find_similar_entities,
        db_merge_kg_entities,
    )

    normalized = name.lower().strip()

    # Layer 1+2: Exact match (handled by db_find_or_create_entity)
    # First check if trigram search finds near-exact matches
    candidates = await db_find_similar_entities(name, team_id=team_id, threshold=LLM_CONFIRM_THRESHOLD)

    for candidate in candidates:
        sim = candidate.get("similarity", 0)
        cand_name = candidate.get("name", "").lower().strip()

        # Exact match — already handled by db_find_or_create_entity
        if cand_name == normalized:
            entity_id = await db_find_or_create_entity(name, entity_type, aliases, team_id=team_id)
            return {"action": "existing", "entity_id": entity_id, "merged_into": candidate["name"]}

        # Auto-merge: very high similarity
        if sim >= AUTO_MERGE_THRESHOLD:
            # Add as alias and merge
            new_aliases = list(set(aliases + [name]))
            entity_id = await db_find_or_create_entity(candidate["name"], entity_type, new_aliases, team_id=team_id)
            logger.info("Auto-merged '%s' into '%s' (sim=%.2f)", name, candidate["name"], sim)
            return {"action": "existing", "entity_id": entity_id, "merged_into": candidate["name"]}

        # LLM confirmation range
        if sim >= LLM_CONFIRM_THRESHOLD:
            result = await llm_confirm_entity_match(name, candidate)
            if result.get("same_entity") and result.get("confidence", 0) >= LLM_CONFIDENCE_THRESHOLD:
                new_aliases = list(set(aliases + [name]))
                entity_id = await db_find_or_create_entity(candidate["name"], entity_type, new_aliases, team_id=team_id)
                logger.info(
                    "LLM-confirmed merge '%s' into '%s' (sim=%.2f, llm_conf=%.2f, reason=%s)",
                    name, candidate["name"], sim, result["confidence"], result.get("reason"),
                )
                return {"action": "existing", "entity_id": entity_id, "merged_into": candidate["name"]}

    # No match — create new
    entity_id = await db_find_or_create_entity(name, entity_type, aliases, team_id=team_id)
    return {"action": "created", "entity_id": entity_id, "merged_into": None}


async def batch_deduplicate_entities(
    entities: list[dict[str, Any]],
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Batch dedup for imports. Groups by trigram candidate to minimize LLM calls.

    Each entity dict: {"name": str, "entity_type": str, "aliases": list[str]}
    Returns: list of {"name": str, "action": str, "entity_id": str, "merged_into": str|None}

    Per devil's advocate: if 50 imports all match "JPMorgan" variants,
    one LLM call confirms all 50 rather than 50 separate calls.
    """
    from app.db.knowledge_graph import db_find_similar_entities

    # First pass: collect all candidates
    entity_candidates: dict[int, list[dict]] = {}
    for i, ent in enumerate(entities):
        candidates = await db_find_similar_entities(
            ent["name"], team_id=team_id, threshold=LLM_CONFIRM_THRESHOLD,
        )
        entity_candidates[i] = candidates

    # Group entities by their top candidate (to batch LLM calls)
    candidate_groups: dict[str, list[int]] = {}  # candidate_id → [entity_indices]
    no_candidate: list[int] = []

    for i, candidates in entity_candidates.items():
        if not candidates:
            no_candidate.append(i)
            continue

        top = candidates[0]
        sim = top.get("similarity", 0)

        if sim >= AUTO_MERGE_THRESHOLD:
            # Will auto-merge, no LLM needed
            continue
        elif sim >= LLM_CONFIRM_THRESHOLD:
            cid = top["id"]
            candidate_groups.setdefault(cid, []).append(i)
        else:
            no_candidate.append(i)

    # Batch LLM calls: one per candidate group
    llm_confirmed: dict[str, bool] = {}  # candidate_id → confirmed
    for cid, indices in candidate_groups.items():
        # Use the first entity as representative for the LLM call
        representative = entities[indices[0]]
        candidate = entity_candidates[indices[0]][0]
        result = await llm_confirm_entity_match(representative["name"], candidate)
        llm_confirmed[cid] = (
            result.get("same_entity", False)
            and result.get("confidence", 0) >= LLM_CONFIDENCE_THRESHOLD
        )

    # Second pass: apply decisions
    results = []
    for i, ent in enumerate(entities):
        dedup_result = await deduplicate_entity(
            ent["name"], ent.get("entity_type", "other"),
            ent.get("aliases", []), team_id=team_id,
        )
        results.append({"name": ent["name"], **dedup_result})

    return results

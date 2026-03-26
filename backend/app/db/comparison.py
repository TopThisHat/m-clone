"""Entity comparison DB layer.

Provides a side-by-side comparison of 2-5 entities within a campaign,
returning a matrix where attributes are rows and entities are columns.
Each cell contains the latest validation result (present/confidence/evidence)
plus the entity's overall score in a header row.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from ._pool import _acquire

logger = logging.getLogger(__name__)


def _compute_attribute_highlights(
    entity_values: dict[str, dict[str, Any] | None],
) -> tuple[list[str], list[str]]:
    """Determine best and worst entity IDs for a single attribute.

    Ranking logic: present=true beats present=false; among equal presence,
    higher confidence wins. Entities with no result (None) are excluded.

    Returns:
        (best_entity_ids, worst_entity_ids) — may be empty if fewer than
        2 entities have results, or lists with multiple IDs on ties.
    """
    scored: list[tuple[str, int, float]] = []
    for eid, val in entity_values.items():
        if val is None:
            continue
        presence_rank = 1 if val.get("present") else 0
        confidence = val.get("confidence") if val.get("confidence") is not None else 0.0
        scored.append((eid, presence_rank, confidence))

    if len(scored) < 2:
        return [], []

    max_key = max(scored, key=lambda t: (t[1], t[2]))
    min_key = min(scored, key=lambda t: (t[1], t[2]))

    # If best == worst (all identical), no highlighting
    if (max_key[1], max_key[2]) == (min_key[1], min_key[2]):
        return [], []

    best = [eid for eid, pr, cf in scored if (pr, cf) == (max_key[1], max_key[2])]
    worst = [eid for eid, pr, cf in scored if (pr, cf) == (min_key[1], min_key[2])]
    return best, worst


def _compute_score_highlights(
    entities: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Determine best and worst entity IDs by total_score.

    Returns:
        (best_entity_ids, worst_entity_ids) — empty if fewer than 2 have scores
        or all scores are equal.
    """
    scored = [
        (e["id"], e["total_score"])
        for e in entities
        if e.get("total_score") is not None
    ]

    if len(scored) < 2:
        return [], []

    max_score = max(s for _, s in scored)
    min_score = min(s for _, s in scored)

    if max_score == min_score:
        return [], []

    best = [eid for eid, s in scored if s == max_score]
    worst = [eid for eid, s in scored if s == min_score]
    return best, worst


async def db_compare_entities(
    campaign_id: str,
    entity_ids: list[str],
) -> dict[str, Any]:
    """Compare 2-5 entities side-by-side within a campaign.

    Returns a structured comparison matrix:
    - ``entities``: list of entity info dicts (id, label, gwm_id, score)
    - ``attributes``: list of attribute dicts with per-entity values
    - ``summary``: aggregate counts

    Args:
        campaign_id: Campaign UUID.
        entity_ids: List of 2-5 entity UUID strings.

    Raises:
        HTTPException(400): if entity count is not between 2 and 5.
        HTTPException(404): if any entity is not found in the campaign.
    """
    if len(entity_ids) < 2 or len(entity_ids) > 5:
        raise HTTPException(
            status_code=400,
            detail=f"Comparison requires 2-5 entities, got {len(entity_ids)}.",
        )

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_ids: list[str] = []
    for eid in entity_ids:
        if eid not in seen:
            seen.add(eid)
            unique_ids.append(eid)

    if len(unique_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 distinct entity IDs are required for comparison.",
        )

    async with _acquire() as conn:
        async with conn.transaction(readonly=True):
            # 1. Fetch entity info + scores
            entity_rows = await conn.fetch(
                """
                SELECT e.id, e.label, e.gwm_id,
                       es.total_score, es.attributes_present, es.attributes_checked
                FROM playbook.entities e
                LEFT JOIN playbook.entity_scores es
                    ON es.entity_id = e.id AND es.campaign_id = $1::uuid
                WHERE e.campaign_id = $1::uuid
                  AND e.id = ANY($2::uuid[])
                ORDER BY array_position($2::uuid[], e.id)
                """,
                campaign_id,
                unique_ids,
            )

            if len(entity_rows) != len(unique_ids):
                found_ids = {str(r["id"]) for r in entity_rows}
                missing = [eid for eid in unique_ids if eid not in found_ids]
                raise HTTPException(
                    status_code=404,
                    detail=f"Entities not found in campaign: {missing}",
                )

            # 2. Fetch all attributes for the campaign
            attr_rows = await conn.fetch(
                """
                SELECT id, label, description, weight, attribute_type, category
                FROM playbook.attributes
                WHERE campaign_id = $1::uuid
                ORDER BY category NULLS LAST, label
                """,
                campaign_id,
            )

            # 3. Fetch latest validation results for the selected entities
            result_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (r.entity_id, r.attribute_id)
                       r.entity_id,
                       r.attribute_id,
                       r.present,
                       r.confidence,
                       r.evidence
                FROM playbook.validation_results r
                JOIN playbook.validation_jobs vj ON vj.id = r.job_id
                WHERE vj.campaign_id = $1::uuid
                  AND vj.status = 'done'
                  AND r.entity_id = ANY($2::uuid[])
                ORDER BY r.entity_id, r.attribute_id, r.created_at DESC
                """,
                campaign_id,
                unique_ids,
            )

    # Build a lookup: (entity_id, attribute_id) -> result dict
    result_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for r in result_rows:
        key = (str(r["entity_id"]), str(r["attribute_id"]))
        result_lookup[key] = {
            "present": r["present"],
            "confidence": float(r["confidence"])
            if r["confidence"] is not None
            else None,
            "evidence": r["evidence"],
        }

    # Build entity info list
    entities = []
    for r in entity_rows:
        entities.append(
            {
                "id": str(r["id"]),
                "label": r["label"],
                "gwm_id": r["gwm_id"],
                "total_score": float(r["total_score"])
                if r["total_score"] is not None
                else None,
                "attributes_present": r["attributes_present"],
                "attributes_checked": r["attributes_checked"],
            }
        )

    # Build attribute rows with per-entity values + best/worst highlighting
    attributes = []
    for a in attr_rows:
        attr_id = str(a["id"])
        entity_values: dict[str, dict[str, Any] | None] = {}
        for eid in unique_ids:
            entity_values[eid] = result_lookup.get((eid, attr_id))

        best_ids, worst_ids = _compute_attribute_highlights(entity_values)

        attributes.append(
            {
                "attribute_id": attr_id,
                "label": a["label"],
                "description": a["description"],
                "weight": float(a["weight"]) if a["weight"] is not None else 1.0,
                "attribute_type": a["attribute_type"] or "text",
                "category": a["category"],
                "entity_values": entity_values,
                "best_entity_ids": best_ids,
                "worst_entity_ids": worst_ids,
            }
        )

    # Compute score highlights across entities
    score_best, score_worst = _compute_score_highlights(entities)

    return {
        "campaign_id": campaign_id,
        "entities": entities,
        "attributes": attributes,
        "summary": {
            "entity_count": len(entities),
            "attribute_count": len(attributes),
        },
        "highlights": {
            "best_score_entity_ids": score_best,
            "worst_score_entity_ids": score_worst,
        },
    }

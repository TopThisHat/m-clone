"""
GPT-5.1 structured output to determine attribute presence from a research report.

Supports both single-attribute (legacy) and multi-attribute (clustered) verification.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

_LLM_SEM = asyncio.Semaphore(5)  # max 5 concurrent LLM calls

# Confidence threshold below which an attribute is flagged for potential
# individual re-research (per devil's advocate recommendation).
LOW_CONFIDENCE_THRESHOLD = 0.5


async def determine_presence(entity: dict, attribute: dict, report_md: str) -> dict:
    """
    Ask GPT-5.1 whether the entity possesses the attribute, based on the report.
    Returns: {"present": bool, "confidence": float, "evidence": str}

    LEGACY — kept for backward compat with validation_pair workflow.
    New code should use verify_attributes_from_report() instead.
    """
    prompt = f"""Entity: {entity['label']}
Attribute: {attribute['label']} — {attribute.get('description') or ''}
Research report:
{report_md[:6000]}
---
Based solely on the report, does this entity have the stated attribute?
Return JSON only: {{"present": true|false, "confidence": 0.0-1.0, "evidence": "quote or explanation"}}"""

    try:
        async with _LLM_SEM:
            resp = await get_openai_client().chat.completions.create(
                model="gpt-5.1",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_completion_tokens=300,
            )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.error(
            "determine_presence failed for entity=%s attribute=%s: %s",
            entity.get("label"), attribute.get("label"), exc,
        )
        return {"present": False, "confidence": 0.0, "evidence": f"Error: {exc}"}


async def verify_attributes_from_report(
    entity: dict,
    attributes: list[dict],
    report_md: str,
) -> list[dict]:
    """
    Given a research report, determine presence of ALL attributes at once.

    This is the cluster-aware replacement for determine_presence() — a single
    LLM call evaluates multiple related attributes from one research report,
    reducing API calls by the cluster size factor.

    Args:
        entity: {"label": str, ...}
        attributes: [{"id": str, "label": str, "description": str|None}, ...]
        report_md: Markdown research report

    Returns:
        List of {"present": bool, "confidence": float, "evidence": str}
        in the same order as the input attributes list. On error, returns
        default entries with present=False, confidence=0.
    """
    if not attributes:
        return []

    # Single attribute → delegate to simpler prompt for accuracy
    if len(attributes) == 1:
        result = await determine_presence(entity, attributes[0], report_md)
        return [result]

    attr_list = "\n".join(
        f"{i + 1}. {a['label']}: {a.get('description') or 'N/A'}"
        for i, a in enumerate(attributes)
    )

    prompt = f"""Entity: {entity['label']}

Based on the research report below, determine whether this entity has each of the following attributes.

Attributes to check:
{attr_list}

Research report:
{report_md[:8000]}

---
For EACH attribute (by number), return:
- present: true/false — does the report provide evidence that this entity has this attribute?
- confidence: 0.0-1.0 — how confident are you based on the available evidence?
- evidence: brief quote or explanation from the report supporting your judgment

Return JSON with a "results" array in the same order as the attributes above:
{{"results": [
    {{"attribute_number": 1, "present": true, "confidence": 0.85, "evidence": "..."}},
    {{"attribute_number": 2, "present": false, "confidence": 0.9, "evidence": "No mention found"}},
    ...
]}}"""

    try:
        async with _LLM_SEM:
            resp = await get_openai_client().chat.completions.create(
                model="gpt-5.1",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_completion_tokens=3000,
            )
        raw = json.loads(resp.choices[0].message.content)
        results_raw = raw.get("results", [])

        # Build result list aligned to input order
        results: list[dict] = []
        # Index by attribute_number for robustness (LLM may reorder)
        by_number = {r.get("attribute_number", i + 1): r for i, r in enumerate(results_raw)}

        for i in range(len(attributes)):
            entry = by_number.get(i + 1)
            if entry:
                results.append({
                    "present": bool(entry.get("present", False)),
                    "confidence": float(entry.get("confidence", 0.0)),
                    "evidence": str(entry.get("evidence", "")),
                })
            else:
                # LLM missed this attribute — mark as low confidence
                results.append({
                    "present": False,
                    "confidence": 0.0,
                    "evidence": "Attribute not evaluated by verification model",
                })

        low_conf_count = sum(1 for r in results if r["confidence"] < LOW_CONFIDENCE_THRESHOLD)
        if low_conf_count > len(attributes) / 2:
            logger.warning(
                "verify_attributes: %d/%d attributes below confidence threshold for entity=%s — "
                "cluster research question may need improvement",
                low_conf_count, len(attributes), entity.get("label"),
            )

        return results

    except Exception as exc:
        logger.error(
            "verify_attributes_from_report failed for entity=%s (%d attrs): %s",
            entity.get("label"), len(attributes), exc,
        )
        return [
            {"present": False, "confidence": 0.0, "evidence": f"Error: {exc}"}
            for _ in attributes
        ]

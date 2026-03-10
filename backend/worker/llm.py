"""
GPT-4o-mini structured output to determine attribute presence from a research report.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def determine_presence(entity: dict, attribute: dict, report_md: str) -> dict:
    """
    Ask GPT-4o-mini whether the entity possesses the attribute, based on the report.
    Returns: {"present": bool, "confidence": float, "evidence": str}
    """
    from openai import AsyncOpenAI

    prompt = f"""Entity: {entity['label']}
Attribute: {attribute['label']} — {attribute.get('description') or ''}
Research report:
{report_md[:6000]}
---
Based solely on the report, does this entity have the stated attribute?
Return JSON only: {{"present": true|false, "confidence": 0.0-1.0, "evidence": "quote or explanation"}}"""

    try:
        resp = await AsyncOpenAI().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.error(
            "determine_presence failed for entity=%s attribute=%s: %s",
            entity.get("label"), attribute.get("label"), exc,
        )
        return {"present": False, "confidence": 0.0, "evidence": f"Error: {exc}"}

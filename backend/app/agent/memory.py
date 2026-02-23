"""
Agent memory: extract named entities / key facts from research reports and store
them cross-session so future queries can benefit from prior research context.
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


async def extract_memories(session_id: str, query: str, report: str) -> None:
    """
    Call GPT-4o-mini to extract named entities + facts from a research report
    and save them to the agent_memory table. Non-blocking — failures are logged
    but not raised.
    """
    try:
        from app.db import get_pool, DatabaseNotConfigured
        pool = await get_pool()
    except Exception:
        return  # DB not configured or unavailable

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        prompt = (
            "Extract the most important named entities (companies, people, concepts, metrics) "
            "and key facts from the following research report. "
            "Return a JSON array of objects with keys: entity, entity_type (company|person|concept|metric), facts (array of short strings). "
            "Limit to the top 8 most significant entities. Return only the JSON array, no other text.\n\n"
            f"Query: {query}\n\nReport:\n{report[:6000]}"
        )
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0,
        )
        raw = resp.choices[0].message.content or "[]"
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        entities = json.loads(raw)
        if not isinstance(entities, list):
            return
    except Exception as exc:
        logger.warning("extract_memories failed: %s", exc)
        return

    try:
        async with pool.acquire() as conn:
            for ent in entities:
                entity = str(ent.get("entity", ""))[:255]
                entity_type = str(ent.get("entity_type", ""))[:50]
                facts = ent.get("facts", [])
                if not entity:
                    continue
                await conn.execute(
                    """
                    INSERT INTO agent_memory (session_id, entity, entity_type, facts)
                    VALUES ($1::uuid, $2, $3, $4::jsonb)
                    """,
                    session_id,
                    entity,
                    entity_type,
                    json.dumps(facts),
                )
    except Exception as exc:
        logger.warning("extract_memories DB write failed: %s", exc)


async def retrieve_memories(query: str, limit: int = 5) -> str:
    """
    Fetch rows from agent_memory where query keywords overlap entity names.
    Returns a formatted context string or "" if none found / DB not configured.
    """
    try:
        from app.db import get_pool, DatabaseNotConfigured
        pool = await get_pool()
    except Exception:
        return ""

    try:
        keywords = [w.lower() for w in query.split() if len(w) > 3]
        if not keywords:
            return ""

        # Build a simple OR search over entity names
        conditions = " OR ".join(f"lower(entity) LIKE ${i+1}" for i in range(len(keywords)))
        params = [f"%{kw}%" for kw in keywords]
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT entity, entity_type, facts
                FROM agent_memory
                WHERE {conditions}
                ORDER BY created_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )
    except Exception as exc:
        logger.warning("retrieve_memories failed: %s", exc)
        return ""

    if not rows:
        return ""

    lines = ["Prior research context:"]
    seen: set[str] = set()
    for row in rows:
        key = row["entity"].lower()
        if key in seen:
            continue
        seen.add(key)
        facts = row["facts"] if isinstance(row["facts"], list) else json.loads(row["facts"] or "[]")
        facts_str = "; ".join(str(f) for f in facts[:3])
        label = f"  - {row['entity']}"
        if row["entity_type"]:
            label += f" ({row['entity_type']})"
        if facts_str:
            label += f": {facts_str}"
        lines.append(label)

    return "\n".join(lines)

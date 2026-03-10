"""
Wraps stream_research() to return final report markdown.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def run_research(query: str) -> str:
    """Run the research agent and return the final report markdown."""
    from app.agent.streaming import stream_research
    from app.dependencies import get_agent_deps

    deps = get_agent_deps(depth="balanced")
    markdown = ""
    current_event = ""

    try:
        async for chunk in stream_research(query=query, deps=deps):
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event == "final_report":
                    try:
                        payload = json.loads(line[6:])
                        markdown = payload.get("markdown", "")
                    except Exception:
                        pass
    except Exception as exc:
        logger.error("run_research failed for query '%s': %s", query[:80], exc)

    return markdown

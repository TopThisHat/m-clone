"""KG Chat Orchestrator — drives LLM tool-calling against the knowledge graph.

Follows the ResearchOrchestrator pattern in agent.py.
Yields structured events for SSE streaming.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.agent.kg_ontology import get_lm_prompt_section
from app.agent.kg_tools import KG_TOOL_SCHEMAS, execute_kg_tool
from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

# Maximum tool calls allowed per LLM turn
MAX_TOOL_CALLS_PER_TURN = 6

# Preferred model; fall back to gpt-4o if gpt-4.1 not available
_PREFERRED_MODEL = "gpt-4.1"
_FALLBACK_MODEL = "gpt-4o"

_KG_SYSTEM_PROMPT_BASE = """You are an expert Knowledge Graph analyst. You have access to a structured
knowledge graph containing entities and their relationships. Your job is to answer user questions
about the graph by calling the provided tools and synthesizing clear, accurate answers.

## Available tools
- **search_kg_entities** — Find entities by name using fuzzy matching
- **get_entity_relationships** — Explore an entity's connections (filter by family/direction)
- **find_connections** — Discover paths between two entities (BFS, up to 5 hops)
- **aggregate_kg** — Run pre-defined analyses (entity counts, most connected, etc.)
- **get_entity_details** — Get full details for specific entities by UUID
- **explore_neighborhood** — Map the local graph around an entity

## Guidelines
- Call tools to gather facts before answering. Do NOT guess or hallucinate entity names or IDs.
- When you find entity UUIDs in results, pass them to entity-detail tools for richer context.
- For path queries, use find_connections. For neighborhood explorations, use explore_neighborhood.
- Summarize tool results in clear natural language. Include entity names, not just UUIDs.
- Maximum {max_calls} tool calls per response turn.
- If the graph has no relevant data, say so clearly rather than speculating.
""".format(max_calls=MAX_TOOL_CALLS_PER_TURN)


def _build_system_prompt() -> str:
    """Combine base prompt with live ontology section."""
    return _KG_SYSTEM_PROMPT_BASE.strip() + "\n\n" + get_lm_prompt_section()


# ── Event types ───────────────────────────────────────────────────────────────

@dataclass
class KGTextDelta:
    token: str


@dataclass
class KGToolCallStart:
    call_id: str
    name: str
    arguments_json: str


@dataclass
class KGToolResult:
    call_id: str
    name: str
    content: str


@dataclass
class KGHighlight:
    """Emitted when tool results contain entity UUIDs to highlight in the graph."""
    entity_ids: list[str]


@dataclass
class KGPath:
    """Emitted when find_connections returns path data for graph rendering."""
    paths: list[dict[str, Any]]
    source_id: str
    target_id: str


@dataclass
class KGFinalResult:
    text: str
    messages: list[dict[str, Any]]


KGChatEvent = KGTextDelta | KGToolCallStart | KGToolResult | KGHighlight | KGPath | KGFinalResult


def _extract_entity_ids_from_result(content: str, tool_name: str) -> list[str]:
    """Pull entity UUIDs out of a JSON tool result for graph highlighting."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []

    ids: list[str] = []

    if tool_name == "search_kg_entities":
        ids = [item["id"] for item in data if isinstance(item, dict) and "id" in item]
    elif tool_name == "get_entity_relationships":
        entity = data.get("entity") or {}
        if entity.get("id"):
            ids.append(entity["id"])
        for r in data.get("relationships", []):
            if r.get("subject_id"):
                ids.append(r["subject_id"])
            if r.get("object_id"):
                ids.append(r["object_id"])
    elif tool_name == "get_entity_details":
        ids = [item["id"] for item in data if isinstance(item, dict) and "id" in item]
    elif tool_name == "explore_neighborhood":
        ids = [n["id"] for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n]
    elif tool_name == "aggregate_kg":
        # most_connected returns entities with ids
        for item in data.get("results", []):
            if isinstance(item, dict) and "id" in item:
                ids.append(item["id"])
    elif tool_name == "find_connections":
        for path in data.get("paths", []):
            for entity in path.get("entities", []):
                if isinstance(entity, dict) and "id" in entity:
                    ids.append(entity["id"])

    return list(dict.fromkeys(ids))  # deduplicate preserving order


def _extract_paths_from_result(content: str) -> tuple[list[dict[str, Any]], str, str] | None:
    """Extract path data from a find_connections result for KGPath events."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None
    paths = data.get("paths")
    if not paths:
        return None
    return paths, data.get("source_id", ""), data.get("target_id", "")


# ── Fallback keyword search ───────────────────────────────────────────────────

async def _fallback_keyword_search(query: str, team_id: str) -> str:
    """Fall back to db_query_kg keyword search when the LLM pipeline fails.

    Returns a formatted string result to stream back to the user.
    """
    try:
        from app.db.knowledge_graph import db_query_kg
        result = await db_query_kg(query=query, team_id=team_id)
        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        if not entities and not relationships:
            return (
                "I couldn't process that as a conversation, but keyword search also "
                f"found no results for '{query}' in the knowledge graph."
            )
        lines = [
            "I couldn't process that as a conversation, but here's what I found by keyword search:\n"
        ]
        if entities:
            lines.append(f"**Entities ({len(entities)}):**")
            for e in entities[:10]:
                lines.append(f"- {e.get('name', '?')} ({e.get('entity_type', '?')})")
        if relationships:
            lines.append(f"\n**Relationships ({len(relationships)}):**")
            for r in relationships[:5]:
                lines.append(
                    f"- {r.get('subject_name', '?')} → {r.get('predicate', '?')} → {r.get('object_name', '?')}"
                )
        return "\n".join(lines)
    except Exception:
        logger.exception("Fallback keyword search failed for team %s", team_id)
        return ""


# ── Orchestrator ──────────────────────────────────────────────────────────────

class KGChatOrchestrator:
    """Drives LLM tool-calling against the KG, yielding KGChatEvent items.

    Follows the same pattern as ResearchOrchestrator in agent.py:
      1. Build messages (system + history + user message)
      2. Stream completions with tool schemas
      3. Execute tools, emit events, loop until no more tool calls
      4. Yield KGFinalResult
    """

    def __init__(self, model: str | None = None) -> None:
        self.client: AsyncOpenAI = get_openai_client()
        raw = model or _PREFERRED_MODEL
        # Strip provider prefix (e.g. "openai:gpt-4.1" → "gpt-4.1")
        self.model = raw.split(":", 1)[-1] if ":" in raw else raw

    async def run(
        self,
        message: str,
        team_id: str,
        message_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[KGChatEvent]:
        """Run one chat turn, streaming events back to the caller."""
        system_prompt = _build_system_prompt()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        if message_history:
            messages.extend(message_history[-40:])  # keep last 40 messages for context
        messages.append({"role": "user", "content": message})

        accumulated_text = ""
        tool_call_count = 0

        try:
            while tool_call_count < MAX_TOOL_CALLS_PER_TURN:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=KG_TOOL_SCHEMAS,
                    parallel_tool_calls=True,
                    stream=True,
                )

                turn_text = ""
                tool_calls_acc: dict[int, dict[str, str]] = {}

                async for chunk in stream:
                    for choice in chunk.choices:
                        delta = choice.delta
                        if delta is None:
                            continue
                        if delta.content:
                            turn_text += delta.content
                            accumulated_text += delta.content
                            yield KGTextDelta(token=delta.content)
                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                                if tc_delta.id:
                                    tool_calls_acc[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        tool_calls_acc[idx]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                if not tool_calls_acc:
                    # No more tool calls — done
                    break

                # Append assistant message with tool_calls
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn_text or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
                    ],
                }
                messages.append(assistant_msg)

                sorted_tcs = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]

                # Yield ToolCallStart events
                for tc in sorted_tcs:
                    yield KGToolCallStart(
                        call_id=tc["id"],
                        name=tc["name"],
                        arguments_json=tc["arguments"],
                    )

                # Execute tools in parallel when multiple
                parsed_args = []
                for tc in sorted_tcs:
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    parsed_args.append(args)

                if len(sorted_tcs) == 1:
                    results = [
                        await execute_kg_tool(sorted_tcs[0]["name"], parsed_args[0], team_id)
                    ]
                else:
                    results = list(await asyncio.gather(
                        *(execute_kg_tool(tc["name"], a, team_id)
                          for tc, a in zip(sorted_tcs, parsed_args))
                    ))

                # Yield results, highlight events, path events
                for tc, result_content in zip(sorted_tcs, results):
                    yield KGToolResult(
                        call_id=tc["id"],
                        name=tc["name"],
                        content=result_content,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_content,
                    })

                    # Emit graph highlight event for entity IDs
                    entity_ids = _extract_entity_ids_from_result(result_content, tc["name"])
                    if entity_ids:
                        yield KGHighlight(entity_ids=entity_ids)

                    # Emit path event for find_connections results
                    if tc["name"] == "find_connections":
                        path_data = _extract_paths_from_result(result_content)
                        if path_data:
                            paths, source_id, target_id = path_data
                            yield KGPath(paths=paths, source_id=source_id, target_id=target_id)

                tool_call_count += len(sorted_tcs)
                if tool_call_count >= MAX_TOOL_CALLS_PER_TURN and tool_calls_acc:
                    # Tool call limit reached — emit partial result notice and stop
                    notice = (
                        "\n\n*This query required more analysis steps than allowed. "
                        "The results above are partial. Try a more specific question.*"
                    )
                    accumulated_text += notice
                    yield KGTextDelta(token=notice)
                    break

        except Exception as exc:
            logger.exception("KGChatOrchestrator error for team %s", team_id)
            # Graceful fallback: keyword search via db_query_kg
            fallback_text = await _fallback_keyword_search(message, team_id)
            if fallback_text:
                accumulated_text = fallback_text
                yield KGTextDelta(token=fallback_text)
            else:
                yield KGTextDelta(token=f"\n\n[Unable to process request: {exc}]")

        yield KGFinalResult(text=accumulated_text, messages=messages)

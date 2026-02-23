import asyncio
import json
import re
from typing import Any, AsyncIterator

from pydantic import TypeAdapter
from pydantic_ai import Agent, FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import ModelMessage, TextPart, TextPartDelta, ToolCallPart
from pydantic_graph import End

from app.agent.agent import research_agent
from app.dependencies import AgentDeps

_messages_adapter = TypeAdapter(list[ModelMessage])

_MAX_HISTORY_MESSAGES = 60


def _trim_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    if len(messages) <= _MAX_HISTORY_MESSAGES:
        return messages

    serialized = _messages_adapter.dump_python(messages, mode="json")
    target = len(messages) - _MAX_HISTORY_MESSAGES

    for i in range(target, len(serialized)):
        msg = serialized[i]
        if msg.get("kind") == "request" and any(
            p.get("part_kind") == "user-prompt" for p in msg.get("parts", [])
        ):
            return messages[i:]

    return messages[target:]


TOOL_METADATA: dict[str, dict[str, str]] = {
    "web_search": {"label": "Web Search", "icon": "search"},
    "tavily_search": {"label": "Web Search", "icon": "search"},
    "wiki_lookup": {"label": "Wikipedia", "icon": "book"},
    "get_financials": {"label": "Financial Data", "icon": "chart"},
    "search_uploaded_documents": {"label": "Documents", "icon": "document"},
    "create_research_plan": {"label": "Research Plan", "icon": "plan"},
    "evaluate_research_completeness": {"label": "Evaluation", "icon": "evaluate"},
    "sec_edgar_search": {"label": "SEC Filing", "icon": "document"},
}


def _sse(event_type: str, data: dict) -> str:
    """Format a single SSE message in standard wire format."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _detect_conflicts(source_claims: dict[str, list[str]]) -> list[str]:
    """
    Detect conflicting numeric claims across sources.
    Groups values by rough magnitude and flags >25% variance.
    """
    if len(source_claims) < 2:
        return []

    # Flatten all claims with their source URL
    all_claims: list[tuple[str, float]] = []
    for url, claims in source_claims.items():
        for claim in claims:
            # Normalise to a float
            raw = re.sub(r'[,$%]', '', claim)
            mult = 1.0
            if raw.upper().endswith('T'):
                mult = 1e12
                raw = raw[:-1]
            elif raw.upper().endswith('B'):
                mult = 1e9
                raw = raw[:-1]
            elif raw.upper().endswith('M'):
                mult = 1e6
                raw = raw[:-1]
            elif raw.upper().endswith('K'):
                mult = 1e3
                raw = raw[:-1]
            try:
                all_claims.append((url, float(raw) * mult))
            except ValueError:
                pass

    if len(all_claims) < 2:
        return []

    # Simple variance check: compare any two values
    warnings: list[str] = []
    values = [v for _, v in all_claims]
    min_v, max_v = min(values), max(values)
    if min_v > 0 and (max_v - min_v) / min_v > 0.25:
        sources = list({url for url, _ in all_claims[:4]})
        domain_a = re.sub(r'^https?://(www\.)?', '', sources[0]).split('/')[0] if sources else 'Source A'
        domain_b = re.sub(r'^https?://(www\.)?', '', sources[1]).split('/')[0] if len(sources) > 1 else 'Source B'
        warnings.append(
            f"Numeric figures vary significantly across sources: "
            f"{_fmt(min_v)} ({domain_b}) vs {_fmt(max_v)} ({domain_a})"
        )
    return warnings


def _fmt(v: float) -> str:
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"{v:.2f}"


async def stream_research(
    query: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Core SSE generator. Drives agent.iter() node by node, emitting structured
    SSE events for tool calls, results, text tokens, and the final report.
    """
    yield _sse("start", {"message": "Research initiated", "query": query})

    # Emit memory context at the start if available
    if deps.memory_context:
        yield _sse("memory_context", {"context": deps.memory_context})

    accumulated_text = ""
    # Track which tool calls produced chart payloads (by call_id)
    _pending_chart_call_ids: set[str] = set()

    prior: list[ModelMessage] | None = None
    if message_history:
        try:
            prior = _messages_adapter.validate_python(message_history)
            prior = _trim_history(prior)
            query = f"[FOLLOW-UP] {query}"
        except Exception:
            prior = None

    try:
        async with research_agent.iter(
            query, deps=deps, message_history=prior
        ) as agent_run:
            async for node in agent_run:

                # ── Model generating tokens / deciding on tool calls ──────────
                if Agent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as agent_stream:
                        async for event in agent_stream:
                            kind = getattr(event, "event_kind", None)

                            if kind == "part_start":
                                part = event.part
                                if isinstance(part, ToolCallPart):
                                    meta = TOOL_METADATA.get(
                                        part.tool_name,
                                        {"label": part.tool_name, "icon": "tool"},
                                    )
                                    yield _sse("tool_call_start", {
                                        "tool_name": part.tool_name,
                                        "tool_label": meta["label"],
                                        "icon": meta["icon"],
                                        "call_id": part.tool_call_id,
                                    })
                                elif isinstance(part, TextPart):
                                    yield _sse("reasoning_start", {"index": event.index})

                            elif kind == "part_delta":
                                delta = event.delta
                                if isinstance(delta, TextPartDelta) and delta.content_delta:
                                    accumulated_text += delta.content_delta
                                    yield _sse("text_delta", {"token": delta.content_delta})

                # ── Tool execution ────────────────────────────────────────────
                elif Agent.is_call_tools_node(node):
                    async with node.stream(agent_run.ctx) as tools_stream:
                        async for event in tools_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                meta = TOOL_METADATA.get(
                                    event.part.tool_name,
                                    {"label": event.part.tool_name, "icon": "tool"},
                                )
                                try:
                                    args = (
                                        json.loads(event.part.args)
                                        if isinstance(event.part.args, str)
                                        else event.part.args or {}
                                    )
                                except Exception:
                                    args = str(event.part.args)

                                # Mark get_financials calls so we can emit chart_data
                                if event.part.tool_name == "get_financials":
                                    _pending_chart_call_ids.add(event.tool_call_id)

                                yield _sse("tool_executing", {
                                    "tool_name": event.part.tool_name,
                                    "tool_label": meta["label"],
                                    "icon": meta["icon"],
                                    "call_id": event.tool_call_id,
                                    "args": args,
                                })

                            elif isinstance(event, FunctionToolResultEvent):
                                content = str(event.result.content)
                                preview = content[:400] + "..." if len(content) > 400 else content
                                yield _sse("tool_result", {
                                    "call_id": event.tool_call_id,
                                    "preview": preview,
                                })

                                # Emit chart_data if this was a get_financials call
                                if event.tool_call_id in _pending_chart_call_ids and deps.chart_payloads:
                                    _pending_chart_call_ids.discard(event.tool_call_id)
                                    yield _sse("chart_data", {"chart": deps.chart_payloads[-1]})

                # ── End node ──────────────────────────────────────────────────
                elif isinstance(node, End):
                    pass

            # Collect final output and usage after loop completes
            result = agent_run.result
            if result is not None:
                final_text = str(result.output) if result.output is not None else accumulated_text
            else:
                final_text = accumulated_text

            usage_data: dict = {}
            try:
                usage = agent_run.usage()
                usage_data = {
                    "request_tokens": usage.request_tokens,
                    "response_tokens": usage.response_tokens,
                    "total_tokens": usage.total_tokens,
                }
            except Exception:
                pass

            # Save token usage to DB (non-blocking)
            if session_id and usage_data.get("total_tokens"):
                try:
                    from app.db import db_update_session
                    asyncio.create_task(
                        db_update_session(session_id, {"usage_tokens": usage_data["total_tokens"]})
                    )
                except Exception:
                    pass

            try:
                all_messages = _messages_adapter.dump_python(
                    agent_run.result.all_messages(), mode="json"
                ) if agent_run.result is not None else []
            except Exception:
                all_messages = []

            cited_urls = re.findall(r'\[.*?\]\((https?://[^)]+)\)', final_text)
            citation_warnings: list[str] = []
            if cited_urls:
                unknown = [
                    u for u in cited_urls
                    if not any(
                        known in u or u.startswith(known)
                        for known in deps.source_urls
                    )
                ]
                if len(unknown) / len(cited_urls) > 0.3:
                    citation_warnings = unknown[:5]

            # Detect conflicting sources
            conflict_warnings = _detect_conflicts(deps.source_claims)
            if conflict_warnings:
                yield _sse("conflict_warning", {"warnings": conflict_warnings})

            yield _sse("final_report", {
                "markdown": final_text,
                "usage": usage_data,
                "messages": all_messages,
                "citation_warnings": citation_warnings,
                "conflict_warnings": conflict_warnings,
            })

            # Trigger memory extraction non-blocking
            if session_id and final_text:
                try:
                    from app.agent.memory import extract_memories
                    original_query = query.removeprefix("[FOLLOW-UP] ")
                    asyncio.create_task(extract_memories(session_id, original_query, final_text))
                except Exception:
                    pass

    except Exception as exc:
        yield _sse("error", {"message": str(exc)})

    yield _sse("done", {"message": "Research complete"})

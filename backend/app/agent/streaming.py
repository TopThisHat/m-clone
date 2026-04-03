import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from app.agent.agent import (
    FinalResult,
    ResearchOrchestrator,
    TextDelta,
    ToolCallStart,
    ToolResult,
)
from app.agent.clarification import clarification_store
from app.dependencies import AgentDeps

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 60

# Token batching configuration — target ~30 fps for smooth typing UX
TEXT_DELTA_BATCH_SIZE_CHARS: int = 30
TEXT_DELTA_FLUSH_INTERVAL_MS: int = 33


class TextDeltaBatcher:
    """Batches text_delta tokens to reduce SSE event frequency.

    Instead of emitting one SSE event per LLM token (50-100+/sec), this
    accumulates tokens and flushes when either the character threshold or
    the time interval is reached — whichever comes first.
    """

    def __init__(
        self,
        batch_size_chars: int = TEXT_DELTA_BATCH_SIZE_CHARS,
        flush_interval_ms: int = TEXT_DELTA_FLUSH_INTERVAL_MS,
    ) -> None:
        self._buffer: str = ""
        self._batch_size: int = batch_size_chars
        self._flush_interval: float = flush_interval_ms / 1000.0
        self._last_flush: float = 0.0

    def add(self, text: str) -> str | None:
        """Add text to buffer. Returns flushed text if batch is ready, else None."""
        self._buffer += text
        now = asyncio.get_running_loop().time()

        if (
            len(self._buffer) >= self._batch_size
            or (now - self._last_flush) >= self._flush_interval
        ):
            return self.flush()
        return None

    def flush(self) -> str | None:
        """Force flush the buffer. Returns buffered text or None if empty."""
        if not self._buffer:
            return None
        text = self._buffer
        self._buffer = ""
        self._last_flush = asyncio.get_running_loop().time()
        return text

# NOTE: Keep in sync with TOOL_REGISTRY in tools.py when adding/removing tools.
TOOL_METADATA: dict[str, dict[str, str]] = {
    "web_search": {"label": "Web Search", "icon": "search"},
    "wiki_lookup": {"label": "Wikipedia", "icon": "book"},
    "get_financials": {"label": "Financial Data", "icon": "chart"},
    "search_uploaded_documents": {"label": "Documents", "icon": "document"},
    "create_research_plan": {"label": "Research Plan", "icon": "plan"},
    "evaluate_research_completeness": {"label": "Evaluation", "icon": "evaluate"},
    "sec_edgar_search": {"label": "SEC Filing", "icon": "document"},
    "ask_clarification": {"label": "Clarification Needed", "icon": "tool"},
    "query_knowledge_graph": {"label": "Knowledge Graph", "icon": "graph"},
    "lookup_client": {"label": "Client Lookup", "icon": "person"},
    "batch_lookup_clients": {"label": "Batch Client Lookup", "icon": "people"},
    "extract_and_lookup_entities": {"label": "Entity Extraction", "icon": "extract"},
    "talk_to_me": {"label": "Client Interactions", "icon": "chat"},
    # Sprint 3 tools (placeholders — implementations coming in Sprint 3)
    "create_execution_plan": {"label": "Execution Plan", "icon": "plan"},
    "report_progress": {"label": "Progress", "icon": "progress"},
    "submit_batch_job": {"label": "Batch Job", "icon": "batch"},
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

    all_claims: list[tuple[str, float]] = []
    for url, claims in source_claims.items():
        for claim in claims:
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


def _convert_legacy_history(message_history: list[Any]) -> list[dict[str, Any]] | None:
    """
    Convert pydantic-ai message format to OpenAI chat format for backward
    compatibility with sessions that were saved under the old agent.
    Returns None if conversion fails.
    """
    try:
        result: list[dict[str, Any]] = []
        for msg in message_history:
            kind = msg.get("kind") if isinstance(msg, dict) else None
            if kind == "request":
                # Extract user prompt parts
                for part in msg.get("parts", []):
                    pk = part.get("part_kind")
                    if pk == "user-prompt":
                        result.append({"role": "user", "content": part.get("content", "")})
                    elif pk == "tool-return":
                        result.append({
                            "role": "tool",
                            "tool_call_id": part.get("tool_call_id", ""),
                            "content": str(part.get("content", "")),
                        })
            elif kind == "response":
                for part in msg.get("parts", []):
                    pk = part.get("part_kind")
                    if pk == "text":
                        result.append({"role": "assistant", "content": part.get("content", "")})
                    elif pk == "tool-call":
                        result.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": part.get("tool_call_id", ""),
                                "type": "function",
                                "function": {
                                    "name": part.get("tool_name", ""),
                                    "arguments": json.dumps(part.get("args", {})) if isinstance(part.get("args"), dict) else str(part.get("args", "{}")),
                                },
                            }],
                        })
            elif isinstance(msg, dict) and msg.get("role"):
                # Already in OpenAI format
                result.append(msg)
        return result if result else None
    except Exception:
        logger.debug("Failed to convert legacy message history (%d messages)", len(message_history), exc_info=True)
        return None


async def stream_research(
    query: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
    session_id: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """
    Core SSE generator. Drives ResearchOrchestrator, emitting structured
    SSE events for tool calls, results, text tokens, and the final report.
    """
    yield _sse("start", {"message": "Research initiated", "query": query})

    if deps.memory_context:
        yield _sse("memory_context", {"context": deps.memory_context})

    accumulated_text = ""
    _pending_chart_tool_names: set[str] = set()
    batcher = TextDeltaBatcher()

    prior: list[dict[str, Any]] | None = None
    if message_history:
        # Try native OpenAI format first, then legacy pydantic-ai format
        if message_history and isinstance(message_history[0], dict) and message_history[0].get("role"):
            prior = message_history
        else:
            prior = _convert_legacy_history(message_history)
        if prior:
            if len(prior) > _MAX_HISTORY_MESSAGES:
                prior = prior[-_MAX_HISTORY_MESSAGES:]
            query = f"[FOLLOW-UP] {query}"

    try:
        orchestrator = ResearchOrchestrator(model=model)

        async for event in orchestrator.run(query, deps, message_history=prior):

            # ── Text token ────────────────────────────────────────────
            if isinstance(event, TextDelta):
                accumulated_text += event.token
                batched = batcher.add(event.token)
                if batched is not None:
                    yield _sse("text_delta", {"token": batched})

            # ── Tool call starting ────────────────────────────────────
            elif isinstance(event, ToolCallStart):
                # Flush buffered text before tool call so UI displays it first
                remaining = batcher.flush()
                if remaining is not None:
                    yield _sse("text_delta", {"token": remaining})
                meta = TOOL_METADATA.get(
                    event.name, {"label": event.name, "icon": "tool"},
                )

                try:
                    args = json.loads(event.arguments_json) if event.arguments_json else {}
                except Exception:
                    logger.debug("Failed to parse arguments_json for tool %s (call_id=%s): %s", event.name, event.call_id, event.arguments_json, exc_info=True)
                    args = event.arguments_json

                # Agent-level clarification: register Future before tool body runs
                if event.name == "ask_clarification":
                    clarification_id = event.call_id
                    question = args.get("question", "") if isinstance(args, dict) else str(args)
                    context = args.get("context") if isinstance(args, dict) else None
                    options = args.get("options") or []

                    clarification_store.register(
                        clarification_id=clarification_id,
                        question=question,
                        context=context,
                        options=options,
                    )
                    deps.pending_clarification_id = clarification_id
                    deps.active_clarification_ids.append(clarification_id)

                    yield _sse("clarification_needed", {
                        "clarification_id": clarification_id,
                        "question": question,
                        "context": context,
                        "options": options,
                    })

                # Mark get_financials calls so we can emit chart_data
                if event.name == "get_financials":
                    _pending_chart_tool_names.add(event.call_id)

                yield _sse("tool_call_start", {
                    "tool_name": event.name,
                    "tool_label": meta["label"],
                    "icon": meta["icon"],
                    "call_id": event.call_id,
                    "args": args,
                    "status": "executing",
                })

                # Drain any mid-tool SSE signals
                while not deps.tool_sse_queue.empty():
                    yield deps.tool_sse_queue.get_nowait()

            # ── Tool result ───────────────────────────────────────────
            elif isinstance(event, ToolResult):
                content = event.content
                preview = content[:400] + "..." if len(content) > 400 else content

                # Emit clarification_answered for agent-level path
                if content.startswith("User clarification:"):
                    answer_text = content.removeprefix("User clarification: ")
                    yield _sse("clarification_answered", {
                        "clarification_id": event.call_id,
                        "answer": answer_text,
                    })

                yield _sse("tool_result", {
                    "call_id": event.call_id,
                    "preview": preview,
                })

                # Emit chart_data if this was a get_financials call
                if event.call_id in _pending_chart_tool_names and deps.chart_payloads:
                    _pending_chart_tool_names.discard(event.call_id)
                    chart_payload = deps.chart_payloads[-1]
                    yield _sse("chart_data", {"chart": chart_payload})
                    ticker = chart_payload.get("ticker", "") if isinstance(chart_payload, dict) else ""
                    yield _sse("chart_trace", {"ticker": ticker, "payload": chart_payload})

                # Drain SSE queue after each processed event
                while not deps.tool_sse_queue.empty():
                    yield deps.tool_sse_queue.get_nowait()

            # ── Final result ──────────────────────────────────────────
            elif isinstance(event, FinalResult):
                # Flush any remaining buffered text before emitting the report
                remaining = batcher.flush()
                if remaining is not None:
                    yield _sse("text_delta", {"token": remaining})
                final_text = event.text or accumulated_text
                usage_data = event.usage
                all_messages = event.messages

                # Save token usage to DB (non-blocking)
                if session_id and usage_data.get("total_tokens"):
                    try:
                        from app.db import db_update_session
                        asyncio.create_task(
                            db_update_session(session_id, {"usage_tokens": usage_data["total_tokens"]})
                        )
                    except Exception:
                        logger.warning("Failed to save token usage for session %s", session_id, exc_info=True)

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

                conflict_warnings = _detect_conflicts(deps.source_claims)
                if conflict_warnings:
                    yield _sse("conflict_warning", {"warnings": conflict_warnings})

                sources = [
                    {
                        "url": url,
                        "title": deps.source_titles.get(url, url),
                        "domain": urlparse(url).netloc,
                    }
                    for url in sorted(deps.source_urls)
                ]

                yield _sse("final_report", {
                    "markdown": final_text,
                    "usage": usage_data,
                    "messages": all_messages,
                    "citation_warnings": citation_warnings,
                    "conflict_warnings": conflict_warnings,
                    "sources": sources,
                })

                # Emit AI-generated follow-up suggestions
                try:
                    from app.agent.memory import generate_suggestions
                    original_query = query.removeprefix("[FOLLOW-UP] ")
                    suggestions = await generate_suggestions(original_query, final_text)
                    if suggestions:
                        yield _sse("suggestions", {"suggestions": suggestions})
                except Exception:
                    logger.warning("Failed to generate follow-up suggestions for research stream", exc_info=True)

                # Trigger memory extraction non-blocking
                if session_id and final_text:
                    try:
                        from app.agent.memory import extract_memories
                        original_query = query.removeprefix("[FOLLOW-UP] ")
                        asyncio.create_task(extract_memories(session_id, original_query, final_text))
                    except Exception:
                        logger.warning("Failed to trigger memory extraction for session %s", session_id, exc_info=True)

                # Publish report to knowledge graph extraction pipeline
                if session_id and final_text:
                    try:
                        from app.streams import publish_for_extraction
                        asyncio.create_task(publish_for_extraction(session_id, final_text))
                    except Exception:
                        logger.warning("Failed to publish report to knowledge graph extraction for session %s", session_id, exc_info=True)

    except Exception as exc:
        # Flush buffered text before emitting the error
        remaining = batcher.flush()
        if remaining is not None:
            yield _sse("text_delta", {"token": remaining})
        yield _sse("error", {"message": str(exc)})
    finally:
        if deps.active_clarification_ids:
            clarification_store.cancel_session(deps.active_clarification_ids, reason="stream_closed")

    yield _sse("done", {"message": "Research complete"})


async def stream_agent(
    query: str,
    deps: AgentDeps,
    message_history: list[Any] | None = None,
    session_id: str | None = None,
    model: str | None = None,
    execution_mode: str | None = None,
) -> AsyncIterator[str]:
    """Mode-aware SSE generator — v2 entry point with classification routing.

    When execution_mode is None, delegates to stream_research() for backward
    compatibility. When "auto" or a specific mode, classifies and routes.
    """
    # If no mode specified, use legacy path
    if execution_mode is None:
        async for event in stream_research(query, deps, message_history, session_id, model):
            yield event
        return

    from app.agent.classifier import ClassificationError, classify_query
    from app.agent.prompts import build_system_prompt
    from app.agent.runner_config import ExecutionMode, RUNNER_CONFIGS
    from app.agent.tools import (
        _BATCH_JOB_MARKER,
        _PROGRESS_MARKER,
        execute_tool,
        get_tools_for_mode,
        normalize_history_for_mode,
    )

    yield _sse("start", {"message": "Request initiated", "query": query})

    if deps.memory_context:
        yield _sse("memory_context", {"context": deps.memory_context})

    # --- Step 1: Classify ---
    try:
        classification = await classify_query(
            query=query,
            has_documents=bool(deps.uploaded_doc_metadata),
            doc_metadata=deps.uploaded_doc_metadata or None,
            is_followup=bool(message_history),
            execution_mode_override=execution_mode if execution_mode != "auto" else None,
        )
    except ClassificationError as exc:
        yield _sse("error", {"message": f"Classification failed: {exc}"})
        yield _sse("done", {"message": "Request failed"})
        return

    # --- Step 2: Emit classification event ---
    yield _sse("classification", {
        "mode": classification.mode.value,
        "reasoning": classification.reasoning,
        "estimated_steps": classification.estimated_steps,
        "batch_size": classification.batch_size,
        "warning": classification.confidence < 0.7,
    })

    # --- Step 3: Get runner config ---
    config = RUNNER_CONFIGS[classification.mode]

    # --- Step 4: For FORMAT_ONLY, skip tools entirely ---
    # FORMAT_ONLY has max_tool_calls=0 so the tool loop below will never
    # execute — the model produces text in its first response and exits.

    # --- Step 5: Normalize history ---
    prior: list[dict[str, Any]] | None = None
    if message_history:
        if message_history and isinstance(message_history[0], dict) and message_history[0].get("role"):
            prior = message_history
        else:
            prior = _convert_legacy_history(message_history)
        if prior:
            prior = normalize_history_for_mode(prior, classification.mode.value)
            if len(prior) > _MAX_HISTORY_MESSAGES:
                prior = prior[-_MAX_HISTORY_MESSAGES:]
            query = f"[FOLLOW-UP] {query}"

    # --- Step 6: Run orchestrator with mode-specific config ---
    accumulated_text = ""
    _pending_chart_tool_names: set[str] = set()
    batcher = TextDeltaBatcher()

    try:
        orchestrator = ResearchOrchestrator(model=model)

        # Build mode-specific system content and tools
        mode_system_content = build_system_prompt(classification.mode, deps)
        mode_tools = get_tools_for_mode(classification.mode.value)

        # Create the messages array with mode-specific prompt
        from app.agent.agent import _trim_history

        messages: list[dict[str, Any]] = [{"role": "system", "content": mode_system_content}]
        if prior:
            messages.extend(_trim_history(prior))
        messages.append({"role": "user", "content": query})

        # Run the tool loop directly (bypass orchestrator.run to inject our tools)
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        while True:
            # Circuit breaker
            if deps.run_state.tool_call_count >= config.max_tool_calls:
                logger.warning(
                    "Mode %s circuit breaker: %d tool calls",
                    classification.mode.value,
                    deps.run_state.tool_call_count,
                )
                break

            stream = await orchestrator.client.chat.completions.create(
                model=orchestrator.model,
                messages=messages,
                tools=mode_tools if mode_tools else None,
                parallel_tool_calls=config.parallel_tool_calls if mode_tools else None,
                stream=True,
            )

            turn_text = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}

            async for chunk in stream:
                if chunk.usage:
                    total_usage["prompt_tokens"] += chunk.usage.prompt_tokens or 0
                    total_usage["completion_tokens"] += chunk.usage.completion_tokens or 0
                    total_usage["total_tokens"] += chunk.usage.total_tokens or 0

                for choice in chunk.choices:
                    delta = choice.delta
                    if delta is None:
                        continue
                    if delta.content:
                        turn_text += delta.content
                        accumulated_text += delta.content
                        batched = batcher.add(delta.content)
                        if batched is not None:
                            yield _sse("text_delta", {"token": batched})
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

            # No tool calls — model finished generating
            if not tool_calls_acc:
                break

            # Build assistant message
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": turn_text or None}
            assistant_msg["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            ]
            messages.append(assistant_msg)

            sorted_tcs = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            parsed_args: list[dict[str, Any]] = []
            for tc in sorted_tcs:
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                parsed_args.append(args)

            # Emit ToolCallStart events
            for tc in sorted_tcs:
                remaining = batcher.flush()
                if remaining is not None:
                    yield _sse("text_delta", {"token": remaining})
                meta = TOOL_METADATA.get(tc["name"], {"label": tc["name"], "icon": "tool"})
                try:
                    display_args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except Exception:
                    display_args = tc["arguments"]

                # Handle clarification (same as stream_research)
                if tc["name"] == "ask_clarification":
                    cid = tc["id"]
                    question = display_args.get("question", "") if isinstance(display_args, dict) else str(display_args)
                    context = display_args.get("context") if isinstance(display_args, dict) else None
                    options = display_args.get("options") or []
                    clarification_store.register(clarification_id=cid, question=question, context=context, options=options)
                    deps.pending_clarification_id = cid
                    deps.active_clarification_ids.append(cid)
                    yield _sse("clarification_needed", {
                        "clarification_id": cid,
                        "question": question,
                        "context": context,
                        "options": options,
                    })

                if tc["name"] == "get_financials":
                    _pending_chart_tool_names.add(tc["id"])

                yield _sse("tool_call_start", {
                    "tool_name": tc["name"],
                    "tool_label": meta["label"],
                    "icon": meta["icon"],
                    "call_id": tc["id"],
                    "args": display_args,
                    "status": "executing",
                })
                while not deps.tool_sse_queue.empty():
                    yield deps.tool_sse_queue.get_nowait()

            # Execute tools
            if len(sorted_tcs) == 1:
                results = [await execute_tool(sorted_tcs[0]["name"], parsed_args[0], deps)]
            else:
                results = await asyncio.gather(
                    *(execute_tool(tc["name"], a, deps) for tc, a in zip(sorted_tcs, parsed_args))
                )

            deps.run_state.tool_call_count += len(sorted_tcs)

            # Process results
            for tc, result_content in zip(sorted_tcs, results):
                # Check for special markers
                if result_content.startswith(_PROGRESS_MARKER):
                    try:
                        progress_data = json.loads(result_content[len(_PROGRESS_MARKER):])
                        yield _sse("progress", progress_data)
                    except json.JSONDecodeError:
                        pass
                elif result_content.startswith(_BATCH_JOB_MARKER):
                    try:
                        batch_data = json.loads(result_content[len(_BATCH_JOB_MARKER):])
                        yield _sse("batch_job_submitted", batch_data)
                    except json.JSONDecodeError:
                        pass

                # Check for clarification answer
                if result_content.startswith("User clarification:"):
                    answer_text = result_content.removeprefix("User clarification: ")
                    yield _sse("clarification_answered", {
                        "clarification_id": tc["id"],
                        "answer": answer_text,
                    })

                preview = result_content[:400] + "..." if len(result_content) > 400 else result_content
                yield _sse("tool_result", {
                    "call_id": tc["id"],
                    "preview": preview,
                })

                # Emit chart_data if this was a get_financials call
                if tc["id"] in _pending_chart_tool_names and deps.chart_payloads:
                    _pending_chart_tool_names.discard(tc["id"])
                    chart_payload = deps.chart_payloads[-1]
                    yield _sse("chart_data", {"chart": chart_payload})
                    ticker = chart_payload.get("ticker", "") if isinstance(chart_payload, dict) else ""
                    yield _sse("chart_trace", {"ticker": ticker, "payload": chart_payload})

                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_content})

                while not deps.tool_sse_queue.empty():
                    yield deps.tool_sse_queue.get_nowait()

        # --- Final result handling ---
        remaining = batcher.flush()
        if remaining is not None:
            yield _sse("text_delta", {"token": remaining})

        final_text = accumulated_text
        usage_data = {
            "request_tokens": total_usage["prompt_tokens"],
            "response_tokens": total_usage["completion_tokens"],
            "total_tokens": total_usage["total_tokens"],
        }

        # Save usage
        if session_id and usage_data.get("total_tokens"):
            try:
                from app.db import db_update_session

                asyncio.create_task(db_update_session(session_id, {"usage_tokens": usage_data["total_tokens"]}))
            except Exception:
                logger.warning("Failed to save token usage for session %s", session_id, exc_info=True)

        # Sources
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

        conflict_warnings = _detect_conflicts(deps.source_claims)
        if conflict_warnings:
            yield _sse("conflict_warning", {"warnings": conflict_warnings})

        sources = [
            {
                "url": url,
                "title": deps.source_titles.get(url, url),
                "domain": urlparse(url).netloc,
            }
            for url in sorted(deps.source_urls)
        ]

        yield _sse("final_report", {
            "markdown": final_text,
            "usage": usage_data,
            "messages": messages,
            "citation_warnings": citation_warnings,
            "conflict_warnings": conflict_warnings,
            "sources": sources,
            "mode": classification.mode.value,
            "estimated_cost_usd": round(deps.run_state.estimated_cost, 4),
        })

        # Emit AI-generated follow-up suggestions
        try:
            from app.agent.memory import generate_suggestions

            original_query = query.removeprefix("[FOLLOW-UP] ")
            suggestions = await generate_suggestions(original_query, final_text)
            if suggestions:
                yield _sse("suggestions", {"suggestions": suggestions})
        except Exception:
            logger.warning("Failed to generate follow-up suggestions for agent stream", exc_info=True)

        # Trigger memory extraction non-blocking
        if session_id and final_text:
            try:
                from app.agent.memory import extract_memories

                original_query = query.removeprefix("[FOLLOW-UP] ")
                asyncio.create_task(extract_memories(session_id, original_query, final_text))
            except Exception:
                logger.warning("Failed to trigger memory extraction for session %s", session_id, exc_info=True)

        # Publish report to knowledge graph extraction pipeline
        if session_id and final_text:
            try:
                from app.streams import publish_for_extraction

                asyncio.create_task(publish_for_extraction(session_id, final_text))
            except Exception:
                logger.warning("Failed to publish report to knowledge graph extraction for session %s", session_id, exc_info=True)

    except Exception as exc:
        # Flush buffered text before emitting the error
        remaining = batcher.flush()
        if remaining is not None:
            yield _sse("text_delta", {"token": remaining})
        yield _sse("error", {"message": str(exc)})
    finally:
        if deps.active_clarification_ids:
            clarification_store.cancel_session(deps.active_clarification_ids, reason="stream_closed")

    yield _sse("done", {"message": "Request complete"})

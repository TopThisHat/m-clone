"""
ResearchOrchestrator — drives the research agent via native OpenAI
chat completions with streaming and tool calling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.agent.prompts import (
    BASE_SYSTEM_PROMPT,
    RESEARCH_PROMPT,
    build_system_prompt,
)
from app.agent.run_state import estimate_turn_cost
from app.agent.runner_config import ExecutionMode
from app.agent.tools import execute_tool, get_openai_tools
from app.config import settings
from app.dependencies import AgentDeps
from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

# Re-export for backward compatibility — existing code and tests import
# SYSTEM_PROMPT from this module.  The canonical source is now prompts.py.
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT + "\n\n" + RESEARCH_PROMPT


# ── Orchestrator event types ─────────────────────────────────────────────────

@dataclass
class TextDelta:
    token: str


@dataclass
class ToolCallStart:
    call_id: str
    name: str
    arguments_json: str


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str


@dataclass
class FinalResult:
    text: str
    usage: dict[str, Any]
    messages: list[dict[str, Any]]


OrchestratorEvent = TextDelta | ToolCallStart | ToolResult | FinalResult


# ── Helper: build system messages ────────────────────────────────────────────

def _build_system_content(deps: AgentDeps) -> str:
    """Combine system prompt + uploaded document metadata + user rules + current date.

    Delegates to ``build_system_prompt`` with RESEARCH mode to preserve the
    existing behavior (full Phase 0-4 research loop).
    """
    return build_system_prompt(ExecutionMode.RESEARCH, deps)


# ── Token-based history trimming ─────────────────────────────────────────────

_MAX_HISTORY_TOKENS = 100_000

try:
    import tiktoken
    # Use o200k_base encoding (GPT-5.1 family); fall back if unavailable
    _enc = tiktoken.get_encoding("o200k_base")
except Exception:
    _enc = None


def _estimate_tokens(message: dict[str, Any]) -> int:
    """Estimate token count for a single message using tiktoken."""
    text_parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        text_parts.append(func.get("name", ""))
        text_parts.append(func.get("arguments", ""))
    combined = " ".join(text_parts)
    if _enc is not None:
        return len(_enc.encode(combined)) + 4  # per-message overhead
    return len(combined) // 4 + 4


def _trim_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim history to fit within _MAX_HISTORY_TOKENS.

    Strategy: drop oldest tool-result messages first (removing both the
    tool result and its matching tool_call from the assistant message),
    then drop oldest messages of any role, cutting at a user-message boundary.
    """
    total = sum(_estimate_tokens(m) for m in messages)
    if total <= _MAX_HISTORY_TOKENS:
        return messages

    # Phase 1: remove oldest tool results until under budget
    trimmed = list(messages)
    drop_tool_call_ids: set[str] = set()
    i = 0
    while i < len(trimmed):
        if total <= _MAX_HISTORY_TOKENS:
            break
        if trimmed[i].get("role") == "tool":
            total -= _estimate_tokens(trimmed[i])
            tool_call_id = trimmed[i].get("tool_call_id", "")
            if tool_call_id:
                drop_tool_call_ids.add(tool_call_id)
            trimmed.pop(i)
            continue
        i += 1

    # Remove orphaned tool_calls from assistant messages
    if drop_tool_call_ids:
        for msg in trimmed:
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                original_calls = msg["tool_calls"]
                filtered = [tc for tc in original_calls if tc.get("id") not in drop_tool_call_ids]
                if filtered:
                    msg["tool_calls"] = filtered
                else:
                    # All tool calls removed — convert to plain assistant message
                    msg.pop("tool_calls")
                    if not msg.get("content"):
                        msg["content"] = ""

    if total <= _MAX_HISTORY_TOKENS:
        return trimmed

    # Phase 2: drop oldest messages, cut at user-message boundary
    while total > _MAX_HISTORY_TOKENS and len(trimmed) > 1:
        total -= _estimate_tokens(trimmed[0])
        trimmed.pop(0)
    # Align to user-message boundary
    while trimmed and trimmed[0].get("role") not in ("user", "system"):
        total -= _estimate_tokens(trimmed[0])
        trimmed.pop(0)
    return trimmed


# ── Circuit breaker ──────────────────────────────────────────────────────────

_MAX_TOOL_CALLS: int = settings.max_tool_calls_per_turn


# ── Orchestrator ─────────────────────────────────────────────────────────────

class ResearchOrchestrator:
    """
    Drives the research agent via native OpenAI chat completions with
    streaming and tool calling. Yields OrchestratorEvent items.
    """

    def __init__(self, model: str | None = None) -> None:
        self.client: AsyncOpenAI = get_openai_client()
        # Strip provider prefix if present (e.g. "openai:gpt-5.1" → "gpt-5.1")
        raw = model or settings.default_model
        self.model = raw.split(":", 1)[-1] if ":" in raw else raw

    async def run(
        self,
        query: str,
        deps: AgentDeps,
        message_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[OrchestratorEvent]:
        """
        The main tool-calling loop:
        1. Build messages array (system + history + user query)
        2. Call client.chat.completions.create(stream=True, tools=...)
        3. Accumulate streamed tool call deltas
        4. Yield TextDelta for text tokens, ToolCallStart/ToolResult for tools
        5. Execute tools, append tool results to messages
        6. Loop back to step 2 until no tool calls remain
        7. Yield FinalResult with final text + usage + messages
        """
        system_content = _build_system_content(deps)
        tools = get_openai_tools()

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        if message_history:
            messages.extend(_trim_history(message_history))
        messages.append({"role": "user", "content": query})

        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        accumulated_text = ""

        while True:
            # --- Circuit breaker: stop if tool call budget exhausted ---
            if deps.run_state.tool_call_count >= _MAX_TOOL_CALLS:
                logger.warning(
                    "Circuit breaker: tool call limit reached (%d)",
                    deps.run_state.tool_call_count,
                )
                break

            # --- Stream a single completion ---
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                parallel_tool_calls=True if tools else None,
                stream=True,
            )

            # Accumulators for this turn
            turn_text = ""
            # {index: {id, name, arguments}} for parallel tool calls
            tool_calls_acc: dict[int, dict[str, str]] = {}

            async for chunk in stream:
                # Track usage from the final chunk
                if chunk.usage:
                    total_usage["prompt_tokens"] += chunk.usage.prompt_tokens or 0
                    total_usage["completion_tokens"] += chunk.usage.completion_tokens or 0
                    total_usage["total_tokens"] += chunk.usage.total_tokens or 0

                for choice in chunk.choices:
                    delta = choice.delta
                    if delta is None:
                        continue

                    # Text content
                    if delta.content:
                        turn_text += delta.content
                        accumulated_text += delta.content
                        yield TextDelta(token=delta.content)

                    # Tool call deltas
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

            # --- If no tool calls, we're done ---
            if not tool_calls_acc:
                break

            # Append the assistant message with tool_calls
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if turn_text:
                assistant_msg["content"] = turn_text
            else:
                assistant_msg["content"] = None
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            ]
            messages.append(assistant_msg)

            # --- Execute tool calls (parallel when multiple) ---
            sorted_tcs = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            parsed_args: list[dict] = []
            for tc in sorted_tcs:
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                parsed_args.append(args)

            # Yield all ToolCallStart events up front
            for tc in sorted_tcs:
                yield ToolCallStart(
                    call_id=tc["id"], name=tc["name"], arguments_json=tc["arguments"],
                )

            # Execute tools — parallel when >1 independent calls
            if len(sorted_tcs) == 1:
                results = [await execute_tool(sorted_tcs[0]["name"], parsed_args[0], deps)]
            else:
                results = await asyncio.gather(
                    *(execute_tool(tc["name"], a, deps) for tc, a in zip(sorted_tcs, parsed_args))
                )

            # Track tool call count and estimated cost
            deps.run_state.tool_call_count += len(sorted_tcs)
            deps.run_state.estimated_cost += estimate_turn_cost(len(sorted_tcs))

            # Yield all ToolResult events and append to messages
            for tc, result_content in zip(sorted_tcs, results):
                yield ToolResult(call_id=tc["id"], name=tc["name"], content=result_content)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_content,
                })

        # --- Yield final result ---
        final_text = accumulated_text
        usage_dict = {
            "request_tokens": total_usage["prompt_tokens"],
            "response_tokens": total_usage["completion_tokens"],
            "total_tokens": total_usage["total_tokens"],
        }
        yield FinalResult(text=final_text, usage=usage_dict, messages=messages)

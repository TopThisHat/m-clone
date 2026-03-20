"""
ResearchOrchestrator — drives the research agent via native OpenAI
chat completions with streaming and tool calling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.agent.tools import execute_tool, get_openai_tools
from app.config import settings
from app.dependencies import AgentDeps
from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a world-class research analyst. Your role is to conduct thorough, multi-source research
and produce authoritative, well-structured responses that directly serve the user's question.
You handle any topic — finance, technology, science, history, markets, companies, and more.

## QUERY CLASSIFICATION — CHECK FIRST

Before starting the research loop, classify the query:

**FORMAT-ONLY queries** — The user provides all the content and only asks you to reformat,
summarize, translate, restructure, list, or transform it. No external facts are needed.
Examples: "Reformat this as a table", "Summarize the above in 3 bullet points",
"Convert this to markdown", "Reorganize this list alphabetically".

→ For FORMAT-ONLY queries: **Skip ALL research phases.** Produce the requested output
  directly. No tool calls needed.

**RESEARCH queries** — The user needs external information you do not already have.
→ Proceed with the full research loop below.

---

## MANDATORY RESEARCH LOOP — FOLLOW EXACTLY

You MUST execute every phase below in order. Skipping phases is not permitted.

---

### Phase 0 — PLAN (first action, no exceptions)

Call `create_research_plan` as your very first tool call, before anything else.
Define 4–6 specific research angles that will guide the rest of your investigation.
Do not call any search or lookup tool before this plan is created.

Set `complexity` based on query breadth — `simple` for single-stat lookups (e.g., "What
is Apple's P/E ratio?"), `standard` for multi-facet questions (default), `deep` for broad
research topics or direct comparisons between multiple entities. The minimum tool call count
for Phase 1 is set by this value.

---

### Phase 1 — EXECUTE (minimum 4 research tool calls)

Run at least 4 research tool calls covering different angles from the plan:
- Use `web_search` with multiple DIFFERENT queries — one search per angle, never repeat a query
- Use `wiki_lookup` for background context on key entities, people, or industries
- Use `get_financials` for any publicly traded companies mentioned
- Use `search_uploaded_documents` if documents have been uploaded

Rules for this phase:
- Every `web_search` call MUST use a different query string from all previous searches
- Cover at least 3 different angles before moving to evaluation
- Do not write any report text during this phase

---

### Phase 2 — EVALUATE (required before writing any report)

Call `evaluate_research_completeness` after completing Phase 1.
Provide an honest summary of what was found, list gaps, and estimate confidence 0–100.

The tool returns a JSON object:
```
{"decision": "SUFFICIENT"|"CONTINUE", "evaluation_number": N, "confidence_pct": X, "gaps": [...], "recommended_queries": [...]}
```
- If `decision` is `SUFFICIENT` → proceed to Phase 4 (write report)
- If `decision` is `CONTINUE` → execute `recommended_queries` as new `web_search` calls, then re-evaluate

You MUST NOT write the final report before calling `evaluate_research_completeness` at least once.

---

### Phase 3 — DIG DEEPER (if confidence < 85%)

Execute targeted searches addressing the specific gaps identified in Phase 2.
Then call `evaluate_research_completeness` again.

**Standard queries:** you may evaluate up to 3 times total.
**Comprehensive list / deep queries:** you may evaluate up to 5 times. The evaluation
tool tracks `items_found` between rounds and only forces completion when progress stalls
(two consecutive evaluations with the same count) or the limit is reached.

---

### Phase 4 — REPORT (only after at least one evaluation)

Write the final report only after receiving "SUFFICIENT" from the evaluation tool
or after completing 3 evaluation rounds.

**Format and tone must fit the query:**

1. **Respect explicit user instructions first.** If the user asked for bullet points, a table,
   a short summary, a numbered list, a comparison, a timeline, or any specific structure —
   use exactly that. Their formatting instruction overrides everything below.

2. **Match depth to the question.** A broad strategic question ("analyse X's competitive
   position") warrants sections with headers. A narrow factual question ("what is X's P/E
   ratio?") may need only a paragraph or two. A comparison ("A vs B") calls for a side-by-side
   or table structure. Do not pad short answers into long reports.

3. **Match tone to the subject.** Finance and investment topics → precise, professional.
   General knowledge or how-to questions → clear and direct. Technical topics → technical
   vocabulary is fine. Never force "investment bank" framing onto non-financial queries.

4. **Always include specifics.** Names, figures, dates — never generalise when the research
   turned up concrete data.

5. **Cite every significant claim.** Inline citations are mandatory:
   - For web search results: hyperlink using the URL from the tool result and tag the tool,
     e.g. [Reuters](https://...) *(Web Search)* or [Press Release](https://...) *(Web Search)*
   - For Wikipedia: link the term and tag it, e.g. [TSMC](https://en.wikipedia.org/wiki/TSMC) *(Wikipedia)*
   - For financial data: note the metric with its tool tag, e.g. *$2.3T market cap (Yahoo Finance)*
   - For uploaded documents: cite with tool tag, e.g. *(Annual Report 2024 — Document Search)*
   - Place a **Sources** section at the very end as a numbered markdown list, each entry
     including the tool that provided it:
     `1. [Title](url) — Web Search`
     `2. [Wikipedia article](url) — Wikipedia`
     `3. Yahoo Finance — AAPL overview`
     `4. annual_report.pdf — Document Search`

6. **Default structure when no instruction is given** (use only if a structured report is
   genuinely appropriate for the question):
   - Brief opening that directly answers or frames the question
   - Logical sections with ## / ### headers
   - Closing takeaways relevant to *this* query (not a generic "Investment Considerations"
     section unless the query is actually about investing)
   - **Sources** section at the end

---

## Follow-up Questions — MANDATORY PHASES (no exceptions)

If the user message begins with `[FOLLOW-UP]`, execute these three phases in order.
The prior conversation history is in your context (older exchanges may have been trimmed
to stay within limits — if asked about something not in your context, say so rather than
guessing). Skip `create_research_plan` only — all other rules apply.

---

### Follow-up Phase A — RESEARCH (minimum 2 tool calls, unless skipped)

Before running Phase A tools, assess: does this follow-up require NEW external data not
already in conversation context? Summarization / reformatting of content already given →
skip Phase A entirely and go directly to Phase C. Any fact not in context → Phase A mandatory.

You MUST run fresh tool calls before writing any answer (when Phase A applies). Do NOT answer from memory or
prior context alone, even if you think you already know the answer.

- Call `web_search` at least twice with queries specifically targeting what the follow-up
  is asking — different queries, not repeats of earlier searches
- Call `wiki_lookup` if background on an entity or concept is needed
- Call `get_financials` if the follow-up touches on financial data
- Minimum 2 tool calls. Maximum 4. You MUST NOT skip this phase.

---

### Follow-up Phase B — EVALUATE (mandatory before writing the answer)

After completing Phase A, call `evaluate_research_completeness`:
- Set `findings_summary` to what the fresh research found relevant to the follow-up
- Set `identified_gaps` to anything still unanswered
- Set `confidence_pct` to your honest confidence that you can fully answer the follow-up

If confidence < 80%: run 1–2 more targeted searches addressing the gaps, then proceed.
If confidence ≥ 80% or after the extra searches: proceed to Phase C.

You MUST NOT write the answer before calling `evaluate_research_completeness`.

---

### Follow-up Phase C — ANSWER

Write a focused answer that:
- Directly and completely addresses the follow-up question
- Integrates fresh findings with relevant context from the prior conversation
- Follows all Phase 4 rules: format fits the question, inline citations, Sources section
- Is proportional — narrow question gets a tight answer, broad question gets full depth
- Respects any formatting instructions (e.g. "give me a table", "3 bullet points")

---

## Comprehensive List Queries

When the user asks for a comprehensive/complete list (e.g., "all NFL owners", "every
Fortune 500 CEO", "list all EU member states and their capitals"), follow these rules:

1. Set `complexity` to `deep` in `create_research_plan`
2. In each `evaluate_research_completeness` call, report the exact count of unique items
   found so far via the `items_found` parameter
3. **Do NOT give up early if you are still making progress.** Keep searching until you
   have found ALL expected items or progress has stalled.
4. You may evaluate up to 5 times for comprehensive lists (not the normal 3). The tool
   only forces completion when `items_found` stops increasing between evaluations.
5. Use multiple targeted searches to fill gaps — e.g., if you have 28 of 32 NFL teams,
   search specifically for the missing divisions or conferences.
6. In your report, present the COMPLETE list. If any items are missing, explicitly note
   which ones and why.

---

## Hard Rules

1. For new research: `create_research_plan` MUST be the first tool call — no exceptions
2. For new research: minimum 4 research tool calls before the first evaluation
3. For follow-ups: minimum 2 fresh research tool calls before calling `evaluate_research_completeness`
4. Each `web_search` must use a DIFFERENT query — no duplicate queries, ever
5. NEVER write any answer (new or follow-up) before calling `evaluate_research_completeness`
   (exception: FORMAT-ONLY queries skip all phases)
6. NEVER refuse a research request or say you "cannot" provide information
7. NEVER speculate from memory — always use tools to gather real information first
8. NEVER state a fact without citing the source it came from
9. If a query seems speculative (e.g. "who might buy X"), treat it as a research task:
   search for reported names, analyst commentary, and documented market activity

You have access to:
- `ask_clarification` — ask the user a clarifying question (call FIRST if the query is genuinely ambiguous, at most once)
- `create_research_plan` — structure the investigation (call first after clarification, if any)
- `evaluate_research_completeness` — self-assess before writing (call after research)
- `web_search` (Tavily) — current news, named individuals, reported deals
- `wiki_lookup` — encyclopedic background, histories, ownership structures
- `get_financials` (Yahoo Finance) — market data, valuations, fundamentals
- `search_uploaded_documents` — PDFs the client has uploaded

---

### Phase −1 — OPTIONAL CLARIFICATION (before Phase 0 only)

You MAY call `ask_clarification` ONCE as your very first action if the top-level
query is genuinely ambiguous in a way that changes the entire research direction.

GENUINE ambiguity: "Tell me about Mercury" (planet/element/car brand?),
"Analyse our performance" (no company name given).

NOT ambiguous: queries with sufficient context, or where a reasonable assumption
can be stated in the report.

Hard Rules (additions):
10. `ask_clarification` MUST be your very first tool call if used — never during Phase 1, 2, or 3.
11. Call `ask_clarification` at most ONCE per session.
"""


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
    """Combine SYSTEM_PROMPT + user rules + current date."""
    parts = [SYSTEM_PROMPT.strip()]

    if deps.user_rules:
        rules_text = "\n".join(f"- {r}" for r in deps.user_rules)
        parts.append(
            "\n## User-Defined Domain Rules\n\n"
            "The user has provided the following domain-specific rules and facts. "
            "**Apply ONLY the rules that are directly relevant to this query** — ignore rules about unrelated topics. "
            "When a rule is relevant, explicitly check for compliance or violations and note findings in your report.\n\n"
            f"{rules_text}"
        )

    today = date.today().strftime("%B %d, %Y")
    parts.append(
        f"Today's date is {today}. "
        "When searching for recent information, prioritise sources published within the last 30–90 days. "
        "If a source appears outdated relative to today's date, note that explicitly in your report."
    )

    return "\n\n".join(parts)


# ── Max history ──────────────────────────────────────────────────────────────

_MAX_HISTORY_MESSAGES = 60


def _trim_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) <= _MAX_HISTORY_MESSAGES:
        return messages
    target = len(messages) - _MAX_HISTORY_MESSAGES
    for i in range(target, len(messages)):
        msg = messages[i]
        if msg.get("role") == "user":
            return messages[i:]
    return messages[target:]


# ── Orchestrator ─────────────────────────────────────────────────────────────

class ResearchOrchestrator:
    """
    Drives the research agent via native OpenAI chat completions with
    streaming and tool calling. Yields OrchestratorEvent items.
    """

    def __init__(self, model: str | None = None) -> None:
        self.client: AsyncOpenAI = get_openai_client()
        # Strip provider prefix if present (e.g. "openai:gpt-4o" → "gpt-4o")
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
            # --- Stream a single completion ---
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
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

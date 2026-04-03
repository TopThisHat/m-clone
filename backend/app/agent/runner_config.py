"""Runner configuration for mode-specific execution strategies."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(str, Enum):
    """Supported agent execution modes.

    Each mode defines a distinct strategy with different constraints
    on turns, tool calls, and available tools.
    """

    FORMAT_ONLY = "format_only"
    QUICK_ANSWER = "quick_answer"
    RESEARCH = "research"
    DATA_PROCESSING = "data_processing"
    TASK_EXECUTION = "task_execution"


@dataclass(frozen=True)
class RunnerConfig:
    """Immutable configuration for a single execution mode.

    Defines the constraints (max turns, tool budget, allowed tools) that
    the runner enforces during agent execution.
    """

    mode: ExecutionMode
    max_turns: int
    max_tool_calls: int
    parallel_tool_calls: bool = True
    # Tool names allowed in this mode (None = all tools)
    allowed_tools: frozenset[str] | None = None


# Mode presets — these define the constraints per execution mode
RUNNER_CONFIGS: dict[ExecutionMode, RunnerConfig] = {
    ExecutionMode.FORMAT_ONLY: RunnerConfig(
        mode=ExecutionMode.FORMAT_ONLY,
        max_turns=1,
        max_tool_calls=0,
        allowed_tools=frozenset(),
    ),
    ExecutionMode.QUICK_ANSWER: RunnerConfig(
        mode=ExecutionMode.QUICK_ANSWER,
        max_turns=3,
        max_tool_calls=5,
        allowed_tools=frozenset({
            "ask_clarification",
            "web_search",
            "wiki_lookup",
            "get_financials",
            "search_uploaded_documents",
            "lookup_client",
            "talk_to_me",
            "query_knowledge_graph",
        }),
    ),
    ExecutionMode.RESEARCH: RunnerConfig(
        mode=ExecutionMode.RESEARCH,
        max_turns=20,
        max_tool_calls=30,
        # All tools available — None means no filtering
        allowed_tools=None,
    ),
    ExecutionMode.DATA_PROCESSING: RunnerConfig(
        mode=ExecutionMode.DATA_PROCESSING,
        max_turns=50,
        max_tool_calls=100,
        allowed_tools=frozenset({
            "ask_clarification",
            "search_uploaded_documents",
            "lookup_client",
            "batch_lookup_clients",
            "extract_and_lookup_entities",
            "get_financials",
            "talk_to_me",
            "query_knowledge_graph",
            # New tools (will be added later)
            "report_progress",
            "submit_batch_job",
        }),
    ),
    ExecutionMode.TASK_EXECUTION: RunnerConfig(
        mode=ExecutionMode.TASK_EXECUTION,
        max_turns=50,
        max_tool_calls=200,
        allowed_tools=frozenset({
            "ask_clarification",
            "web_search",
            "wiki_lookup",
            "get_financials",
            "sec_edgar_search",
            "search_uploaded_documents",
            "lookup_client",
            "batch_lookup_clients",
            "extract_and_lookup_entities",
            "talk_to_me",
            "query_knowledge_graph",
            # New tools (will be added later)
            "create_execution_plan",
            "report_progress",
            "submit_batch_job",
        }),
    ),
}

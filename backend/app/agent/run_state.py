"""Mutable execution state for a single agent turn.

Separated from AgentDeps (immutable request context) to prevent race
conditions when tools run in parallel via asyncio.gather.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunState:
    """Tracks mutable state during a single agent execution turn.

    Owned by the orchestrator, passed to tools that need to read or
    update execution state. Never shared across requests.
    """

    # Research mode state (existing, moved from AgentDeps)
    research_plan: list[str] = field(default_factory=list)
    evaluation_count: int = 0
    query_complexity: str = "standard"
    progress_history: list[int] = field(default_factory=list)

    # Execution plan state (new — for TASK_EXECUTION mode)
    execution_plan: list[dict] | None = None
    execution_step: int = 0
    estimated_tool_calls: int = 0

    # Cost tracking (new — for circuit breaker)
    tool_call_count: int = 0
    estimated_cost: float = 0.0

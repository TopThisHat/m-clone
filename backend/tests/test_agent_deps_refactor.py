"""Tests for AgentDeps integration with the RunState refactor.

Validates that AgentDeps works correctly with the new run_state field
introduced by the foundation refactor (Sprint 1, Task 1.8). The mutable
fields (research_plan, evaluation_count, query_complexity, progress_history)
have been moved from AgentDeps to RunState, and AgentDeps now holds a
run_state: RunState attribute.

Coverage:
  - get_agent_deps() creates an AgentDeps with a run_state attribute
  - run_state.query_complexity is set correctly from depth parameter
  - All depth values map correctly ("fast" -> "simple", "balanced" -> "standard", "deep" -> "deep")
  - Default AgentDeps has default RunState
  - RunState accessible via deps.run_state

Run: cd backend && uv run python -m pytest tests/test_agent_deps_refactor.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.agent.run_state import RunState
from app.dependencies import AgentDeps, get_agent_deps


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# AgentDeps — run_state Attribute
# ---------------------------------------------------------------------------

class TestAgentDepsHasRunState:
    """Verify AgentDeps has a run_state attribute of type RunState."""

    def test_get_agent_deps_creates_run_state(self):
        """get_agent_deps() must return an AgentDeps instance with a
        run_state attribute that is an instance of RunState. This is
        the primary entry point for constructing agent dependencies.
        """
        deps = get_agent_deps()
        assert hasattr(deps, "run_state")
        assert isinstance(deps.run_state, RunState)

    def test_default_agent_deps_has_default_run_state(self):
        """When no depth parameter is provided, the default AgentDeps
        must contain a RunState with all default values (query_complexity
        defaults to 'standard' via the 'balanced' depth mapping).
        """
        deps = get_agent_deps()
        assert deps.run_state.query_complexity == "standard"
        assert deps.run_state.evaluation_count == 0
        assert deps.run_state.research_plan == []
        assert deps.run_state.progress_history == []
        assert deps.run_state.tool_call_count == 0
        assert deps.run_state.estimated_cost == 0.0

    def test_run_state_is_independent_per_deps_instance(self):
        """Each call to get_agent_deps() must produce an independent
        RunState to prevent cross-request contamination.
        """
        deps1 = get_agent_deps()
        deps2 = get_agent_deps()
        # Mutating one should not affect the other
        deps1.run_state.evaluation_count = 5
        deps1.run_state.research_plan.append("angle1")
        assert deps2.run_state.evaluation_count == 0
        assert deps2.run_state.research_plan == []


# ---------------------------------------------------------------------------
# Depth → query_complexity Mapping
# ---------------------------------------------------------------------------

class TestDepthToComplexityMapping:
    """Verify depth parameter maps correctly to RunState.query_complexity."""

    def test_depth_fast_maps_to_simple(self):
        """Depth 'fast' must map to query_complexity 'simple', indicating
        a lightweight research pass (1-2 tool calls, no evaluation phase).
        """
        deps = get_agent_deps(depth="fast")
        assert deps.run_state.query_complexity == "simple"

    def test_depth_balanced_maps_to_standard(self):
        """Depth 'balanced' must map to query_complexity 'standard', the
        default research depth (minimum 4 tool calls before evaluation).
        """
        deps = get_agent_deps(depth="balanced")
        assert deps.run_state.query_complexity == "standard"

    def test_depth_deep_maps_to_deep(self):
        """Depth 'deep' must map to query_complexity 'deep', triggering
        thorough research (6+ tool calls, all angles covered).
        """
        deps = get_agent_deps(depth="deep")
        assert deps.run_state.query_complexity == "deep"

    def test_unknown_depth_falls_back_to_standard(self):
        """An unrecognized depth value must fall back to 'standard' to
        ensure safe default behavior rather than crashing.
        """
        deps = get_agent_deps(depth="ultra-extreme")
        assert deps.run_state.query_complexity == "standard"

    def test_all_known_depths_produce_expected_complexity(self):
        """Exhaustive check: every known depth value must produce the
        corresponding query_complexity per the _DEPTH_MAP.
        """
        expected = {
            "fast": "simple",
            "balanced": "standard",
            "deep": "deep",
        }
        for depth, complexity in expected.items():
            deps = get_agent_deps(depth=depth)
            assert deps.run_state.query_complexity == complexity, (
                f"depth={depth!r} should produce query_complexity={complexity!r}, "
                f"got {deps.run_state.query_complexity!r}"
            )


# ---------------------------------------------------------------------------
# RunState Mutability via AgentDeps
# ---------------------------------------------------------------------------

class TestRunStateMutabilityViaDeps:
    """Verify that RunState accessed via deps.run_state is mutable."""

    def test_can_set_research_plan_via_deps(self):
        """Tools must be able to write deps.run_state.research_plan
        during agent execution (e.g. create_research_plan tool).
        """
        deps = get_agent_deps()
        deps.run_state.research_plan = ["market analysis", "competitor review"]
        assert deps.run_state.research_plan == ["market analysis", "competitor review"]

    def test_can_increment_evaluation_count_via_deps(self):
        """Tools must be able to increment deps.run_state.evaluation_count
        during agent execution (e.g. evaluate_research tool).
        """
        deps = get_agent_deps()
        deps.run_state.evaluation_count += 1
        assert deps.run_state.evaluation_count == 1

    def test_can_set_query_complexity_via_deps(self):
        """Tools must be able to override deps.run_state.query_complexity
        when the LLM reassesses query complexity mid-execution.
        """
        deps = get_agent_deps(depth="fast")
        assert deps.run_state.query_complexity == "simple"
        deps.run_state.query_complexity = "deep"
        assert deps.run_state.query_complexity == "deep"

    def test_can_append_progress_history_via_deps(self):
        """The evaluate_research tool must be able to append items_found
        to deps.run_state.progress_history for stalled-progress detection.
        """
        deps = get_agent_deps()
        deps.run_state.progress_history.append(3)
        deps.run_state.progress_history.append(3)
        assert deps.run_state.progress_history == [3, 3]

    def test_can_track_tool_calls_via_deps(self):
        """The circuit breaker must be able to increment tool_call_count
        via deps.run_state to enforce the per-mode tool budget.
        """
        deps = get_agent_deps()
        for _ in range(10):
            deps.run_state.tool_call_count += 1
        assert deps.run_state.tool_call_count == 10


# ---------------------------------------------------------------------------
# AgentDeps — Other Fields Preserved
# ---------------------------------------------------------------------------

class TestAgentDepsOtherFields:
    """Verify that non-RunState fields on AgentDeps still work correctly."""

    def test_get_agent_deps_sets_doc_context(self):
        """get_agent_deps must set doc_context from the doc_context parameter."""
        deps = get_agent_deps(doc_context="Some document context")
        assert deps.doc_context == "Some document context"

    def test_get_agent_deps_sets_user_sid(self):
        """get_agent_deps must thread user_sid through to AgentDeps."""
        deps = get_agent_deps(user_sid="test-user-123")
        assert deps.user_sid == "test-user-123"

    def test_get_agent_deps_sets_team_ids(self):
        """get_agent_deps must thread team_ids through to AgentDeps."""
        deps = get_agent_deps(team_ids=["team-a", "team-b"])
        assert deps.team_ids == ["team-a", "team-b"]

    def test_get_agent_deps_sets_memory_context(self):
        """get_agent_deps must thread memory_context through to AgentDeps."""
        deps = get_agent_deps(memory_context="Previous conversation summary")
        assert deps.memory_context == "Previous conversation summary"

    def test_get_agent_deps_sets_user_rules(self):
        """get_agent_deps must thread user_rules through to AgentDeps."""
        deps = get_agent_deps(user_rules=["rule1", "rule2"])
        assert deps.user_rules == ["rule1", "rule2"]

    def test_get_agent_deps_pdf_context_alias(self):
        """The deprecated pdf_context alias must still work, falling
        through to doc_context when doc_context is empty.
        """
        deps = get_agent_deps(pdf_context="Legacy PDF content")
        assert deps.doc_context == "Legacy PDF content"

    def test_get_agent_deps_doc_context_takes_precedence(self):
        """When both doc_context and pdf_context are provided, doc_context
        must take precedence over the deprecated pdf_context alias.
        """
        deps = get_agent_deps(
            doc_context="New doc context",
            pdf_context="Old pdf context",
        )
        assert deps.doc_context == "New doc context"

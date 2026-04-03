"""Tests for RunState and RunnerConfig modules.

Validates the foundation refactor (Sprint 1, Task 1.8) that introduces:
  - RunState: mutable execution state for a single agent turn
  - RunnerConfig: frozen (immutable) per-mode execution constraints
  - ExecutionMode: enum of all 5 supported agent modes
  - RUNNER_CONFIGS: registry mapping every mode to its RunnerConfig

Coverage:
  - RunState initialization with defaults
  - RunState mutability (can set fields)
  - RunnerConfig is frozen (immutable)
  - RUNNER_CONFIGS has all 5 modes
  - Each mode has expected max_turns and max_tool_calls
  - FORMAT_ONLY has empty allowed_tools
  - RESEARCH has allowed_tools=None (all tools)
  - DATA_PROCESSING and TASK_EXECUTION have the expected tool subsets

Run: cd backend && uv run python -m pytest tests/test_run_state.py -v
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
import pytest_asyncio

from app.agent.run_state import RunState
from app.agent.runner_config import ExecutionMode, RunnerConfig, RUNNER_CONFIGS


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# RunState — Initialization Defaults
# ---------------------------------------------------------------------------

class TestRunStateDefaults:
    """Verify RunState initializes with correct default values."""

    def test_run_state_default_research_plan(self):
        """RunState.research_plan must default to an empty list so that
        tools can safely append research angles without a None check.
        """
        state = RunState()
        assert state.research_plan == []
        assert isinstance(state.research_plan, list)

    def test_run_state_default_evaluation_count(self):
        """RunState.evaluation_count must default to 0 representing
        no evaluations completed at the start of a turn.
        """
        state = RunState()
        assert state.evaluation_count == 0

    def test_run_state_default_query_complexity(self):
        """RunState.query_complexity must default to 'standard', the
        middle-ground depth level for research queries.
        """
        state = RunState()
        assert state.query_complexity == "standard"

    def test_run_state_default_progress_history(self):
        """RunState.progress_history must default to an empty list used
        for detecting stalled research progress across evaluations.
        """
        state = RunState()
        assert state.progress_history == []
        assert isinstance(state.progress_history, list)

    def test_run_state_default_execution_plan(self):
        """RunState.execution_plan must default to None, indicating no
        execution plan has been created for TASK_EXECUTION mode.
        """
        state = RunState()
        assert state.execution_plan is None

    def test_run_state_default_execution_step(self):
        """RunState.execution_step must default to 0 representing the
        start of plan execution.
        """
        state = RunState()
        assert state.execution_step == 0

    def test_run_state_default_estimated_tool_calls(self):
        """RunState.estimated_tool_calls must default to 0 before any
        execution plan is generated.
        """
        state = RunState()
        assert state.estimated_tool_calls == 0

    def test_run_state_default_tool_call_count(self):
        """RunState.tool_call_count must default to 0, the circuit
        breaker starts with no tool calls recorded.
        """
        state = RunState()
        assert state.tool_call_count == 0

    def test_run_state_default_estimated_cost(self):
        """RunState.estimated_cost must default to 0.0 representing
        zero accumulated cost at the start of a turn.
        """
        state = RunState()
        assert state.estimated_cost == 0.0


# ---------------------------------------------------------------------------
# RunState — Mutability
# ---------------------------------------------------------------------------

class TestRunStateMutability:
    """Verify RunState fields can be mutated during execution."""

    def test_run_state_can_set_research_plan(self):
        """Tools must be able to write research_plan to record the
        research angles chosen by create_research_plan.
        """
        state = RunState()
        state.research_plan = ["angle1", "angle2"]
        assert state.research_plan == ["angle1", "angle2"]

    def test_run_state_can_increment_evaluation_count(self):
        """The evaluate_research tool must be able to increment
        evaluation_count to track how many evaluation rounds occurred.
        """
        state = RunState()
        state.evaluation_count += 1
        assert state.evaluation_count == 1
        state.evaluation_count += 1
        assert state.evaluation_count == 2

    def test_run_state_can_set_query_complexity(self):
        """create_research_plan must be able to override query_complexity
        based on the LLM's assessment of the query.
        """
        state = RunState()
        state.query_complexity = "deep"
        assert state.query_complexity == "deep"

    def test_run_state_can_append_progress_history(self):
        """evaluate_research must be able to append items_found to
        progress_history for stalled-progress detection.
        """
        state = RunState()
        state.progress_history.append(5)
        state.progress_history.append(5)
        assert state.progress_history == [5, 5]

    def test_run_state_can_set_execution_plan(self):
        """The execution plan tool must be able to set execution_plan
        with a list of step dicts for TASK_EXECUTION mode.
        """
        state = RunState()
        plan = [{"step": 1, "action": "search"}, {"step": 2, "action": "analyze"}]
        state.execution_plan = plan
        assert state.execution_plan == plan
        assert len(state.execution_plan) == 2

    def test_run_state_can_increment_tool_call_count(self):
        """The circuit breaker must be able to track tool calls to
        enforce the per-mode tool budget.
        """
        state = RunState()
        state.tool_call_count += 1
        state.tool_call_count += 1
        state.tool_call_count += 1
        assert state.tool_call_count == 3

    def test_run_state_can_accumulate_estimated_cost(self):
        """Cost tracking must support incremental accumulation across
        multiple tool invocations.
        """
        state = RunState()
        state.estimated_cost += 0.01
        state.estimated_cost += 0.02
        assert abs(state.estimated_cost - 0.03) < 1e-9

    def test_run_state_custom_initialization(self):
        """RunState must support custom initialization for all fields,
        used by get_agent_deps to set query_complexity from depth.
        """
        state = RunState(
            query_complexity="simple",
            evaluation_count=2,
            tool_call_count=5,
        )
        assert state.query_complexity == "simple"
        assert state.evaluation_count == 2
        assert state.tool_call_count == 5


# ---------------------------------------------------------------------------
# RunnerConfig — Immutability
# ---------------------------------------------------------------------------

class TestRunnerConfigFrozen:
    """Verify RunnerConfig is frozen (immutable after creation)."""

    def test_runner_config_is_frozen(self):
        """RunnerConfig must be a frozen dataclass to prevent accidental
        mutation of mode constraints during execution. Attempting to set
        any field must raise FrozenInstanceError.
        """
        config = RunnerConfig(
            mode=ExecutionMode.RESEARCH,
            max_turns=20,
            max_tool_calls=30,
        )
        with pytest.raises(FrozenInstanceError):
            config.max_turns = 999

    def test_runner_config_cannot_set_max_tool_calls(self):
        """Attempting to change max_tool_calls on a frozen RunnerConfig
        must raise FrozenInstanceError.
        """
        config = RunnerConfig(
            mode=ExecutionMode.FORMAT_ONLY,
            max_turns=1,
            max_tool_calls=0,
        )
        with pytest.raises(FrozenInstanceError):
            config.max_tool_calls = 100

    def test_runner_config_cannot_set_allowed_tools(self):
        """Attempting to change allowed_tools on a frozen RunnerConfig
        must raise FrozenInstanceError.
        """
        config = RunnerConfig(
            mode=ExecutionMode.RESEARCH,
            max_turns=20,
            max_tool_calls=30,
            allowed_tools=None,
        )
        with pytest.raises(FrozenInstanceError):
            config.allowed_tools = frozenset({"web_search"})


# ---------------------------------------------------------------------------
# RUNNER_CONFIGS — Registry Completeness
# ---------------------------------------------------------------------------

class TestRunnerConfigsRegistry:
    """Verify RUNNER_CONFIGS contains all 5 execution modes."""

    def test_runner_configs_has_all_five_modes(self):
        """RUNNER_CONFIGS must map every ExecutionMode variant to a
        RunnerConfig. Missing modes would cause KeyError at runtime
        when the classifier selects a mode.
        """
        expected_modes = {
            ExecutionMode.FORMAT_ONLY,
            ExecutionMode.QUICK_ANSWER,
            ExecutionMode.RESEARCH,
            ExecutionMode.DATA_PROCESSING,
            ExecutionMode.TASK_EXECUTION,
        }
        assert set(RUNNER_CONFIGS.keys()) == expected_modes

    def test_runner_configs_values_are_runner_config_instances(self):
        """Every value in RUNNER_CONFIGS must be a RunnerConfig instance
        to guarantee the runner receives a well-typed config object.
        """
        for mode, config in RUNNER_CONFIGS.items():
            assert isinstance(config, RunnerConfig), (
                f"RUNNER_CONFIGS[{mode}] is {type(config).__name__}, "
                f"expected RunnerConfig"
            )

    def test_runner_configs_mode_matches_key(self):
        """Each RunnerConfig.mode must match its dict key so that the
        config is self-consistent.
        """
        for mode, config in RUNNER_CONFIGS.items():
            assert config.mode == mode, (
                f"RUNNER_CONFIGS[{mode}].mode is {config.mode}, expected {mode}"
            )


# ---------------------------------------------------------------------------
# RUNNER_CONFIGS — Per-Mode Constraints
# ---------------------------------------------------------------------------

class TestFormatOnlyMode:
    """Verify FORMAT_ONLY mode constraints."""

    def test_format_only_max_turns(self):
        """FORMAT_ONLY must allow exactly 1 turn because it only
        reformats existing content without any tool usage.
        """
        config = RUNNER_CONFIGS[ExecutionMode.FORMAT_ONLY]
        assert config.max_turns == 1

    def test_format_only_max_tool_calls(self):
        """FORMAT_ONLY must have 0 max_tool_calls since no tools
        should be invoked for pure formatting tasks.
        """
        config = RUNNER_CONFIGS[ExecutionMode.FORMAT_ONLY]
        assert config.max_tool_calls == 0

    def test_format_only_allowed_tools_empty(self):
        """FORMAT_ONLY must have an empty frozenset for allowed_tools,
        explicitly disabling all tool access.
        """
        config = RUNNER_CONFIGS[ExecutionMode.FORMAT_ONLY]
        assert config.allowed_tools is not None
        assert config.allowed_tools == frozenset()
        assert len(config.allowed_tools) == 0


class TestQuickAnswerMode:
    """Verify QUICK_ANSWER mode constraints."""

    def test_quick_answer_max_turns(self):
        """QUICK_ANSWER must allow 3 turns for a short tool-assisted
        response cycle.
        """
        config = RUNNER_CONFIGS[ExecutionMode.QUICK_ANSWER]
        assert config.max_turns == 3

    def test_quick_answer_max_tool_calls(self):
        """QUICK_ANSWER must allow 5 tool calls, enough for a quick
        lookup but limited to prevent runaway execution.
        """
        config = RUNNER_CONFIGS[ExecutionMode.QUICK_ANSWER]
        assert config.max_tool_calls == 5

    def test_quick_answer_allowed_tools_subset(self):
        """QUICK_ANSWER must provide a curated tool subset including
        common lookup tools but excluding batch/bulk tools.
        """
        config = RUNNER_CONFIGS[ExecutionMode.QUICK_ANSWER]
        assert config.allowed_tools is not None
        assert "web_search" in config.allowed_tools
        assert "talk_to_me" in config.allowed_tools
        assert "lookup_client" in config.allowed_tools
        # Batch tools should NOT be in quick_answer
        assert "batch_lookup_clients" not in config.allowed_tools
        assert "extract_and_lookup_entities" not in config.allowed_tools


class TestResearchMode:
    """Verify RESEARCH mode constraints."""

    def test_research_max_turns(self):
        """RESEARCH must allow 20 turns to support multi-step deep
        research with plan creation and evaluation cycles.
        """
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.max_turns == 20

    def test_research_max_tool_calls(self):
        """RESEARCH must allow 30 tool calls for thorough research
        across multiple angles and evaluation rounds.
        """
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.max_tool_calls == 30

    def test_research_allowed_tools_is_none(self):
        """RESEARCH must have allowed_tools=None, granting access to
        all registered tools without restriction.
        """
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.allowed_tools is None


class TestDataProcessingMode:
    """Verify DATA_PROCESSING mode constraints."""

    def test_data_processing_max_turns(self):
        """DATA_PROCESSING must allow 50 turns for large batch
        operations over CSV/entity data.
        """
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.max_turns == 50

    def test_data_processing_max_tool_calls(self):
        """DATA_PROCESSING must allow 100 tool calls for bulk entity
        resolution and batch lookups.
        """
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.max_tool_calls == 100

    def test_data_processing_has_batch_tools(self):
        """DATA_PROCESSING must include batch/bulk tools that are
        excluded from lighter modes.
        """
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.allowed_tools is not None
        assert "batch_lookup_clients" in config.allowed_tools
        assert "extract_and_lookup_entities" in config.allowed_tools
        assert "search_uploaded_documents" in config.allowed_tools

    def test_data_processing_excludes_web_search(self):
        """DATA_PROCESSING should NOT include web_search since batch
        data tasks operate on internal data sources only.
        """
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.allowed_tools is not None
        assert "web_search" not in config.allowed_tools

    def test_data_processing_includes_progress_tools(self):
        """DATA_PROCESSING must include progress reporting and batch
        submission tools for long-running operations.
        """
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.allowed_tools is not None
        assert "report_progress" in config.allowed_tools
        assert "submit_batch_job" in config.allowed_tools


class TestTaskExecutionMode:
    """Verify TASK_EXECUTION mode constraints."""

    def test_task_execution_max_turns(self):
        """TASK_EXECUTION must allow 50 turns for multi-step plans
        that combine research and data processing.
        """
        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.max_turns == 50

    def test_task_execution_max_tool_calls(self):
        """TASK_EXECUTION must allow 200 tool calls, the highest
        budget of all modes, for complex orchestrated workflows.
        """
        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.max_tool_calls == 200

    def test_task_execution_has_both_research_and_batch_tools(self):
        """TASK_EXECUTION must combine research tools (web_search,
        wiki_lookup) with batch tools (batch_lookup_clients) since it
        orchestrates both research and data processing.
        """
        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.allowed_tools is not None
        # Research tools
        assert "web_search" in config.allowed_tools
        assert "wiki_lookup" in config.allowed_tools
        assert "sec_edgar_search" in config.allowed_tools
        # Batch/data tools
        assert "batch_lookup_clients" in config.allowed_tools
        assert "extract_and_lookup_entities" in config.allowed_tools

    def test_task_execution_has_planning_tools(self):
        """TASK_EXECUTION must include the execution plan tool and
        progress reporting for orchestrated workflows.
        """
        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.allowed_tools is not None
        assert "create_execution_plan" in config.allowed_tools
        assert "report_progress" in config.allowed_tools
        assert "submit_batch_job" in config.allowed_tools

    def test_task_execution_has_highest_tool_budget(self):
        """TASK_EXECUTION must have the highest max_tool_calls of all
        modes to support complex multi-step plans.
        """
        task_budget = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION].max_tool_calls
        for mode, config in RUNNER_CONFIGS.items():
            if mode != ExecutionMode.TASK_EXECUTION:
                assert task_budget >= config.max_tool_calls, (
                    f"TASK_EXECUTION budget ({task_budget}) must be >= "
                    f"{mode.value} budget ({config.max_tool_calls})"
                )


# ---------------------------------------------------------------------------
# ExecutionMode — Enum Values
# ---------------------------------------------------------------------------

class TestExecutionModeEnum:
    """Verify ExecutionMode enum has correct string values."""

    def test_execution_mode_values(self):
        """Each ExecutionMode variant must have a snake_case string value
        for serialization in API responses and logs.
        """
        assert ExecutionMode.FORMAT_ONLY.value == "format_only"
        assert ExecutionMode.QUICK_ANSWER.value == "quick_answer"
        assert ExecutionMode.RESEARCH.value == "research"
        assert ExecutionMode.DATA_PROCESSING.value == "data_processing"
        assert ExecutionMode.TASK_EXECUTION.value == "task_execution"

    def test_execution_mode_is_str_enum(self):
        """ExecutionMode must inherit from str so that enum values can
        be used directly in string contexts (JSON serialization, logging).
        """
        assert isinstance(ExecutionMode.RESEARCH, str)
        assert ExecutionMode.RESEARCH == "research"

    def test_execution_mode_has_exactly_five_members(self):
        """ExecutionMode must have exactly 5 members corresponding to
        the 5 supported agent execution strategies.
        """
        assert len(ExecutionMode) == 5

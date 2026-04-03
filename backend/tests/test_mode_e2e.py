"""End-to-end mode tests — classification to prompt to tool filtering pipeline.

Validates the full flow:
  1. Heuristic or LLM classification assigns the correct mode
  2. build_system_prompt() produces mode-appropriate instructions
  3. get_tools_for_mode() returns the correct tool subset

Also tests the feature flag and rollback mechanism.

Tasks 15.3-15.4 + 15.5 + 15.7

Run: cd backend && uv run python -m pytest tests/test_mode_e2e.py -v
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.classifier import _heuristic_classify
from app.agent.prompts import build_system_prompt
from app.agent.runner_config import ExecutionMode, RUNNER_CONFIGS
from app.agent.tools import get_tools_for_mode


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_names(schemas: list[dict]) -> set[str]:
    """Extract tool names from a list of OpenAI function-calling schemas."""
    return {s["function"]["name"] for s in schemas}


def _make_deps(**overrides: Any) -> MagicMock:
    """Return a mock AgentDeps with sensible defaults."""
    deps = MagicMock()
    deps.uploaded_doc_metadata = overrides.get("uploaded_doc_metadata", [])
    deps.uploaded_filenames = overrides.get("uploaded_filenames", [])
    deps.user_rules = overrides.get("user_rules", [])
    return deps


# ---------------------------------------------------------------------------
# Task 15.3: DATA_PROCESSING end-to-end
# ---------------------------------------------------------------------------


class TestDataProcessingE2E:
    """Full pipeline test for DATA_PROCESSING mode."""

    def test_csv_lookup_classifies_as_data_processing(self):
        """A lookup query with CSV metadata must classify as DATA_PROCESSING
        via the heuristic (no LLM call needed)."""
        result = _heuristic_classify(
            "Look up all the names in this spreadsheet",
            has_documents=True,
            doc_metadata=[{"filename": "contacts.csv", "rows": 150}],
        )
        assert result is not None
        assert result.mode == ExecutionMode.DATA_PROCESSING
        assert result.source == "heuristic"
        assert result.batch_size == 150

    def test_data_processing_prompt_skips_research(self):
        """DATA_PROCESSING prompt must NOT contain Phase 0-4 research loop
        instructions.  It may mention create_research_plan in a negation
        context (e.g., 'Skip ... no create_research_plan')."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "EXECUTION MODE: DATA PROCESSING" in prompt
        # Must NOT include the actual research loop phases
        assert "Phase 0" not in prompt
        assert "Phase 1 " not in prompt  # trailing space to avoid matching "Phase" in other contexts
        assert "MANDATORY RESEARCH LOOP" not in prompt

    def test_data_processing_prompt_contains_inventory_phase(self):
        """DATA_PROCESSING must instruct the agent to inventory the data first."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "Inventory Phase" in prompt
        assert "Exact row/item count" in prompt

    def test_data_processing_prompt_contains_tool_selection(self):
        """DATA_PROCESSING must explain batch size tool selection."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "batch_lookup_clients" in prompt
        assert "lookup_client" in prompt

    def test_data_processing_prompt_contains_anti_truncation(self):
        """DATA_PROCESSING must include anti-truncation mandates."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "Anti-truncation" in prompt

    def test_data_processing_tools_exclude_web_search(self):
        """DATA_PROCESSING must NOT include web_search."""
        tools = get_tools_for_mode("data_processing")
        names = _tool_names(tools)
        assert "web_search" not in names

    def test_data_processing_tools_exclude_wiki_lookup(self):
        """DATA_PROCESSING must NOT include wiki_lookup."""
        tools = get_tools_for_mode("data_processing")
        names = _tool_names(tools)
        assert "wiki_lookup" not in names

    def test_data_processing_tools_exclude_research_planning(self):
        """DATA_PROCESSING must NOT include research planning tools."""
        tools = get_tools_for_mode("data_processing")
        names = _tool_names(tools)
        assert "create_research_plan" not in names
        assert "evaluate_research_completeness" not in names

    def test_data_processing_tools_include_batch_lookup(self):
        """DATA_PROCESSING must include batch_lookup_clients."""
        tools = get_tools_for_mode("data_processing")
        names = _tool_names(tools)
        assert "batch_lookup_clients" in names

    def test_data_processing_tools_include_extract_and_lookup(self):
        """DATA_PROCESSING must include extract_and_lookup_entities."""
        tools = get_tools_for_mode("data_processing")
        names = _tool_names(tools)
        assert "extract_and_lookup_entities" in names

    def test_data_processing_runner_config(self):
        """DATA_PROCESSING config must have high limits for batch work."""
        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.max_turns == 50
        assert config.max_tool_calls == 100

    def test_data_processing_full_pipeline(self):
        """End-to-end: classify -> prompt -> tools for CSV batch query."""
        # Step 1: Classify
        result = _heuristic_classify(
            "Process each row and find GWM IDs",
            has_documents=True,
            doc_metadata=[{"filename": "contacts.csv", "rows": 80}],
        )
        assert result is not None
        assert result.mode == ExecutionMode.DATA_PROCESSING

        # Step 2: Build prompt
        deps = _make_deps()
        prompt = build_system_prompt(result.mode, deps)
        assert "EXECUTION MODE: DATA PROCESSING" in prompt
        assert "MANDATORY RESEARCH LOOP" not in prompt

        # Step 3: Get tools
        tools = get_tools_for_mode(result.mode.value)
        names = _tool_names(tools)
        assert "batch_lookup_clients" in names
        assert "web_search" not in names


# ---------------------------------------------------------------------------
# Task 15.4: TASK_EXECUTION end-to-end
# ---------------------------------------------------------------------------


class TestTaskExecutionE2E:
    """Full pipeline test for TASK_EXECUTION mode."""

    def test_task_execution_prompt_has_execution_plan(self):
        """TASK_EXECUTION prompt must instruct the agent to create an
        execution plan as the first tool call."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "EXECUTION MODE: TASK EXECUTION" in prompt
        assert "create_execution_plan" in prompt
        assert "Step 1" in prompt

    def test_task_execution_prompt_skips_research_ceremony(self):
        """TASK_EXECUTION must skip the Phase 0-4 research loop.  It may
        mention create_research_plan in a negation context."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "MANDATORY RESEARCH LOOP" not in prompt
        assert "Phase 0" not in prompt

    def test_task_execution_prompt_contains_progress_reporting(self):
        """TASK_EXECUTION must instruct progress reporting after each step."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "report_progress" in prompt

    def test_task_execution_prompt_contains_autonomous_decisions(self):
        """TASK_EXECUTION must instruct autonomous decision-making."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "Autonomous" in prompt

    def test_task_execution_prompt_contains_plan_adaptation(self):
        """TASK_EXECUTION must support plan adaptation."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "Plan Adaptation" in prompt

    def test_task_execution_has_execution_plan_tool(self):
        """TASK_EXECUTION must include the create_execution_plan tool."""
        tools = get_tools_for_mode("task_execution")
        names = _tool_names(tools)
        assert "create_execution_plan" in names

    def test_task_execution_has_web_search(self):
        """TASK_EXECUTION must include web_search (unlike DATA_PROCESSING)."""
        tools = get_tools_for_mode("task_execution")
        names = _tool_names(tools)
        assert "web_search" in names

    def test_task_execution_has_wiki_lookup(self):
        """TASK_EXECUTION must include wiki_lookup."""
        tools = get_tools_for_mode("task_execution")
        names = _tool_names(tools)
        assert "wiki_lookup" in names

    def test_task_execution_excludes_research_planning_tools(self):
        """TASK_EXECUTION must NOT include create_research_plan or
        evaluate_research_completeness."""
        tools = get_tools_for_mode("task_execution")
        names = _tool_names(tools)
        assert "create_research_plan" not in names
        assert "evaluate_research_completeness" not in names

    def test_task_execution_runner_config(self):
        """TASK_EXECUTION config must have highest limits."""
        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.max_turns == 50
        assert config.max_tool_calls == 200

    def test_task_execution_has_report_progress_tool(self):
        """TASK_EXECUTION must include report_progress."""
        tools = get_tools_for_mode("task_execution")
        names = _tool_names(tools)
        assert "report_progress" in names


# ---------------------------------------------------------------------------
# Task 15.3-15.4: FORMAT_ONLY end-to-end
# ---------------------------------------------------------------------------


class TestFormatOnlyE2E:
    """Full pipeline test for FORMAT_ONLY mode."""

    def test_reformat_classifies_as_format_only(self):
        """Reformat requests must classify as FORMAT_ONLY via heuristic."""
        result = _heuristic_classify("Reformat this as a bullet list")
        assert result is not None
        assert result.mode == ExecutionMode.FORMAT_ONLY

    def test_format_only_prompt_skips_all_research(self):
        """FORMAT_ONLY prompt must skip all research phases."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.FORMAT_ONLY, deps)
        assert "EXECUTION MODE: FORMAT ONLY" in prompt
        assert "MANDATORY RESEARCH LOOP" not in prompt
        assert "No tool calls needed" in prompt

    def test_format_only_has_zero_tools(self):
        """FORMAT_ONLY must return zero tools."""
        tools = get_tools_for_mode("format_only")
        assert len(tools) == 0

    def test_format_only_runner_config(self):
        """FORMAT_ONLY config must have minimal limits."""
        config = RUNNER_CONFIGS[ExecutionMode.FORMAT_ONLY]
        assert config.max_turns == 1
        assert config.max_tool_calls == 0
        assert config.allowed_tools == frozenset()


# ---------------------------------------------------------------------------
# Task 15.3-15.4: QUICK_ANSWER end-to-end
# ---------------------------------------------------------------------------


class TestQuickAnswerE2E:
    """Full pipeline test for QUICK_ANSWER mode."""

    def test_simple_question_classifies_as_quick_answer(self):
        """Simple factual questions must classify as QUICK_ANSWER."""
        result = _heuristic_classify("What is Apple's P/E ratio?")
        assert result is not None
        assert result.mode == ExecutionMode.QUICK_ANSWER

    def test_quick_answer_prompt_is_concise(self):
        """QUICK_ANSWER prompt must instruct direct, minimal-tool answers."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.QUICK_ANSWER, deps)
        assert "EXECUTION MODE: QUICK ANSWER" in prompt
        assert "directly" in prompt.lower() or "concise" in prompt.lower()

    def test_quick_answer_has_web_search(self):
        """QUICK_ANSWER must include web_search for fact retrieval."""
        tools = get_tools_for_mode("quick_answer")
        names = _tool_names(tools)
        assert "web_search" in names

    def test_quick_answer_excludes_research_planning(self):
        """QUICK_ANSWER must NOT include create_research_plan or
        evaluate_research_completeness."""
        tools = get_tools_for_mode("quick_answer")
        names = _tool_names(tools)
        assert "create_research_plan" not in names
        assert "evaluate_research_completeness" not in names

    def test_quick_answer_runner_config(self):
        """QUICK_ANSWER config must have low limits."""
        config = RUNNER_CONFIGS[ExecutionMode.QUICK_ANSWER]
        assert config.max_turns == 3
        assert config.max_tool_calls == 5


# ---------------------------------------------------------------------------
# Task 15.3-15.4: RESEARCH end-to-end
# ---------------------------------------------------------------------------


class TestResearchE2E:
    """Full pipeline test for RESEARCH mode."""

    def test_research_prompt_has_full_ceremony(self):
        """RESEARCH must include the full Phase 0-4 research loop."""
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "EXECUTION MODE: RESEARCH" in prompt
        assert "create_research_plan" in prompt
        assert "evaluate_research_completeness" in prompt
        assert "Phase 0" in prompt
        assert "Phase 4" in prompt

    def test_research_has_all_research_tools(self):
        """RESEARCH must include create_research_plan and
        evaluate_research_completeness."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "create_research_plan" in names
        assert "evaluate_research_completeness" in names
        assert "web_search" in names

    def test_research_runner_config(self):
        """RESEARCH config must match the original defaults."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.max_turns == 20
        assert config.max_tool_calls == 30
        assert config.allowed_tools is None


# ---------------------------------------------------------------------------
# Task 15.3-15.4: Cross-mode prompt isolation
# ---------------------------------------------------------------------------


class TestCrossModePromptIsolation:
    """Each mode's prompt must include ONLY its own addendum, never
    instructions from another mode."""

    @pytest.mark.parametrize("mode", list(ExecutionMode))
    def test_prompt_contains_own_mode_label(self, mode: ExecutionMode):
        """Every mode prompt must declare its own execution mode label."""
        deps = _make_deps()
        prompt = build_system_prompt(mode, deps)
        # Each addendum contains "EXECUTION MODE: <MODE>" (with variation)
        mode_label = mode.value.upper().replace("_", " ")
        assert f"EXECUTION MODE: {mode_label}" in prompt

    def test_data_processing_does_not_contain_research_loop(self):
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "Phase 0" not in prompt
        assert "Phase 1" not in prompt  # Uses "Inventory Phase" instead

    def test_task_execution_does_not_contain_research_loop(self):
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "Phase 0" not in prompt
        assert "MANDATORY RESEARCH LOOP" not in prompt

    def test_format_only_does_not_contain_research_or_data(self):
        deps = _make_deps()
        prompt = build_system_prompt(ExecutionMode.FORMAT_ONLY, deps)
        assert "Phase 0" not in prompt
        assert "Inventory Phase" not in prompt
        assert "create_execution_plan" not in prompt


# ---------------------------------------------------------------------------
# Task 15.5: Feature flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """Test the should_use_auto_mode feature flag."""

    def test_zero_percent_disables_auto_mode(self):
        """When rollout_percent is 0, auto mode is always disabled."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 0
            assert should_use_auto_mode("any_user") is False
            assert should_use_auto_mode(None) is False
            assert should_use_auto_mode("") is False

    def test_hundred_percent_enables_auto_mode(self):
        """When rollout_percent is 100, auto mode is always enabled."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 100
            assert should_use_auto_mode("any_user") is True
            assert should_use_auto_mode(None) is True
            assert should_use_auto_mode("") is True

    def test_partial_rollout_with_user_sid(self):
        """When rollout is between 0-100, result depends on user_sid hash."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 50
            # Same user always gets same result (deterministic)
            result1 = should_use_auto_mode("user-abc-123")
            result2 = should_use_auto_mode("user-abc-123")
            assert result1 == result2

    def test_partial_rollout_without_user_sid_is_false(self):
        """When rollout is partial and no user_sid, default to False."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 50
            assert should_use_auto_mode(None) is False
            assert should_use_auto_mode("") is False

    def test_partial_rollout_distributes_users(self):
        """At 50%, roughly half of test user SIDs should be enabled."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 50
            enabled = sum(
                1 for i in range(1000)
                if should_use_auto_mode(f"test-user-{i}")
            )
            # Allow generous tolerance for hash distribution
            assert 350 < enabled < 650, (
                f"Expected ~500 enabled out of 1000, got {enabled}"
            )

    def test_negative_percent_disables(self):
        """Negative values should be treated as 0 (disabled)."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = -10
            assert should_use_auto_mode("user") is False

    def test_over_hundred_enables(self):
        """Values over 100 should be treated as 100 (fully enabled)."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 150
            assert should_use_auto_mode("user") is True


# ---------------------------------------------------------------------------
# Task 15.5: Settings integration
# ---------------------------------------------------------------------------


class TestAutoModeSettingsField:
    """Verify that auto_mode_rollout_percent exists in Settings."""

    def test_settings_has_rollout_percent(self):
        """Settings must have auto_mode_rollout_percent field."""
        from app.config import settings
        assert hasattr(settings, "auto_mode_rollout_percent")

    def test_settings_default_is_zero(self):
        """The default value must be 0 (auto mode disabled)."""
        from app.config import Settings
        # Check the field's default value from the class definition
        field_info = Settings.model_fields.get("auto_mode_rollout_percent")
        assert field_info is not None, "auto_mode_rollout_percent not in Settings"
        assert field_info.default == 0


# ---------------------------------------------------------------------------
# Task 15.7: Rollback documentation
# ---------------------------------------------------------------------------


class TestRollbackProcedure:
    """Documents the rollback procedure for multi-mode agent execution.

    To disable auto-classification and revert to legacy RESEARCH-only mode:

        export AUTO_MODE_ROLLOUT_PERCENT=0

    Or in .env:

        AUTO_MODE_ROLLOUT_PERCENT=0

    This immediately causes should_use_auto_mode() to return False for all
    users, routing all traffic through stream_research() (the pre-refactor
    code path).  No restart is needed if the setting is read per-request.

    The tests below verify this rollback mechanism works correctly.
    """

    def test_zero_percent_disables_auto_mode(self):
        """Setting AUTO_MODE_ROLLOUT_PERCENT=0 disables auto-classification
        for all users — the primary rollback mechanism."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 0
            # Should be False for any user SID, including None
            assert not should_use_auto_mode("any_user")
            assert not should_use_auto_mode(None)
            assert not should_use_auto_mode("admin-user")

    def test_hundred_percent_enables_auto_mode(self):
        """Setting AUTO_MODE_ROLLOUT_PERCENT=100 fully enables auto-classification."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 100
            assert should_use_auto_mode("any_user")
            assert should_use_auto_mode(None)

    def test_gradual_rollout_via_percent(self):
        """Setting AUTO_MODE_ROLLOUT_PERCENT=10 enables auto-classification
        for approximately 10% of users (consistent per user_sid)."""
        from app.agent.feature_flags import should_use_auto_mode

        with patch("app.agent.feature_flags.settings") as mock_settings:
            mock_settings.auto_mode_rollout_percent = 10
            enabled = sum(
                1 for i in range(1000)
                if should_use_auto_mode(f"user-{i}")
            )
            # ~10% of 1000 = ~100, with generous tolerance
            assert 50 < enabled < 200, (
                f"Expected ~100 enabled at 10%, got {enabled}"
            )

    def test_rollback_preserves_research_mode_behavior(self):
        """When auto mode is disabled (rollback state), the RESEARCH runner
        config is the one used by the legacy path."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        # These are the pre-refactor defaults
        assert config.max_turns == 20
        assert config.max_tool_calls == 30
        assert config.allowed_tools is None  # All tools available

    def test_rollback_preserves_legacy_system_prompt(self):
        """When auto mode is disabled, the legacy SYSTEM_PROMPT (base +
        research addendum) is used via stream_research()."""
        from app.agent.agent import SYSTEM_PROMPT
        from app.agent.prompts import BASE_SYSTEM_PROMPT, RESEARCH_PROMPT

        assert BASE_SYSTEM_PROMPT in SYSTEM_PROMPT
        assert RESEARCH_PROMPT in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Task 15.3-15.4: All modes have valid runner configs
# ---------------------------------------------------------------------------


class TestAllModesHaveConfigs:
    """Every ExecutionMode must have a corresponding RunnerConfig."""

    @pytest.mark.parametrize("mode", list(ExecutionMode))
    def test_mode_has_runner_config(self, mode: ExecutionMode):
        assert mode in RUNNER_CONFIGS, f"Missing RunnerConfig for {mode.value}"

    @pytest.mark.parametrize("mode", list(ExecutionMode))
    def test_mode_has_prompt_addendum(self, mode: ExecutionMode):
        """Every mode must produce a valid prompt via build_system_prompt."""
        deps = _make_deps()
        prompt = build_system_prompt(mode, deps)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

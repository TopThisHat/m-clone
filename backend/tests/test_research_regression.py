"""Regression tests for RESEARCH mode — backward compatibility.

Validates that the default execution path (execution_mode=None) behaves
identically to the pre-refactor system:

  - stream_research() is the entry point (not stream_agent)
  - The SYSTEM_PROMPT assembled for RESEARCH mode contains all Phase 0-4
    research loop instructions
  - All research tools are available (create_research_plan,
    evaluate_research_completeness, web_search, etc.)
  - Runner config defaults match the original limits
  - The legacy SYSTEM_PROMPT re-export from agent.py is intact

Run: cd backend && uv run python -m pytest tests/test_research_regression.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from app.agent.prompts import (
    BASE_SYSTEM_PROMPT,
    DATA_PROCESSING_PROMPT,
    FORMAT_ONLY_PROMPT,
    QUICK_ANSWER_PROMPT,
    RESEARCH_PROMPT,
    TASK_EXECUTION_PROMPT,
    build_system_prompt,
)
from app.agent.runner_config import ExecutionMode, RUNNER_CONFIGS, RunnerConfig
from app.agent.tools import TOOL_REGISTRY, get_openai_tools, get_tools_for_mode


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


def _make_minimal_deps() -> MagicMock:
    """Return a mock AgentDeps with the minimum fields needed by build_system_prompt."""
    deps = MagicMock()
    deps.uploaded_doc_metadata = []
    deps.uploaded_filenames = []
    deps.user_rules = []
    return deps


# ---------------------------------------------------------------------------
# Task 15.1: RESEARCH mode prompt regression
# ---------------------------------------------------------------------------


class TestResearchPromptRegression:
    """The RESEARCH mode prompt must contain all Phase 0-4 instructions
    that existed in the monolithic SYSTEM_PROMPT before the refactor."""

    def test_research_prompt_contains_phase_0(self):
        """Phase 0 — PLAN: create_research_plan must be the first tool call."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 0" in prompt
        assert "create_research_plan" in prompt
        assert "PLAN" in prompt

    def test_research_prompt_contains_phase_1(self):
        """Phase 1 — EXECUTE: minimum 4 research tool calls."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 1" in prompt
        assert "EXECUTE" in prompt
        assert "minimum 4" in prompt.lower() or "at least 4" in prompt.lower()

    def test_research_prompt_contains_phase_2(self):
        """Phase 2 — EVALUATE: evaluate_research_completeness before writing."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 2" in prompt
        assert "EVALUATE" in prompt
        assert "evaluate_research_completeness" in prompt

    def test_research_prompt_contains_phase_3(self):
        """Phase 3 — DIG DEEPER: targeted searches if confidence < 85%."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 3" in prompt
        assert "DIG DEEPER" in prompt

    def test_research_prompt_contains_phase_4(self):
        """Phase 4 — REPORT: write final report after evaluation."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 4" in prompt
        assert "REPORT" in prompt

    def test_research_prompt_includes_base_prompt(self):
        """The assembled prompt must start with the shared BASE_SYSTEM_PROMPT."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert prompt.startswith(BASE_SYSTEM_PROMPT)

    def test_research_prompt_includes_research_addendum(self):
        """The RESEARCH addendum must be present in the assembled prompt."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert RESEARCH_PROMPT in prompt

    def test_research_prompt_does_not_include_other_addenda(self):
        """The RESEARCH prompt must NOT include addenda from other modes."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert DATA_PROCESSING_PROMPT not in prompt
        assert TASK_EXECUTION_PROMPT not in prompt
        assert FORMAT_ONLY_PROMPT not in prompt
        assert QUICK_ANSWER_PROMPT not in prompt

    def test_research_prompt_contains_authorization_notice(self):
        """The shared BASE_SYSTEM_PROMPT contains the authorization notice
        required by all modes."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "AUTHORIZATION NOTICE" in prompt
        assert "authorized financial professionals" in prompt

    def test_research_prompt_contains_hard_rules(self):
        """Hard rules section must be present in the assembled prompt."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Hard Rules" in prompt

    def test_research_prompt_contains_follow_up_instructions(self):
        """Follow-up phases (A, B, C) must be present in the RESEARCH prompt."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Follow-up Phase A" in prompt
        assert "Follow-up Phase B" in prompt
        assert "Follow-up Phase C" in prompt

    def test_research_prompt_contains_comprehensive_list_instructions(self):
        """Comprehensive list query handling must be present."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Comprehensive List" in prompt

    def test_research_prompt_includes_date(self):
        """The assembled prompt must include today's date."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        # The date section is added dynamically
        assert "date" in prompt.lower()

    def test_research_prompt_mode_execution_label(self):
        """The RESEARCH addendum must declare its execution mode."""
        deps = _make_minimal_deps()
        prompt = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "EXECUTION MODE: RESEARCH" in prompt


# ---------------------------------------------------------------------------
# Task 15.1: RESEARCH mode tool availability regression
# ---------------------------------------------------------------------------


class TestResearchToolRegression:
    """All research tools must be available when running in RESEARCH mode."""

    def test_create_research_plan_available(self):
        """create_research_plan must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "create_research_plan" in names

    def test_evaluate_research_completeness_available(self):
        """evaluate_research_completeness must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "evaluate_research_completeness" in names

    def test_web_search_available(self):
        """web_search must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "web_search" in names

    def test_wiki_lookup_available(self):
        """wiki_lookup must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "wiki_lookup" in names

    def test_get_financials_available(self):
        """get_financials must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "get_financials" in names

    def test_search_uploaded_documents_available(self):
        """search_uploaded_documents must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "search_uploaded_documents" in names

    def test_lookup_client_available(self):
        """lookup_client must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "lookup_client" in names

    def test_batch_lookup_clients_available(self):
        """batch_lookup_clients must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "batch_lookup_clients" in names

    def test_talk_to_me_available(self):
        """talk_to_me must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "talk_to_me" in names

    def test_query_knowledge_graph_available(self):
        """query_knowledge_graph must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "query_knowledge_graph" in names

    def test_ask_clarification_available(self):
        """ask_clarification must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "ask_clarification" in names

    def test_sec_edgar_search_available(self):
        """sec_edgar_search must be available in RESEARCH mode."""
        tools = get_tools_for_mode("research")
        names = _tool_names(tools)
        assert "sec_edgar_search" in names

    def test_research_tools_superset_of_quick_answer(self):
        """RESEARCH mode tools must be a superset of QUICK_ANSWER tools."""
        research = _tool_names(get_tools_for_mode("research"))
        quick = _tool_names(get_tools_for_mode("quick_answer"))
        assert quick.issubset(research), (
            f"QUICK_ANSWER tools not in RESEARCH: {quick - research}"
        )

    def test_get_openai_tools_returns_all_tools(self):
        """get_openai_tools() must still return every registered tool
        for backward compatibility."""
        all_tools = get_openai_tools()
        names = _tool_names(all_tools)
        assert names == set(TOOL_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Task 15.1: RESEARCH mode runner config regression
# ---------------------------------------------------------------------------


class TestResearchRunnerConfigRegression:
    """RESEARCH mode RunnerConfig must match the pre-refactor defaults."""

    def test_default_mode_is_research_in_configs(self):
        """RESEARCH mode must exist in RUNNER_CONFIGS."""
        assert ExecutionMode.RESEARCH in RUNNER_CONFIGS

    def test_research_max_turns(self):
        """RESEARCH mode must allow 20 turns."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.max_turns == 20

    def test_research_max_tool_calls(self):
        """RESEARCH mode must allow 30 tool calls."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.max_tool_calls == 30

    def test_research_allows_all_tools(self):
        """RESEARCH mode must have allowed_tools=None (no filtering at runner level)."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.allowed_tools is None

    def test_research_parallel_tool_calls_enabled(self):
        """RESEARCH mode must have parallel tool calls enabled."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.parallel_tool_calls is True

    def test_research_config_is_runner_config(self):
        """The config value must be a RunnerConfig dataclass."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert isinstance(config, RunnerConfig)

    def test_research_config_is_frozen(self):
        """RunnerConfig must be immutable."""
        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        with pytest.raises(AttributeError):
            config.max_turns = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Task 15.1: Legacy SYSTEM_PROMPT re-export
# ---------------------------------------------------------------------------


class TestLegacySystemPromptExport:
    """The monolithic SYSTEM_PROMPT re-exported from agent.py must remain
    intact for backward-compatible tests and imports."""

    def test_legacy_system_prompt_exists(self):
        """SYSTEM_PROMPT must be importable from app.agent.agent."""
        from app.agent.agent import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_legacy_system_prompt_contains_base_and_research(self):
        """The re-exported SYSTEM_PROMPT must be BASE + RESEARCH."""
        from app.agent.agent import SYSTEM_PROMPT
        assert BASE_SYSTEM_PROMPT in SYSTEM_PROMPT
        assert RESEARCH_PROMPT in SYSTEM_PROMPT

    def test_legacy_prompt_contains_authorization_notice(self):
        from app.agent.agent import SYSTEM_PROMPT
        assert "AUTHORIZATION NOTICE" in SYSTEM_PROMPT

    def test_legacy_prompt_contains_phase_0_through_4(self):
        from app.agent.agent import SYSTEM_PROMPT
        for phase in range(5):
            assert f"Phase {phase}" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Task 15.1: stream_research vs stream_agent routing
# ---------------------------------------------------------------------------


class TestStreamRoutingRegression:
    """When execution_mode is None, stream_agent must delegate to
    stream_research for full backward compatibility."""

    @pytest.mark.asyncio
    async def test_stream_agent_delegates_to_stream_research_when_mode_is_none(self):
        """stream_agent(execution_mode=None) must iterate stream_research."""
        from unittest.mock import AsyncMock, patch

        mock_events = ["event1", "event2", "event3"]

        async def fake_stream_research(*args, **kwargs):
            for e in mock_events:
                yield e

        deps = _make_minimal_deps()

        with patch(
            "app.agent.streaming.stream_research",
            side_effect=fake_stream_research,
        ):
            from app.agent.streaming import stream_agent

            collected = []
            async for event in stream_agent("test query", deps, execution_mode=None):
                collected.append(event)

        assert collected == mock_events

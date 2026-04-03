"""Tests for mode-based tool filtering (Sprint 2, Tasks 4.1-4.7).

Validates:
  - ToolDef.modes field is correctly populated by @_register
  - get_tools_for_mode() returns the right schemas per execution mode
  - FORMAT_ONLY returns an empty tool list
  - RESEARCH includes all tools
  - DATA_PROCESSING excludes web_search, wiki_lookup, sec_edgar_search,
    create_research_plan, evaluate_research_completeness
  - TASK_EXECUTION excludes create_research_plan, evaluate_research_completeness
  - normalize_history_for_mode() strips irrelevant tool call/result pairs
  - get_openai_tools() still returns all tools (backward compatibility)

Run: cd backend && uv run python -m pytest tests/test_tool_filtering.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.agent.tools import (
    TOOL_REGISTRY,
    get_openai_tools,
    get_tools_for_mode,
    normalize_history_for_mode,
)


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


# All tool names present in the registry at module load time.
ALL_TOOL_NAMES = set(TOOL_REGISTRY.keys())

# Canonical mode strings matching ExecutionMode enum values.
FORMAT_ONLY = "format_only"
QUICK_ANSWER = "quick_answer"
RESEARCH = "research"
DATA_PROCESSING = "data_processing"
TASK_EXECUTION = "task_execution"


# ---------------------------------------------------------------------------
# Task 4.1-4.2: ToolDef.modes field populated correctly
# ---------------------------------------------------------------------------

class TestToolDefModes:
    """Verify that @_register correctly stores modes on ToolDef."""

    def test_all_tools_have_modes_set(self):
        """Every registered tool must have an explicit modes frozenset (not None)."""
        for name, td in TOOL_REGISTRY.items():
            assert td.modes is not None, (
                f"Tool '{name}' has modes=None; all tools should have explicit "
                f"mode tags for FORMAT_ONLY exclusion."
            )

    def test_modes_are_frozenset(self):
        """Modes must be stored as frozenset for immutability."""
        for name, td in TOOL_REGISTRY.items():
            if td.modes is not None:
                assert isinstance(td.modes, frozenset), (
                    f"Tool '{name}' modes should be frozenset, got {type(td.modes)}"
                )

    def test_create_research_plan_research_only(self):
        """create_research_plan should be available only in RESEARCH mode."""
        td = TOOL_REGISTRY["create_research_plan"]
        assert td.modes == frozenset({"research"})

    def test_evaluate_research_completeness_research_only(self):
        """evaluate_research_completeness should be available only in RESEARCH mode."""
        td = TOOL_REGISTRY["evaluate_research_completeness"]
        assert td.modes == frozenset({"research"})

    def test_extract_and_lookup_entities_modes(self):
        """extract_and_lookup_entities should be in DATA_PROCESSING and TASK_EXECUTION only."""
        td = TOOL_REGISTRY["extract_and_lookup_entities"]
        assert td.modes == frozenset({"data_processing", "task_execution"})

    def test_web_search_excludes_data_processing(self):
        """web_search should NOT be available in DATA_PROCESSING mode."""
        td = TOOL_REGISTRY["web_search"]
        assert "data_processing" not in td.modes

    def test_sec_edgar_search_modes(self):
        """sec_edgar_search should be in RESEARCH and TASK_EXECUTION only."""
        td = TOOL_REGISTRY["sec_edgar_search"]
        assert td.modes == frozenset({"research", "task_execution"})


# ---------------------------------------------------------------------------
# Task 4.3: get_tools_for_mode()
# ---------------------------------------------------------------------------

class TestGetToolsForMode:
    """Verify get_tools_for_mode returns correct tool schemas per mode."""

    def test_format_only_returns_empty(self):
        """FORMAT_ONLY mode should have zero tools."""
        tools = get_tools_for_mode(FORMAT_ONLY)
        assert tools == [], f"Expected empty list for FORMAT_ONLY, got {_tool_names(tools)}"

    def test_research_returns_expected_tools(self):
        """RESEARCH mode should include all tools tagged for research.

        Note: extract_and_lookup_entities is deliberately limited to
        DATA_PROCESSING and TASK_EXECUTION per the tool availability matrix.
        """
        tools = get_tools_for_mode(RESEARCH)
        names = _tool_names(tools)

        expected = {
            "ask_clarification",
            "create_research_plan",
            "evaluate_research_completeness",
            "web_search",
            "wiki_lookup",
            "get_financials",
            "sec_edgar_search",
            "search_uploaded_documents",
            "lookup_client",
            "batch_lookup_clients",
            "talk_to_me",
            "query_knowledge_graph",
        }
        assert names == expected, (
            f"RESEARCH mismatch.\n"
            f"  Extra: {names - expected}\n"
            f"  Missing: {expected - names}"
        )

    def test_quick_answer_tools(self):
        """QUICK_ANSWER should include the correct subset."""
        tools = get_tools_for_mode(QUICK_ANSWER)
        names = _tool_names(tools)

        expected = {
            "ask_clarification",
            "web_search",
            "wiki_lookup",
            "get_financials",
            "search_uploaded_documents",
            "lookup_client",
            "talk_to_me",
            "query_knowledge_graph",
        }
        assert names == expected, (
            f"QUICK_ANSWER mismatch.\n"
            f"  Extra: {names - expected}\n"
            f"  Missing: {expected - names}"
        )

    def test_data_processing_excludes_research_and_web_tools(self):
        """DATA_PROCESSING should NOT include web_search, wiki_lookup,
        sec_edgar_search, create_research_plan, or evaluate_research_completeness.
        """
        tools = get_tools_for_mode(DATA_PROCESSING)
        names = _tool_names(tools)

        excluded = {
            "web_search",
            "wiki_lookup",
            "sec_edgar_search",
            "create_research_plan",
            "evaluate_research_completeness",
        }
        for tool_name in excluded:
            assert tool_name not in names, (
                f"Tool '{tool_name}' should be excluded from DATA_PROCESSING"
            )

        # Verify expected tools ARE present
        expected_present = {
            "ask_clarification",
            "get_financials",
            "search_uploaded_documents",
            "lookup_client",
            "batch_lookup_clients",
            "extract_and_lookup_entities",
            "talk_to_me",
            "query_knowledge_graph",
        }
        for tool_name in expected_present:
            assert tool_name in names, (
                f"Tool '{tool_name}' should be present in DATA_PROCESSING"
            )

    def test_task_execution_excludes_research_planning_tools(self):
        """TASK_EXECUTION should NOT include create_research_plan or
        evaluate_research_completeness.
        """
        tools = get_tools_for_mode(TASK_EXECUTION)
        names = _tool_names(tools)

        excluded = {
            "create_research_plan",
            "evaluate_research_completeness",
        }
        for tool_name in excluded:
            assert tool_name not in names, (
                f"Tool '{tool_name}' should be excluded from TASK_EXECUTION"
            )

        # TASK_EXECUTION includes web/search tools unlike DATA_PROCESSING
        assert "web_search" in names
        assert "wiki_lookup" in names
        assert "sec_edgar_search" in names

    def test_unknown_mode_returns_only_untagged_tools(self):
        """An unrecognized mode string should only return tools with modes=None.
        Since all tools are tagged, this should return empty."""
        tools = get_tools_for_mode("nonexistent_mode")
        assert tools == []

    def test_schemas_are_valid_openai_format(self):
        """Every schema returned by get_tools_for_mode must have the
        expected OpenAI function-calling structure."""
        for mode in [QUICK_ANSWER, RESEARCH, DATA_PROCESSING, TASK_EXECUTION]:
            for schema in get_tools_for_mode(mode):
                assert schema["type"] == "function"
                assert "name" in schema["function"]
                assert "description" in schema["function"]
                assert "parameters" in schema["function"]


# ---------------------------------------------------------------------------
# Backward compatibility: get_openai_tools()
# ---------------------------------------------------------------------------

class TestGetOpenaiToolsBackwardCompat:
    """get_openai_tools() must still return ALL tools regardless of modes."""

    def test_returns_all_tools(self):
        tools = get_openai_tools()
        names = _tool_names(tools)
        assert names == ALL_TOOL_NAMES

    def test_count_matches_registry(self):
        assert len(get_openai_tools()) == len(TOOL_REGISTRY)


# ---------------------------------------------------------------------------
# Task 4.5: normalize_history_for_mode()
# ---------------------------------------------------------------------------

class TestNormalizeHistoryForMode:
    """Verify that normalize_history_for_mode strips tool calls/results
    for tools not available in the target mode."""

    def _make_tool_call_msg(
        self, call_id: str, tool_name: str, args: str = "{}",
    ) -> dict:
        """Create an assistant message with a single tool_call."""
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": args},
                }
            ],
        }

    def _make_tool_result_msg(
        self, call_id: str, content: str = "result",
    ) -> dict:
        """Create a tool-role result message."""
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        }

    def test_preserves_allowed_tool_calls(self):
        """Tool calls for tools available in the mode are kept."""
        history = [
            {"role": "user", "content": "Hello"},
            self._make_tool_call_msg("c1", "web_search"),
            self._make_tool_result_msg("c1", "search results"),
            {"role": "assistant", "content": "Here is what I found."},
        ]
        result = normalize_history_for_mode(history, RESEARCH)
        assert len(result) == 4

    def test_strips_disallowed_tool_calls(self):
        """Tool calls for tools NOT in the mode are removed, along with
        their corresponding tool results."""
        history = [
            {"role": "user", "content": "Process this data"},
            self._make_tool_call_msg("c1", "create_research_plan"),
            self._make_tool_result_msg("c1", "plan created"),
            self._make_tool_call_msg("c2", "web_search"),
            self._make_tool_result_msg("c2", "search results"),
            {"role": "assistant", "content": "Done."},
        ]
        # DATA_PROCESSING excludes create_research_plan AND web_search
        result = normalize_history_for_mode(history, DATA_PROCESSING)

        # user + assistant text should remain; both tool pairs stripped
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Done."

    def test_preserves_user_and_system_messages(self):
        """User and system messages are never filtered."""
        history = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = normalize_history_for_mode(history, FORMAT_ONLY)
        assert result == history

    def test_mixed_tool_calls_in_single_message(self):
        """When a single assistant message has multiple tool_calls, only
        the allowed ones are kept."""
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                },
                {
                    "id": "c2",
                    "type": "function",
                    "function": {"name": "create_research_plan", "arguments": "{}"},
                },
            ],
        }
        history = [
            {"role": "user", "content": "Go"},
            msg,
            self._make_tool_result_msg("c1", "web result"),
            self._make_tool_result_msg("c2", "plan result"),
        ]
        # QUICK_ANSWER includes web_search but NOT create_research_plan
        result = normalize_history_for_mode(history, QUICK_ANSWER)

        # user msg + assistant (with only web_search call) + web_search result
        assert len(result) == 3
        assert len(result[1]["tool_calls"]) == 1
        assert result[1]["tool_calls"][0]["function"]["name"] == "web_search"
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "c1"

    def test_assistant_text_preserved_when_all_calls_stripped(self):
        """If all tool_calls are stripped but the message has text content,
        the text portion is preserved without the tool_calls key."""
        msg = {
            "role": "assistant",
            "content": "Let me think about this.",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "create_research_plan", "arguments": "{}"},
                },
            ],
        }
        history = [msg]
        result = normalize_history_for_mode(history, DATA_PROCESSING)
        assert len(result) == 1
        assert result[0]["content"] == "Let me think about this."
        assert "tool_calls" not in result[0]

    def test_empty_history(self):
        """Empty input returns empty output."""
        assert normalize_history_for_mode([], RESEARCH) == []

    def test_format_only_strips_all_tool_calls(self):
        """FORMAT_ONLY has no tools, so all tool calls/results are stripped."""
        history = [
            {"role": "user", "content": "Format this"},
            self._make_tool_call_msg("c1", "web_search"),
            self._make_tool_result_msg("c1", "results"),
            {"role": "assistant", "content": "Formatted."},
        ]
        result = normalize_history_for_mode(history, FORMAT_ONLY)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Cross-validation: mode tags vs RunnerConfig.allowed_tools
# ---------------------------------------------------------------------------

class TestModeTagsMatchRunnerConfig:
    """Verify that the modes tagged on tools are consistent with the
    allowed_tools frozensets defined in runner_config.py."""

    def test_quick_answer_consistency(self):
        """Tools tagged for QUICK_ANSWER should match RunnerConfig allowed_tools."""
        from app.agent.runner_config import RUNNER_CONFIGS, ExecutionMode

        config = RUNNER_CONFIGS[ExecutionMode.QUICK_ANSWER]
        assert config.allowed_tools is not None

        tagged = _tool_names(get_tools_for_mode(QUICK_ANSWER))
        assert tagged == config.allowed_tools, (
            f"QUICK_ANSWER mismatch.\n"
            f"  Tagged but not in config: {tagged - config.allowed_tools}\n"
            f"  In config but not tagged: {config.allowed_tools - tagged}"
        )

    def test_data_processing_consistency(self):
        """Tools tagged for DATA_PROCESSING should be a subset of
        RunnerConfig allowed_tools (config may include future Sprint 3 tools)."""
        from app.agent.runner_config import RUNNER_CONFIGS, ExecutionMode

        config = RUNNER_CONFIGS[ExecutionMode.DATA_PROCESSING]
        assert config.allowed_tools is not None

        tagged = _tool_names(get_tools_for_mode(DATA_PROCESSING))
        # Config includes Sprint 3 tools not yet registered
        sprint3_tools = {"report_progress", "submit_batch_job"}
        config_minus_future = config.allowed_tools - sprint3_tools
        assert tagged == config_minus_future, (
            f"DATA_PROCESSING mismatch.\n"
            f"  Tagged but not in config: {tagged - config_minus_future}\n"
            f"  In config but not tagged: {config_minus_future - tagged}"
        )

    def test_task_execution_consistency(self):
        """Tools tagged for TASK_EXECUTION should be a subset of
        RunnerConfig allowed_tools (config may include future Sprint 3 tools)."""
        from app.agent.runner_config import RUNNER_CONFIGS, ExecutionMode

        config = RUNNER_CONFIGS[ExecutionMode.TASK_EXECUTION]
        assert config.allowed_tools is not None

        tagged = _tool_names(get_tools_for_mode(TASK_EXECUTION))
        sprint3_tools = {"create_execution_plan", "report_progress", "submit_batch_job"}
        config_minus_future = config.allowed_tools - sprint3_tools
        assert tagged == config_minus_future, (
            f"TASK_EXECUTION mismatch.\n"
            f"  Tagged but not in config: {tagged - config_minus_future}\n"
            f"  In config but not tagged: {config_minus_future - tagged}"
        )

    def test_research_allows_most_tools(self):
        """RESEARCH mode has allowed_tools=None in RunnerConfig (all tools allowed
        at the runner level).  The tool-level mode tags are more restrictive:
        extract_and_lookup_entities is excluded from RESEARCH per the design matrix.

        This is intentional — the runner config is a superset; the tool-level
        modes act as a second filter.
        """
        from app.agent.runner_config import RUNNER_CONFIGS, ExecutionMode

        config = RUNNER_CONFIGS[ExecutionMode.RESEARCH]
        assert config.allowed_tools is None  # None = all tools at runner level

        tagged = _tool_names(get_tools_for_mode(RESEARCH))
        # extract_and_lookup_entities is excluded at the tool level
        expected = ALL_TOOL_NAMES - {"extract_and_lookup_entities"}
        assert tagged == expected

    def test_format_only_empty(self):
        """FORMAT_ONLY has allowed_tools=frozenset() in RunnerConfig."""
        from app.agent.runner_config import RUNNER_CONFIGS, ExecutionMode

        config = RUNNER_CONFIGS[ExecutionMode.FORMAT_ONLY]
        assert config.allowed_tools == frozenset()

        tagged = _tool_names(get_tools_for_mode(FORMAT_ONLY))
        assert tagged == set()

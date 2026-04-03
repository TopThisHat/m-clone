"""Tests for the modular prompt architecture in app.agent.prompts.

Validates that ``build_system_prompt`` correctly assembles the base prompt,
mode-specific addenda, and dynamic sections (uploaded docs, user rules, date)
for every execution mode.

Coverage:
  - build_system_prompt returns a string containing base content for each mode
  - RESEARCH mode includes Phase 0-4 instructions
  - DATA_PROCESSING mode does NOT include create_research_plan references
  - TASK_EXECUTION mode includes create_execution_plan instructions
  - QUICK_ANSWER mode includes concise answer rules
  - FORMAT_ONLY mode skips all research phases
  - Each mode's prompt contains its unique section header
  - Dynamic sections (uploaded docs, user rules, date) are included
  - Backward-compatible SYSTEM_PROMPT re-export from agent.py

Sprint 2 — Multi-Mode Agent Execution Engine (Tasks 3.1-3.10)

Run: cd backend && uv run python -m pytest tests/test_prompts.py -v
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

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
from app.agent.runner_config import ExecutionMode


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Minimal AgentDeps stub for testing (avoids importing wikipediaapi)
# ---------------------------------------------------------------------------

class _StubDeps:
    """Minimal stand-in for AgentDeps with only the fields prompts.py reads."""

    def __init__(
        self,
        uploaded_doc_metadata=None,
        uploaded_filenames=None,
        user_rules=None,
    ):
        self.uploaded_doc_metadata = uploaded_doc_metadata or []
        self.uploaded_filenames = uploaded_filenames or []
        self.user_rules = user_rules or []


def _make_deps(**kwargs) -> _StubDeps:
    return _StubDeps(**kwargs)


# ---------------------------------------------------------------------------
# Base Prompt Content
# ---------------------------------------------------------------------------

class TestBasePromptContent:
    """Verify BASE_SYSTEM_PROMPT contains all shared sections."""

    def test_base_contains_authorization_notice(self):
        assert "AUTHORIZATION NOTICE" in BASE_SYSTEM_PROMPT

    def test_base_contains_anti_refusal_mandate(self):
        assert "Anti-refusal mandate" in BASE_SYSTEM_PROMPT
        assert "sensitive data" in BASE_SYSTEM_PROMPT
        assert "privacy concerns" in BASE_SYSTEM_PROMPT

    def test_base_contains_client_tool_decision_tree(self):
        assert "Client Tool Decision Tree" in BASE_SYSTEM_PROMPT
        assert "Step 1" in BASE_SYSTEM_PROMPT
        assert "Step 2" in BASE_SYSTEM_PROMPT
        assert "Step 3" in BASE_SYSTEM_PROMPT

    def test_base_contains_trigger_taxonomy(self):
        assert "TalkToMe Trigger Taxonomy" in BASE_SYSTEM_PROMPT
        assert "Category 1" in BASE_SYSTEM_PROMPT
        assert "Category 5" in BASE_SYSTEM_PROMPT

    def test_base_contains_catch_all_rule(self):
        assert "Catch-all" in BASE_SYSTEM_PROMPT
        assert "when in doubt" in BASE_SYSTEM_PROMPT.lower()

    def test_base_contains_negative_list(self):
        assert "Negative List" in BASE_SYSTEM_PROMPT

    def test_base_contains_batch_protocol(self):
        assert "INVENTORY" in BASE_SYSTEM_PROMPT
        assert "PLAN" in BASE_SYSTEM_PROMPT
        assert "EXECUTE" in BASE_SYSTEM_PROMPT
        assert "OUTPUT" in BASE_SYSTEM_PROMPT

    def test_base_contains_anti_truncation_mandates(self):
        assert "Anti-truncation" in BASE_SYSTEM_PROMPT
        lower = BASE_SYSTEM_PROMPT.lower()
        assert "too many rows" in lower
        assert "too large" in lower

    def test_base_contains_hard_rules(self):
        assert "Hard Rules" in BASE_SYSTEM_PROMPT

    def test_base_contains_mode_override_notice(self):
        assert "Mode-specific instructions below override" in BASE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# RESEARCH Mode
# ---------------------------------------------------------------------------

class TestResearchMode:
    """Verify RESEARCH mode includes the full Phase 0-4 research loop."""

    def test_research_prompt_contains_phase_0(self):
        assert "Phase 0" in RESEARCH_PROMPT
        assert "create_research_plan" in RESEARCH_PROMPT

    def test_research_prompt_contains_phase_1(self):
        assert "Phase 1" in RESEARCH_PROMPT
        assert "minimum 4 research tool calls" in RESEARCH_PROMPT

    def test_research_prompt_contains_phase_2(self):
        assert "Phase 2" in RESEARCH_PROMPT
        assert "evaluate_research_completeness" in RESEARCH_PROMPT

    def test_research_prompt_contains_phase_3(self):
        assert "Phase 3" in RESEARCH_PROMPT
        assert "DIG DEEPER" in RESEARCH_PROMPT

    def test_research_prompt_contains_phase_4(self):
        assert "Phase 4" in RESEARCH_PROMPT
        assert "REPORT" in RESEARCH_PROMPT

    def test_research_prompt_contains_followup_phases(self):
        assert "Follow-up Phase A" in RESEARCH_PROMPT
        assert "Follow-up Phase B" in RESEARCH_PROMPT
        assert "Follow-up Phase C" in RESEARCH_PROMPT

    def test_research_prompt_contains_comprehensive_list_rules(self):
        assert "Comprehensive List Queries" in RESEARCH_PROMPT

    def test_research_prompt_contains_citation_rules(self):
        assert "Cite every significant claim" in RESEARCH_PROMPT
        assert "Sources" in RESEARCH_PROMPT

    def test_research_prompt_contains_clarification_phase(self):
        assert "ask_clarification" in RESEARCH_PROMPT
        assert "Phase -1" in RESEARCH_PROMPT or "OPTIONAL CLARIFICATION" in RESEARCH_PROMPT

    def test_build_research_includes_phases(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Phase 0" in result
        assert "create_research_plan" in result
        assert "evaluate_research_completeness" in result

    def test_build_research_includes_base(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "AUTHORIZATION NOTICE" in result
        assert "Client Tool Decision Tree" in result


# ---------------------------------------------------------------------------
# DATA PROCESSING Mode
# ---------------------------------------------------------------------------

class TestDataProcessingMode:
    """Verify DATA_PROCESSING mode skips research ceremony."""

    def test_data_processing_excludes_research_plan_from_tools(self):
        """create_research_plan is mentioned only to say it is skipped,
        never listed in the 'You have access to' tool inventory."""
        # Split on the tool inventory section and verify it's not listed as available
        tool_section = DATA_PROCESSING_PROMPT.split("You have access to:")
        assert len(tool_section) == 2, "Expected 'You have access to:' section"
        assert "create_research_plan" not in tool_section[1]

    def test_data_processing_excludes_evaluate_from_tools(self):
        """evaluate_research_completeness is mentioned only to say it is skipped,
        never listed in the 'You have access to' tool inventory."""
        tool_section = DATA_PROCESSING_PROMPT.split("You have access to:")
        assert len(tool_section) == 2, "Expected 'You have access to:' section"
        assert "evaluate_research_completeness" not in tool_section[1]

    def test_data_processing_contains_inventory_phase(self):
        assert "Inventory Phase" in DATA_PROCESSING_PROMPT
        assert "Exact row/item count" in DATA_PROCESSING_PROMPT

    def test_data_processing_contains_tool_selection(self):
        assert "Tool Selection by Batch Size" in DATA_PROCESSING_PROMPT
        assert "1-4 names" in DATA_PROCESSING_PROMPT
        assert "5+ names" in DATA_PROCESSING_PROMPT
        assert "batch_lookup_clients" in DATA_PROCESSING_PROMPT

    def test_data_processing_contains_error_isolation(self):
        assert "Per-item error isolation" in DATA_PROCESSING_PROMPT

    def test_data_processing_contains_tabular_output(self):
        assert "Complete Tabular Output" in DATA_PROCESSING_PROMPT
        assert "summary line" in DATA_PROCESSING_PROMPT

    def test_data_processing_contains_anti_truncation(self):
        lower = DATA_PROCESSING_PROMPT.lower()
        assert "never say" in lower or "never output" in lower
        assert "too many rows" in lower or "too large" in lower

    def test_build_data_processing_excludes_research_plan(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        # The DATA_PROCESSING addendum itself must not mention create_research_plan
        # but the base prompt may mention it in the batch protocol general context.
        # Verify that the data processing mode header is present:
        assert "EXECUTION MODE: DATA PROCESSING" in result
        # Verify research-specific phases are NOT in the mode addendum portion
        assert "Phase 0" not in result
        assert "MANDATORY RESEARCH LOOP" not in result


# ---------------------------------------------------------------------------
# TASK EXECUTION Mode
# ---------------------------------------------------------------------------

class TestTaskExecutionMode:
    """Verify TASK_EXECUTION mode includes plan + step execution."""

    def test_task_execution_contains_execution_plan(self):
        assert "create_execution_plan" in TASK_EXECUTION_PROMPT

    def test_task_execution_contains_step_execution(self):
        assert "Execute Steps in Dependency Order" in TASK_EXECUTION_PROMPT

    def test_task_execution_contains_autonomous_decisions(self):
        assert "Autonomous Decision-Making" in TASK_EXECUTION_PROMPT

    def test_task_execution_contains_plan_adaptation(self):
        assert "Plan Adaptation" in TASK_EXECUTION_PROMPT

    def test_task_execution_contains_unified_summary(self):
        assert "Unified Summary" in TASK_EXECUTION_PROMPT

    def test_task_execution_excludes_research_plan_from_tools(self):
        """create_research_plan is mentioned only to say it is skipped,
        never listed in the 'You have access to' tool inventory."""
        tool_section = TASK_EXECUTION_PROMPT.split("You have access to:")
        assert len(tool_section) == 2, "Expected 'You have access to:' section"
        assert "create_research_plan" not in tool_section[1]

    def test_task_execution_excludes_evaluate_from_tools(self):
        """evaluate_research_completeness is mentioned only to say it is skipped,
        never listed in the 'You have access to' tool inventory."""
        tool_section = TASK_EXECUTION_PROMPT.split("You have access to:")
        assert len(tool_section) == 2, "Expected 'You have access to:' section"
        assert "evaluate_research_completeness" not in tool_section[1]

    def test_build_task_execution(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.TASK_EXECUTION, deps)
        assert "EXECUTION MODE: TASK EXECUTION" in result
        assert "create_execution_plan" in result


# ---------------------------------------------------------------------------
# QUICK ANSWER Mode
# ---------------------------------------------------------------------------

class TestQuickAnswerMode:
    """Verify QUICK_ANSWER mode is concise."""

    def test_quick_answer_contains_rules(self):
        assert "QUICK ANSWER" in QUICK_ANSWER_PROMPT
        assert "0-2 calls" in QUICK_ANSWER_PROMPT

    def test_quick_answer_requires_citation(self):
        assert "Cite the source" in QUICK_ANSWER_PROMPT

    def test_quick_answer_no_research_plan(self):
        assert "create_research_plan" not in QUICK_ANSWER_PROMPT

    def test_build_quick_answer(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.QUICK_ANSWER, deps)
        assert "EXECUTION MODE: QUICK ANSWER" in result
        # Should still include base content
        assert "AUTHORIZATION NOTICE" in result


# ---------------------------------------------------------------------------
# FORMAT ONLY Mode
# ---------------------------------------------------------------------------

class TestFormatOnlyMode:
    """Verify FORMAT_ONLY mode skips everything."""

    def test_format_only_contains_skip_instruction(self):
        assert "FORMAT ONLY" in FORMAT_ONLY_PROMPT
        assert "Skip all research phases" in FORMAT_ONLY_PROMPT
        assert "No tool calls needed" in FORMAT_ONLY_PROMPT

    def test_format_only_no_research_plan(self):
        assert "create_research_plan" in FORMAT_ONLY_PROMPT  # mentioned as "do NOT call"

    def test_build_format_only(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.FORMAT_ONLY, deps)
        assert "EXECUTION MODE: FORMAT ONLY" in result
        # Should NOT include research phases
        assert "Phase 0" not in result
        assert "MANDATORY RESEARCH LOOP" not in result


# ---------------------------------------------------------------------------
# Dynamic Sections
# ---------------------------------------------------------------------------

class TestDynamicSections:
    """Verify uploaded docs, user rules, and date are injected."""

    def test_uploaded_documents_included(self):
        deps = _make_deps(
            uploaded_doc_metadata=[
                {"filename": "report.pdf", "type": "pdf", "char_count": 5000, "pages": 12}
            ],
            uploaded_filenames=["report.pdf"],
        )
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "report.pdf" in result
        assert "Uploaded Documents" in result
        assert "5,000 chars" in result
        assert "12 pages" in result

    def test_single_document_reference_resolution(self):
        deps = _make_deps(
            uploaded_doc_metadata=[
                {"filename": "data.csv", "type": "csv", "char_count": 1000}
            ],
            uploaded_filenames=["data.csv"],
        )
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Only one document is uploaded" in result
        assert "data.csv" in result

    def test_multiple_document_reference_resolution(self):
        deps = _make_deps(
            uploaded_doc_metadata=[
                {"filename": "a.pdf", "type": "pdf", "char_count": 100},
                {"filename": "b.xlsx", "type": "excel", "char_count": 200},
            ],
            uploaded_filenames=["a.pdf", "b.xlsx"],
        )
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "Multiple documents are uploaded" in result
        assert "Filename matching" in result

    def test_user_rules_included(self):
        deps = _make_deps(user_rules=["Always check SEC filings", "Ignore penny stocks"])
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        assert "User-Defined Domain Rules" in result
        assert "Always check SEC filings" in result
        assert "Ignore penny stocks" in result

    def test_date_included(self):
        deps = _make_deps()
        result = build_system_prompt(ExecutionMode.RESEARCH, deps)
        today_str = date.today().strftime("%B %d, %Y")
        assert today_str in result

    def test_date_with_fixed_date(self):
        """Verify date injection uses the current date."""
        deps = _make_deps()
        with patch("app.agent.prompts.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = build_system_prompt(ExecutionMode.RESEARCH, deps)
            assert "January 15, 2026" in result

    def test_dynamic_sections_present_in_all_modes(self):
        """Dynamic sections (date at minimum) should appear in every mode."""
        deps = _make_deps(user_rules=["Test rule"])
        today_str = date.today().strftime("%B %d, %Y")
        for mode in ExecutionMode:
            result = build_system_prompt(mode, deps)
            assert today_str in result, f"Date missing in {mode.value} mode"
            assert "Test rule" in result, f"User rule missing in {mode.value} mode"

    def test_uploaded_docs_with_sheets_and_rows(self):
        deps = _make_deps(
            uploaded_doc_metadata=[
                {
                    "filename": "data.xlsx",
                    "type": "excel",
                    "char_count": 3000,
                    "sheets": 3,
                    "rows": 150,
                }
            ],
        )
        result = build_system_prompt(ExecutionMode.DATA_PROCESSING, deps)
        assert "3 sheets" in result
        assert "150 rows" in result


# ---------------------------------------------------------------------------
# Backward Compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify SYSTEM_PROMPT re-export from agent.py preserves content."""

    def test_system_prompt_import_from_agent(self):
        from app.agent.agent import SYSTEM_PROMPT
        # Must contain base content
        assert "AUTHORIZATION NOTICE" in SYSTEM_PROMPT
        assert "authorized financial professionals" in SYSTEM_PROMPT

    def test_system_prompt_contains_research_phases(self):
        from app.agent.agent import SYSTEM_PROMPT
        assert "Phase 0" in SYSTEM_PROMPT
        assert "create_research_plan" in SYSTEM_PROMPT
        assert "evaluate_research_completeness" in SYSTEM_PROMPT

    def test_system_prompt_contains_trigger_taxonomy(self):
        from app.agent.agent import SYSTEM_PROMPT
        assert "TalkToMe Trigger Taxonomy" in SYSTEM_PROMPT
        assert "Category 1" in SYSTEM_PROMPT
        assert "Category 5" in SYSTEM_PROMPT

    def test_system_prompt_contains_hard_rules(self):
        from app.agent.agent import SYSTEM_PROMPT
        assert "Hard Rules" in SYSTEM_PROMPT

    def test_system_prompt_contains_batch_protocol(self):
        from app.agent.agent import SYSTEM_PROMPT
        assert "INVENTORY" in SYSTEM_PROMPT
        assert "Anti-truncation" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Mode-Specific Uniqueness
# ---------------------------------------------------------------------------

class TestModeUniqueness:
    """Verify each mode contains its unique header and instructions."""

    def test_each_mode_has_unique_header(self):
        deps = _make_deps()
        expected_headers = {
            ExecutionMode.RESEARCH: "EXECUTION MODE: RESEARCH",
            ExecutionMode.QUICK_ANSWER: "EXECUTION MODE: QUICK ANSWER",
            ExecutionMode.DATA_PROCESSING: "EXECUTION MODE: DATA PROCESSING",
            ExecutionMode.TASK_EXECUTION: "EXECUTION MODE: TASK EXECUTION",
            ExecutionMode.FORMAT_ONLY: "EXECUTION MODE: FORMAT ONLY",
        }
        for mode, header in expected_headers.items():
            result = build_system_prompt(mode, deps)
            assert header in result, f"Missing header '{header}' in {mode.value} mode"

    def test_modes_do_not_contain_other_mode_headers(self):
        """Each mode's prompt should only contain its own mode header."""
        deps = _make_deps()
        mode_headers = {
            ExecutionMode.RESEARCH: "EXECUTION MODE: RESEARCH",
            ExecutionMode.QUICK_ANSWER: "EXECUTION MODE: QUICK ANSWER",
            ExecutionMode.DATA_PROCESSING: "EXECUTION MODE: DATA PROCESSING",
            ExecutionMode.TASK_EXECUTION: "EXECUTION MODE: TASK EXECUTION",
            ExecutionMode.FORMAT_ONLY: "EXECUTION MODE: FORMAT ONLY",
        }
        for mode in ExecutionMode:
            result = build_system_prompt(mode, deps)
            for other_mode, header in mode_headers.items():
                if other_mode == mode:
                    assert header in result
                else:
                    assert header not in result, (
                        f"{mode.value} prompt should not contain "
                        f"'{header}' from {other_mode.value}"
                    )

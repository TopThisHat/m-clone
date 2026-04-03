"""Test stubs for Sprint 2 — Query Classification.

These stubs pre-define the test surface for the query classifier that will
route user queries to the appropriate ExecutionMode. The classifier combines
heuristic rules (fast, deterministic) with an LLM fallback (for ambiguous
queries).

Stubs cover:
  - Heuristic classifier: format_only, quick_answer, data_processing
  - Heuristic returning None for ambiguous queries (triggers LLM fallback)
  - LLM classifier: research, task_execution
  - Confidence threshold enforcement
  - Mode override bypassing classification entirely

Run: cd backend && uv run python -m pytest tests/test_classifier.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Heuristic Classifier
# ---------------------------------------------------------------------------

class TestHeuristicClassifier:
    """Tests for the fast, deterministic heuristic classifier."""

    def test_heuristic_classifies_format_only(self):
        """Queries that only ask to reformat, summarize, or rephrase
        existing content (with no data lookup) must be classified as
        FORMAT_ONLY by the heuristic layer.

        Example: 'Reformat this as a bullet list'
        """
        pytest.skip("Sprint 2 — heuristic classifier not yet implemented")

    def test_heuristic_classifies_quick_answer(self):
        """Simple factual queries that can be answered with 1-2 tool
        calls must be classified as QUICK_ANSWER by the heuristic.

        Example: 'What is the stock price of AAPL?'
        """
        pytest.skip("Sprint 2 — heuristic classifier not yet implemented")

    def test_heuristic_classifies_data_processing_with_csv(self):
        """Queries that reference uploaded CSV data or request batch
        entity resolution must be classified as DATA_PROCESSING.

        Example: 'Look up all the names in the uploaded spreadsheet'
        """
        pytest.skip("Sprint 2 — heuristic classifier not yet implemented")

    def test_heuristic_returns_none_for_ambiguous(self):
        """Queries that do not clearly match any heuristic rule must
        return None, signaling the orchestrator to invoke the LLM
        classifier for a more nuanced assessment.

        Example: 'Tell me about recent market trends for tech companies'
        """
        pytest.skip("Sprint 2 — heuristic classifier not yet implemented")


# ---------------------------------------------------------------------------
# LLM Classifier
# ---------------------------------------------------------------------------

class TestLLMClassifier:
    """Tests for the LLM-based fallback classifier."""

    @pytest.mark.asyncio
    async def test_llm_classifier_research_query(self):
        """Deep, multi-angle research queries that require plan creation
        and evaluation cycles must be classified as RESEARCH by the LLM.

        Example: 'Analyze the competitive landscape of cloud computing
        providers and their market positioning strategies'
        """
        pytest.skip("Sprint 2 — LLM classifier not yet implemented")

    @pytest.mark.asyncio
    async def test_llm_classifier_task_execution(self):
        """Multi-step orchestrated workflows that combine research and
        data processing must be classified as TASK_EXECUTION by the LLM.

        Example: 'Research the top 50 SaaS companies, find their CFOs,
        and look up each one in our CRM'
        """
        pytest.skip("Sprint 2 — LLM classifier not yet implemented")


# ---------------------------------------------------------------------------
# Confidence Threshold
# ---------------------------------------------------------------------------

class TestConfidenceThreshold:
    """Tests for confidence-based classification validation."""

    @pytest.mark.asyncio
    async def test_confidence_below_threshold_raises_error(self):
        """When the LLM classifier returns a confidence score below the
        minimum threshold, classification must raise an error rather than
        proceeding with a low-confidence mode selection. This prevents
        misrouting queries to inappropriate execution strategies.
        """
        pytest.skip("Sprint 2 — confidence threshold not yet implemented")


# ---------------------------------------------------------------------------
# Mode Override
# ---------------------------------------------------------------------------

class TestModeOverride:
    """Tests for explicit mode override bypassing classification."""

    @pytest.mark.asyncio
    async def test_mode_override_bypasses_classification(self):
        """When the caller provides an explicit mode override (e.g. via
        API parameter or system instruction), the classifier must be
        skipped entirely and the specified mode returned directly. This
        supports testing, debugging, and power-user workflows.
        """
        pytest.skip("Sprint 2 — mode override not yet implemented")

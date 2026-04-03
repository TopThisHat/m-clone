"""Tests for Sprint 2 -- Query Classification.

Covers the full classifier surface:
  - Heuristic classifier: format_only, quick_answer, data_processing
  - Heuristic returning None for ambiguous queries (triggers LLM fallback)
  - LLM classifier: research, task_execution
  - Confidence threshold enforcement
  - Mode override bypassing classification entirely
  - Edge cases: empty queries, extremely long queries

All LLM tests mock the OpenAI client -- no real API calls are made.

Run: cd backend && uv run python -m pytest tests/test_classifier.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.classifier import (
    CONFIDENCE_THRESHOLD,
    ClassificationError,
    ClassificationResult,
    _heuristic_classify,
    _llm_classify,
    classify_query,
)
from app.agent.runner_config import ExecutionMode


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers for building mock LLM responses
# ---------------------------------------------------------------------------


def _make_llm_response(
    mode: str,
    confidence: float = 0.85,
    reasoning: str = "test",
    estimated_steps: int = 10,
    requires_iteration: bool = True,
    batch_size: int | None = None,
) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response with JSON content."""
    payload = {
        "mode": mode,
        "confidence": confidence,
        "reasoning": reasoning,
        "estimated_steps": estimated_steps,
        "requires_iteration": requires_iteration,
        "batch_size": batch_size,
    }
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_openai_client(response: MagicMock) -> MagicMock:
    """Return a mock AsyncOpenAI client that returns the given response."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Heuristic Classifier
# ---------------------------------------------------------------------------


class TestHeuristicClassifier:
    """Tests for the fast, deterministic heuristic classifier."""

    def test_heuristic_classifies_format_only(self):
        """Queries that only ask to reformat, summarize, or rephrase
        existing content (with no data lookup) must be classified as
        FORMAT_ONLY by the heuristic layer.
        """
        queries = [
            "Reformat this as a bullet list",
            "convert to a table please",
            "Summarize this for me",
            "summarize the above in 3 sentences",
            "reorganize these notes",
            "translate this to Spanish",
            "as a table with headers",
            "rephrase this more formally",
            "rewrite this paragraph",
        ]
        for query in queries:
            result = _heuristic_classify(query)
            assert result is not None, f"Expected FORMAT_ONLY for: {query!r}"
            assert result.mode == ExecutionMode.FORMAT_ONLY, (
                f"Expected FORMAT_ONLY for {query!r}, got {result.mode}"
            )
            assert result.confidence == 0.9
            assert result.source == "heuristic"
            assert result.estimated_steps == 1
            assert result.requires_iteration is False

    def test_heuristic_classifies_quick_answer(self):
        """Simple factual queries that can be answered with 1-2 tool
        calls must be classified as QUICK_ANSWER by the heuristic.
        """
        queries = [
            "What is the stock price of AAPL?",
            "Who is the CEO of Tesla?",
            "When did Apple go public?",
            "How much revenue did Google make?",
            "What's the market cap of Microsoft?",
        ]
        for query in queries:
            result = _heuristic_classify(query)
            assert result is not None, f"Expected QUICK_ANSWER for: {query!r}"
            assert result.mode == ExecutionMode.QUICK_ANSWER, (
                f"Expected QUICK_ANSWER for {query!r}, got {result.mode}"
            )
            assert result.confidence == 0.9
            assert result.source == "heuristic"
            assert result.estimated_steps == 2

    def test_heuristic_quick_answer_rejected_with_sequential(self):
        """Queries that look like quick answers but contain sequential
        indicators should NOT be classified as QUICK_ANSWER.
        """
        queries = [
            "What is AAPL price then compare it to MSFT",
            "Who is the CEO and then find their background",
            "What's the revenue after that calculate growth rate",
        ]
        for query in queries:
            result = _heuristic_classify(query)
            # Should NOT match quick_answer (may be None or match something else)
            if result is not None:
                assert result.mode != ExecutionMode.QUICK_ANSWER, (
                    f"Should NOT be QUICK_ANSWER for sequential query: {query!r}"
                )

    def test_heuristic_quick_answer_rejected_when_long(self):
        """Queries over 25 tokens should not match QUICK_ANSWER even if
        they start with a question word.
        """
        long_query = (
            "What is the comprehensive detailed financial analysis of Apple Inc "
            "including revenue trends operating margins and free cash flow "
            "generation over the past five fiscal years?"
        )
        result = _heuristic_classify(long_query)
        if result is not None:
            assert result.mode != ExecutionMode.QUICK_ANSWER

    def test_heuristic_classifies_data_processing_with_csv(self):
        """Queries that reference uploaded CSV data or request batch
        entity resolution must be classified as DATA_PROCESSING.
        """
        doc_metadata: list[dict[str, Any]] = [
            {"filename": "companies.csv", "rows": 150, "columns": ["name", "domain"]},
        ]
        queries = [
            "Look up all the names in the uploaded spreadsheet",
            "Process each row and enrich with company data",
            "Extract entities from every row",
            "Batch look up these companies",
            "Cross-reference the names with our CRM",
            "Check which companies are public",
            "For each row find the CEO",
            "Parse the data and enrich it",
        ]
        for query in queries:
            result = _heuristic_classify(
                query, has_documents=True, doc_metadata=doc_metadata,
            )
            assert result is not None, f"Expected DATA_PROCESSING for: {query!r}"
            assert result.mode == ExecutionMode.DATA_PROCESSING, (
                f"Expected DATA_PROCESSING for {query!r}, got {result.mode}"
            )
            assert result.confidence == 0.9
            assert result.source == "heuristic"
            assert result.batch_size == 150

    def test_heuristic_data_processing_requires_tabular_data(self):
        """DATA_PROCESSING should NOT match when documents lack a 'rows' field."""
        doc_metadata: list[dict[str, Any]] = [
            {"filename": "report.pdf", "pages": 12},
        ]
        result = _heuristic_classify(
            "Look up all the names",
            has_documents=True,
            doc_metadata=doc_metadata,
        )
        # Should be None (ambiguous) -- no tabular data
        assert result is None or result.mode != ExecutionMode.DATA_PROCESSING

    def test_heuristic_data_processing_requires_documents(self):
        """DATA_PROCESSING should NOT match when has_documents is False."""
        result = _heuristic_classify(
            "Look up all the names in the spreadsheet",
            has_documents=False,
        )
        assert result is None or result.mode != ExecutionMode.DATA_PROCESSING

    def test_heuristic_returns_none_for_ambiguous(self):
        """Queries that do not clearly match any heuristic rule must
        return None, signaling the orchestrator to invoke the LLM
        classifier for a more nuanced assessment.
        """
        queries = [
            "Tell me about recent market trends for tech companies",
            "Analyze the competitive landscape of cloud computing",
            "Research the top SaaS companies and their pricing strategies",
            "What are the key risks facing the semiconductor industry?",
            "Compare the business models of Uber and Lyft",
        ]
        for query in queries:
            result = _heuristic_classify(query)
            assert result is None, (
                f"Expected None (ambiguous) for: {query!r}, got {result}"
            )

    def test_heuristic_handles_empty_query(self):
        """Empty or whitespace-only queries should return None."""
        assert _heuristic_classify("") is None
        assert _heuristic_classify("   ") is None
        assert _heuristic_classify("\n\t") is None

    def test_heuristic_format_only_case_insensitive(self):
        """Pattern matching must be case-insensitive."""
        result = _heuristic_classify("REFORMAT THIS AS A TABLE")
        assert result is not None
        assert result.mode == ExecutionMode.FORMAT_ONLY

    def test_heuristic_data_processing_batch_size_calculation(self):
        """Batch size should sum rows across multiple metadata entries."""
        doc_metadata: list[dict[str, Any]] = [
            {"filename": "a.csv", "rows": 50},
            {"filename": "b.csv", "rows": 100},
        ]
        result = _heuristic_classify(
            "Process all rows",
            has_documents=True,
            doc_metadata=doc_metadata,
        )
        assert result is not None
        assert result.batch_size == 150


# ---------------------------------------------------------------------------
# LLM Classifier
# ---------------------------------------------------------------------------


class TestLLMClassifier:
    """Tests for the LLM-based fallback classifier."""

    @pytest.mark.asyncio
    async def test_llm_classifier_research_query(self):
        """Deep, multi-angle research queries that require plan creation
        and evaluation cycles must be classified as RESEARCH by the LLM.
        """
        response = _make_llm_response(
            mode="research",
            confidence=0.92,
            reasoning="Multi-faceted analysis requiring multiple sources",
            estimated_steps=15,
            requires_iteration=True,
        )
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify(
                "Analyze the competitive landscape of cloud computing "
                "providers and their market positioning strategies"
            )

        assert result is not None
        assert result.mode == ExecutionMode.RESEARCH
        assert result.confidence == 0.92
        assert result.source == "llm"
        assert result.requires_iteration is True
        assert result.estimated_steps == 15
        assert "LLM:" in result.reasoning

    @pytest.mark.asyncio
    async def test_llm_classifier_task_execution(self):
        """Multi-step orchestrated workflows that combine research and
        data processing must be classified as TASK_EXECUTION by the LLM.
        """
        response = _make_llm_response(
            mode="task_execution",
            confidence=0.88,
            reasoning="Multi-phase workflow: research + batch lookup + report",
            estimated_steps=35,
            requires_iteration=True,
            batch_size=50,
        )
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify(
                "Research the top 50 SaaS companies, find their CFOs, "
                "and look up each one in our CRM"
            )

        assert result is not None
        assert result.mode == ExecutionMode.TASK_EXECUTION
        assert result.confidence == 0.88
        assert result.source == "llm"
        assert result.batch_size == 50

    @pytest.mark.asyncio
    async def test_llm_classifier_returns_none_on_timeout(self):
        """LLM classifier must return None when the API call times out."""
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()

        async def slow_create(**kwargs: Any) -> None:
            import asyncio
            await asyncio.sleep(60)

        client.chat.completions.create = slow_create

        with patch("app.openai_factory.get_openai_client", return_value=client):
            with patch("app.agent.classifier._LLM_CLASSIFY_TIMEOUT", 0.01):
                result = await _llm_classify("some query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_classifier_returns_none_on_api_error(self):
        """LLM classifier must return None when the API raises an error."""
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=Exception("API rate limit"),
        )

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify("some query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_classifier_returns_none_on_invalid_mode(self):
        """LLM classifier must return None when the response contains
        an unrecognized mode string.
        """
        response = _make_llm_response(mode="nonexistent_mode")
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify("some query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_classifier_returns_none_on_malformed_json(self):
        """LLM classifier must return None when the response is not valid JSON."""
        message = MagicMock()
        message.content = "This is not JSON at all"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify("some query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_classifier_returns_none_on_empty_content(self):
        """LLM classifier must return None when message content is None."""
        message = MagicMock()
        message.content = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await _llm_classify("some query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_classifier_passes_doc_metadata(self):
        """LLM classifier must include doc_metadata in the system prompt."""
        response = _make_llm_response(mode="data_processing", confidence=0.8)
        client = _mock_openai_client(response)

        doc_metadata = [{"filename": "test.csv", "rows": 100}]

        with patch("app.openai_factory.get_openai_client", return_value=client):
            await _llm_classify(
                "process this data",
                has_documents=True,
                doc_metadata=doc_metadata,
            )

        # Verify the system prompt contained the metadata
        call_kwargs = client.chat.completions.create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        system_content = messages[0]["content"]
        assert "test.csv" in system_content
        assert "100" in system_content


# ---------------------------------------------------------------------------
# Confidence Threshold
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    """Tests for confidence-based classification validation."""

    @pytest.mark.asyncio
    async def test_confidence_below_threshold_raises_error(self):
        """When the LLM classifier returns a confidence score below the
        minimum threshold, classification must raise ClassificationError.
        """
        response = _make_llm_response(
            mode="research",
            confidence=0.3,  # Below 0.5 threshold
            reasoning="Very uncertain classification",
        )
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            with pytest.raises(ClassificationError, match="below threshold"):
                await classify_query(
                    "Tell me about recent market trends for tech companies"
                )

    @pytest.mark.asyncio
    async def test_confidence_at_threshold_passes(self):
        """Confidence exactly at the threshold should be accepted."""
        response = _make_llm_response(
            mode="research",
            confidence=CONFIDENCE_THRESHOLD,
            reasoning="Borderline confidence",
        )
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await classify_query(
                "Tell me about recent market trends for tech companies"
            )

        assert result.mode == ExecutionMode.RESEARCH
        assert result.confidence == CONFIDENCE_THRESHOLD

    @pytest.mark.asyncio
    async def test_both_classifiers_fail_raises_error(self):
        """When both heuristic and LLM classifiers fail, ClassificationError
        must be raised (not a silent default to RESEARCH).
        """
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=Exception("API down"),
        )

        with patch("app.openai_factory.get_openai_client", return_value=client):
            with pytest.raises(ClassificationError, match="failed"):
                await classify_query(
                    "Tell me about some vague topic"
                )

    @pytest.mark.asyncio
    async def test_empty_query_raises_error(self):
        """Empty queries must raise ClassificationError immediately."""
        with pytest.raises(ClassificationError, match="empty"):
            await classify_query("")

        with pytest.raises(ClassificationError, match="empty"):
            await classify_query("   ")


# ---------------------------------------------------------------------------
# Mode Override
# ---------------------------------------------------------------------------


class TestModeOverride:
    """Tests for explicit mode override bypassing classification."""

    @pytest.mark.asyncio
    async def test_mode_override_bypasses_classification(self):
        """When the caller provides an explicit mode override, the classifier
        must be skipped entirely and the specified mode returned directly.
        """
        result = await classify_query(
            "Some ambiguous query that would normally need LLM",
            execution_mode_override="research",
        )

        assert result.mode == ExecutionMode.RESEARCH
        assert result.confidence == 1.0
        assert result.source == "override"
        assert "override" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_mode_override_all_modes(self):
        """Override must work for every valid ExecutionMode."""
        for mode in ExecutionMode:
            result = await classify_query(
                "test query",
                execution_mode_override=mode.value,
            )
            assert result.mode == mode
            assert result.source == "override"

    @pytest.mark.asyncio
    async def test_mode_override_invalid_mode_raises_error(self):
        """An invalid override mode string must raise ClassificationError."""
        with pytest.raises(ClassificationError, match="Invalid execution mode"):
            await classify_query(
                "test query",
                execution_mode_override="nonexistent_mode",
            )

    @pytest.mark.asyncio
    async def test_mode_override_skips_heuristic_and_llm(self):
        """Override must not invoke heuristic or LLM at all."""
        with patch("app.agent.classifier._heuristic_classify") as mock_h, \
             patch("app.agent.classifier._llm_classify") as mock_l:
            result = await classify_query(
                "Reformat this as a table",  # Would match heuristic
                execution_mode_override="research",
            )

        mock_h.assert_not_called()
        mock_l.assert_not_called()
        assert result.mode == ExecutionMode.RESEARCH


# ---------------------------------------------------------------------------
# Integration: classify_query end-to-end flow
# ---------------------------------------------------------------------------


class TestClassifyQueryFlow:
    """Tests for the full classify_query orchestration."""

    @pytest.mark.asyncio
    async def test_heuristic_hit_skips_llm(self):
        """When the heuristic matches, the LLM should never be called."""
        with patch("app.agent.classifier._llm_classify") as mock_llm:
            result = await classify_query("Reformat this as a table")

        mock_llm.assert_not_called()
        assert result.mode == ExecutionMode.FORMAT_ONLY
        assert result.source == "heuristic"

    @pytest.mark.asyncio
    async def test_heuristic_miss_falls_through_to_llm(self):
        """When the heuristic returns None, the LLM classifier is invoked."""
        response = _make_llm_response(mode="research", confidence=0.9)
        client = _mock_openai_client(response)

        with patch("app.openai_factory.get_openai_client", return_value=client):
            result = await classify_query(
                "Analyze the competitive landscape of cloud providers"
            )

        assert result.mode == ExecutionMode.RESEARCH
        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_classify_with_documents_and_csv(self):
        """DATA_PROCESSING classification via heuristic when CSV is present."""
        result = await classify_query(
            "Look up all the names in the spreadsheet",
            has_documents=True,
            doc_metadata=[{"filename": "data.csv", "rows": 200}],
        )
        assert result.mode == ExecutionMode.DATA_PROCESSING
        assert result.batch_size == 200


# ---------------------------------------------------------------------------
# ClassificationResult dataclass
# ---------------------------------------------------------------------------


class TestClassificationResult:
    """Tests for the ClassificationResult dataclass."""

    def test_result_is_frozen(self):
        """ClassificationResult must be immutable."""
        result = ClassificationResult(
            mode=ExecutionMode.RESEARCH,
            confidence=0.9,
            reasoning="test",
            estimated_steps=10,
            requires_iteration=True,
            batch_size=None,
            source="heuristic",
        )
        with pytest.raises(AttributeError):
            result.mode = ExecutionMode.FORMAT_ONLY  # type: ignore[misc]

    def test_result_fields(self):
        """All fields must be accessible and correctly typed."""
        result = ClassificationResult(
            mode=ExecutionMode.DATA_PROCESSING,
            confidence=0.85,
            reasoning="Batch operation detected",
            estimated_steps=20,
            requires_iteration=False,
            batch_size=100,
            source="llm",
        )
        assert result.mode == ExecutionMode.DATA_PROCESSING
        assert result.confidence == 0.85
        assert result.reasoning == "Batch operation detected"
        assert result.estimated_steps == 20
        assert result.requires_iteration is False
        assert result.batch_size == 100
        assert result.source == "llm"

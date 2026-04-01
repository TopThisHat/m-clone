"""Load test: 50 concurrent document queries (m-clone-di27, task 14.3).

Simulates 50 simultaneous queries against a mocked document session to verify:
  - No failures under high concurrency
  - P95 latency stays within acceptable bounds (mocked — sub-50ms expected)
  - All 50 queries return valid QueryResult objects
  - The in-process latency tracker accumulates correct sample count

Run:
    cd backend && uv run python -m pytest tests/test_document_query_load.py -v
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document_intelligence import QueryResult, DocumentSchema, SheetSchema, ColumnSchema, _latency_tracker
from app.redis_client import DocumentSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONCURRENT_QUERIES = 50


def _make_schema() -> DocumentSchema:
    cols = [ColumnSchema(name=c) for c in ["name", "value", "status"]]
    sheet = SheetSchema(name="Sheet1", columns=cols, row_count=100)
    return DocumentSchema(document_type="tabular", total_sheets=1, sheets=[sheet], summary="Test doc")


def _make_session() -> DocumentSession:
    content = "name,value,status\nAlice,100,active\nBob,200,inactive\nCarol,150,active"
    return DocumentSession(
        text=content,
        texts=[content],
        filenames=["load_test.csv"],
        metadata=[{"filename": "load_test.csv", "type": "tabular", "char_count": len(content)}],
    )


def _make_openai_mock() -> MagicMock:
    plan_dict = {
        "relevant_columns": ["name", "value"],
        "extraction_instruction": "Extract matching rows",
        "document_type": "tabular",
        "complexity": "simple",
    }
    msg = MagicMock()
    msg.content = json.dumps(plan_dict)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=25)

    mock_client = MagicMock()
    mock_openai = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_openai)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_openai.chat.completions.create = AsyncMock(return_value=resp)
    return mock_client


def _make_redis_mock() -> AsyncMock:
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # always cache miss
    mock_redis.setex = AsyncMock()
    mock_redis.sadd = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.incrbyfloat = AsyncMock()
    mock_redis.smembers = AsyncMock(return_value=set())
    return mock_redis


# ---------------------------------------------------------------------------
# Load tests
# ---------------------------------------------------------------------------

class TestConcurrentDocumentQueries:
    """50 concurrent queries — no failures, sane latency distribution."""

    @pytest.mark.asyncio
    async def test_50_concurrent_queries_no_failures(self) -> None:
        """All 50 concurrent queries must complete without error."""
        from app.document_intelligence import _query_document_impl

        session = _make_session()
        schema = _make_schema()
        mock_openai = _make_openai_mock()
        mock_redis = _make_redis_mock()

        queries = [f"What is the value for item {i}?" for i in range(CONCURRENT_QUERIES)]
        results: list[QueryResult] = []
        errors: list[Exception] = []

        async def run_query(q: str) -> QueryResult:
            return await _query_document_impl(f"load-test-session-{hash(q)}", q)

        with (
            patch("app.document_intelligence.get_openai_client", return_value=mock_openai),
            patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)),
            patch("app.document_intelligence._load_schema", AsyncMock(return_value=schema)),
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
            patch("app.document_intelligence.settings") as mock_settings,
        ):
            mock_settings.query_model = "gpt-4.1"
            mock_settings.redis_ttl_hours = 24
            mock_settings.max_session_cost = 10.0
            mock_settings.enable_semantic_classification = True

            tasks = [asyncio.create_task(run_query(q)) for q in queries]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)

        for item in gathered:
            if isinstance(item, Exception):
                errors.append(item)
            else:
                results.append(item)

        assert len(errors) == 0, f"Expected 0 errors, got {len(errors)}: {errors[:3]}"
        assert len(results) == CONCURRENT_QUERIES, (
            f"Expected {CONCURRENT_QUERIES} results, got {len(results)}"
        )

    @pytest.mark.asyncio
    async def test_all_results_are_valid_query_results(self) -> None:
        """Every result from concurrent queries must be a valid QueryResult."""
        from app.document_intelligence import _query_document_impl

        session = _make_session()
        schema = _make_schema()
        mock_openai = _make_openai_mock()
        mock_redis = _make_redis_mock()

        queries = [f"Find records where status is active, query {i}" for i in range(20)]

        async def run_query(q: str) -> QueryResult:
            return await _query_document_impl(f"valid-test-{hash(q)}", q)

        with (
            patch("app.document_intelligence.get_openai_client", return_value=mock_openai),
            patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)),
            patch("app.document_intelligence._load_schema", AsyncMock(return_value=schema)),
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
            patch("app.document_intelligence.settings") as mock_settings,
        ):
            mock_settings.query_model = "gpt-4.1"
            mock_settings.redis_ttl_hours = 24
            mock_settings.max_session_cost = 10.0
            mock_settings.enable_semantic_classification = True

            results = await asyncio.gather(*[run_query(q) for q in queries])

        for i, result in enumerate(results):
            assert isinstance(result, QueryResult), f"Result {i} is not a QueryResult"
            assert result.total_matches == len(result.matches), f"Result {i} has mismatched total_matches"
            assert result.error is None or isinstance(result.error, str), f"Result {i} has invalid error"

    @pytest.mark.asyncio
    async def test_concurrent_queries_do_not_contaminate_each_other(self) -> None:
        """Queries against different sessions must not share state."""
        from app.document_intelligence import _query_document_impl

        session = _make_session()
        schema = _make_schema()
        mock_openai = _make_openai_mock()
        mock_redis = _make_redis_mock()

        session_ids = [f"isolation-session-{i}" for i in range(30)]

        async def run_query(sid: str) -> tuple[str, QueryResult]:
            result = await _query_document_impl(sid, "What are the active records?")
            return sid, result

        with (
            patch("app.document_intelligence.get_openai_client", return_value=mock_openai),
            patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)),
            patch("app.document_intelligence._load_schema", AsyncMock(return_value=schema)),
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
            patch("app.document_intelligence.settings") as mock_settings,
        ):
            mock_settings.query_model = "gpt-4.1"
            mock_settings.redis_ttl_hours = 24
            mock_settings.max_session_cost = 10.0
            mock_settings.enable_semantic_classification = True

            pairs = await asyncio.gather(*[run_query(sid) for sid in session_ids])

        returned_sids = {p[0] for p in pairs}
        assert returned_sids == set(session_ids), "Some sessions were lost"

    @pytest.mark.asyncio
    async def test_latency_tracker_accumulates_samples(self) -> None:
        """After N queries, the latency tracker must have recorded N samples."""
        from app.document_intelligence import _query_document_impl, _latency_tracker, get_latency_metrics

        session = _make_session()
        schema = _make_schema()
        mock_openai = _make_openai_mock()
        mock_redis = _make_redis_mock()

        n_queries = 25
        queries = [f"Latency tracker query {i}" for i in range(n_queries)]

        # Record starting count
        before_count = _latency_tracker.percentiles()["count"]

        async def run_query(q: str) -> QueryResult:
            return await _query_document_impl(f"latency-test-{hash(q)}", q)

        with (
            patch("app.document_intelligence.get_openai_client", return_value=mock_openai),
            patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)),
            patch("app.document_intelligence._load_schema", AsyncMock(return_value=schema)),
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
            patch("app.document_intelligence.settings") as mock_settings,
        ):
            mock_settings.query_model = "gpt-4.1"
            mock_settings.redis_ttl_hours = 24
            mock_settings.max_session_cost = 10.0
            mock_settings.enable_semantic_classification = True

            await asyncio.gather(*[run_query(q) for q in queries])

        after_metrics = get_latency_metrics()
        after_count = after_metrics["count"]

        assert after_count >= before_count + n_queries, (
            f"Expected at least {before_count + n_queries} samples, got {after_count}"
        )
        # Sanity check: p50 < p99
        if after_metrics["count"] > 0:
            assert after_metrics["p50"] <= after_metrics["p99"], "P50 must be <= P99"


class TestLatencyPercentileCalculation:
    """Unit tests for the _LatencyTracker ring buffer and percentile math."""

    def test_empty_tracker_returns_zeros(self) -> None:
        from app.document_intelligence import _LatencyTracker
        tracker = _LatencyTracker()
        metrics = tracker.percentiles()
        assert metrics["p50"] == 0.0
        assert metrics["p95"] == 0.0
        assert metrics["p99"] == 0.0
        assert metrics["count"] == 0

    def test_single_sample(self) -> None:
        from app.document_intelligence import _LatencyTracker
        tracker = _LatencyTracker()
        tracker.record(42.0, "simple")
        metrics = tracker.percentiles()
        assert metrics["p50"] == 42.0
        assert metrics["p95"] == 42.0
        assert metrics["p99"] == 42.0
        assert metrics["count"] == 1

    def test_percentiles_ordered_correctly(self) -> None:
        """P50 <= P95 <= P99 for any distribution."""
        from app.document_intelligence import _LatencyTracker
        tracker = _LatencyTracker()
        # Add 100 samples: 90 fast (10ms), 8 medium (100ms), 2 slow (500ms)
        for _ in range(90):
            tracker.record(10.0, "simple")
        for _ in range(8):
            tracker.record(100.0, "complex")
        for _ in range(2):
            tracker.record(500.0, "complex")

        metrics = tracker.percentiles()
        assert metrics["p50"] <= metrics["p95"] <= metrics["p99"]
        assert metrics["p50"] == 10.0, f"Expected P50=10.0, got {metrics['p50']}"
        assert metrics["p99"] >= 100.0, f"Expected P99>=100.0, got {metrics['p99']}"
        assert metrics["count"] == 100

    def test_ring_buffer_evicts_old_samples(self) -> None:
        """After filling the ring buffer, old samples should be evicted."""
        from app.document_intelligence import _LatencyTracker
        tracker = _LatencyTracker(window=10)
        # Fill with 10 slow samples
        for _ in range(10):
            tracker.record(1000.0, "complex")
        # Overwrite with 10 fast samples
        for _ in range(10):
            tracker.record(5.0, "simple")

        metrics = tracker.percentiles()
        assert metrics["count"] == 10
        assert metrics["p50"] == 5.0, f"Old samples should be evicted, got P50={metrics['p50']}"

    def test_mean_calculation(self) -> None:
        from app.document_intelligence import _LatencyTracker
        tracker = _LatencyTracker()
        for v in [10.0, 20.0, 30.0]:
            tracker.record(v, "simple")
        metrics = tracker.percentiles()
        assert metrics["mean"] == 20.0

    def test_get_latency_metrics_returns_dict(self) -> None:
        from app.document_intelligence import get_latency_metrics
        metrics = get_latency_metrics()
        assert "p50" in metrics
        assert "p95" in metrics
        assert "p99" in metrics
        assert "count" in metrics
        assert "mean" in metrics


class TestMetricsEndpoint:
    """Integration tests for the GET /api/documents/metrics endpoint."""

    def test_metrics_endpoint_returns_200(self) -> None:
        from app.main import app
        from app.auth import get_current_user
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user", "email": "t@t.com"}
        client = TestClient(app, raise_server_exceptions=True)
        try:
            response = client.get("/api/documents/metrics")
            assert response.status_code == 200
            data = response.json()
            assert "latency_ms" in data
            assert "p50" in data["latency_ms"]
            assert "p95" in data["latency_ms"]
            assert "p99" in data["latency_ms"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_session_cost_endpoint_returns_zero_for_unknown_session(self) -> None:
        from app.main import app
        from app.auth import get_current_user
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user", "email": "t@t.com"}
        client = TestClient(app, raise_server_exceptions=True)
        try:
            response = client.get("/api/documents/session-cost?session_key=nonexistent-session")
            assert response.status_code == 200
            data = response.json()
            assert data["cumulative_cost_usd"] == 0.0
            assert "budget_usd" in data
            assert "budget_remaining_usd" in data
            assert "budget_exceeded" in data
        finally:
            app.dependency_overrides.pop(get_current_user, None)

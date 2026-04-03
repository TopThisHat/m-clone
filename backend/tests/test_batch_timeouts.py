"""Tests for batch timeout handling in app.agent.batch_resolver.

Validates per-call and overall batch timeout behavior introduced by
the TalkToMe prompt-hardening spec (m-clone-v936, Sprint 1).

Per-call timeouts ensure a single slow resolve_client call does not
block the entire batch. Overall batch timeouts ensure partial results
are returned when the total wall-clock time exceeds the configured limit.

Coverage:
  - Per-call timeout records error status on the timed-out entry
  - Per-call timeout does not affect other concurrent calls
  - Overall batch timeout returns partial results
  - Overall batch timeout sets remaining entries to timeout error status

Run: cd backend && uv run python -m pytest tests/test_batch_timeouts.py -v
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import app.agent.batch_resolver as br
from app.agent.batch_resolver import batch_resolve_clients


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeLookupResult:
    """Minimal stand-in for LookupResult from client_resolver."""
    match_found: bool
    gwm_id: str | None = None
    confidence: float | None = None


async def _fast_resolve(name: str, company: str | None = None) -> FakeLookupResult:
    """Instant mock resolve that always matches."""
    return FakeLookupResult(match_found=True, gwm_id="GWM-FAST", confidence=0.95)


# ---------------------------------------------------------------------------
# Per-Call Timeout
# ---------------------------------------------------------------------------

class TestPerCallTimeout:
    """Verify that individual slow calls time out gracefully."""

    @pytest.mark.asyncio
    async def test_per_call_timeout_records_error(self):
        """When a single resolve_client call exceeds the per-call timeout,
        that entry must have status='error' with a message indicating
        a timeout occurred. The entry must still appear in the results
        (not silently dropped).

        Spec ref: m-clone-v936, per-call timeout behavior.
        """
        call_count = 0

        async def slow_for_one(name: str, company: str | None = None):
            nonlocal call_count
            call_count += 1
            if "Slow" in name:
                # Sleep longer than _PER_CALL_TIMEOUT (10s)
                await asyncio.sleep(20)
                return FakeLookupResult(match_found=True, gwm_id="GWM-SLOW", confidence=0.9)
            return FakeLookupResult(match_found=True, gwm_id="GWM-FAST", confidence=0.95)

        people = [
            {"name": "Slow Person"},
            {"name": "Fast Person"},
        ]

        with patch("app.agent.batch_resolver.resolve_client", side_effect=slow_for_one):
            results = await batch_resolve_clients(people)

        assert len(results) == 2

        # Find the slow entry
        slow_result = next(r for r in results if r["name"] == "Slow Person")
        assert slow_result["status"] == "error"
        assert "timed out" in slow_result["error"].lower()
        assert slow_result["gwm_id"] is None

    @pytest.mark.asyncio
    async def test_per_call_timeout_other_calls_continue(self):
        """When one call times out, the remaining calls in the batch must
        continue to execute and return their results normally. The timeout
        of one entry must not cancel or block other concurrent entries.

        Spec ref: m-clone-v936, fault isolation in batch processing.
        """
        async def slow_for_first(name: str, company: str | None = None):
            if "Slow" in name:
                await asyncio.sleep(20)  # exceeds _PER_CALL_TIMEOUT
                return FakeLookupResult(match_found=True, gwm_id="GWM-SLOW", confidence=0.9)
            # Fast calls succeed immediately
            await asyncio.sleep(0.01)
            return FakeLookupResult(match_found=True, gwm_id=f"GWM-{name.upper()}", confidence=0.92)

        people = [
            {"name": "Slow Person"},
            {"name": "Alice"},
            {"name": "Bob"},
        ]

        with patch("app.agent.batch_resolver.resolve_client", side_effect=slow_for_first):
            results = await batch_resolve_clients(people)

        assert len(results) == 3

        # Slow person timed out
        slow_result = next(r for r in results if r["name"] == "Slow Person")
        assert slow_result["status"] == "error"

        # Other calls should have succeeded
        alice_result = next(r for r in results if r["name"] == "Alice")
        assert alice_result["status"] == "matched"
        assert alice_result["gwm_id"] is not None

        bob_result = next(r for r in results if r["name"] == "Bob")
        assert bob_result["status"] == "matched"
        assert bob_result["gwm_id"] is not None


# ---------------------------------------------------------------------------
# Overall Batch Timeout
# ---------------------------------------------------------------------------

class TestOverallBatchTimeout:
    """Verify that the overall batch timeout returns partial results."""

    @pytest.mark.asyncio
    async def test_overall_batch_timeout_partial_results(self):
        """When the total batch processing time exceeds the overall timeout,
        all entries that have completed so far must be returned with their
        actual status. The function must not raise an exception or return
        an empty result.

        Spec ref: m-clone-v936, overall batch timeout — partial results.
        """
        async def very_slow_resolve(name: str, company: str | None = None):
            await asyncio.sleep(5)  # each call takes 5s
            return FakeLookupResult(match_found=True, gwm_id="GWM-SLOW", confidence=0.9)

        people = [{"name": f"Person {i}"} for i in range(5)]

        # Set a very short overall batch timeout so it fires before all complete
        original_timeout = br._BATCH_TIMEOUT
        br._BATCH_TIMEOUT = 1.0
        try:
            with patch("app.agent.batch_resolver.resolve_client", side_effect=very_slow_resolve):
                results = await batch_resolve_clients(people)
        finally:
            br._BATCH_TIMEOUT = original_timeout

        # All 5 entries must be present (no silent drops)
        assert len(results) == 5

        # The function should not raise — it returns results for all entries
        # Some or all should have error status due to the batch timeout
        error_results = [r for r in results if r["status"] == "error"]
        assert len(error_results) > 0, "Expected at least some entries to have error status"

    @pytest.mark.asyncio
    async def test_overall_batch_timeout_error_messages(self):
        """Entries that did not complete before the overall batch timeout
        must have status='error' and an error message indicating that the
        batch timed out before their resolution could complete.

        Spec ref: m-clone-v936, overall batch timeout — error annotation.
        """
        async def very_slow_resolve(name: str, company: str | None = None):
            await asyncio.sleep(5)  # each call takes 5s
            return FakeLookupResult(match_found=True, gwm_id="GWM-SLOW", confidence=0.9)

        people = [{"name": f"Person {i}"} for i in range(5)]

        original_timeout = br._BATCH_TIMEOUT
        br._BATCH_TIMEOUT = 1.0
        try:
            with patch("app.agent.batch_resolver.resolve_client", side_effect=very_slow_resolve):
                results = await batch_resolve_clients(people)
        finally:
            br._BATCH_TIMEOUT = original_timeout

        # All entries must be present
        assert len(results) == 5

        # Timed-out entries must have descriptive error messages
        error_results = [r for r in results if r["status"] == "error"]
        for r in error_results:
            assert r["error"] is not None
            assert "timed out" in r["error"].lower()
            assert r["gwm_id"] is None
            assert r["confidence"] is None

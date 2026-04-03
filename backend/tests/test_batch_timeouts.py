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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.batch_resolver import batch_resolve_clients


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


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
        pytest.skip("Sprint 3: implementation pending")

    @pytest.mark.asyncio
    async def test_per_call_timeout_other_calls_continue(self):
        """When one call times out, the remaining calls in the batch must
        continue to execute and return their results normally. The timeout
        of one entry must not cancel or block other concurrent entries.

        Spec ref: m-clone-v936, fault isolation in batch processing.
        """
        pytest.skip("Sprint 3: implementation pending")


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
        pytest.skip("Sprint 3: implementation pending")

    @pytest.mark.asyncio
    async def test_overall_batch_timeout_error_messages(self):
        """Entries that did not complete before the overall batch timeout
        must have status='error' and an error message indicating that the
        batch timed out before their resolution could complete.

        Spec ref: m-clone-v936, overall batch timeout — error annotation.
        """
        pytest.skip("Sprint 3: implementation pending")

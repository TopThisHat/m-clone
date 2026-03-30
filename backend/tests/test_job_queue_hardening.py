"""
Unit tests for PG job queue status guards and hardening.

Covers:
  1. dequeue() returns post-update state — status='claimed' in returned dicts
  2. mark_running() returns False when job is not in 'claimed' state
  3. mark_running() returns True when job is in 'claimed' state
  4. ack() returns False when job is not in 'running' state
  5. ack() returns True when job is in 'running' state
  6. reclaim_stale() uses FOR UPDATE SKIP LOCKED to avoid racing dequeue
  7. dequeue() SQL filters by known job_type values (job_type = ANY)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# Unit tests — no database connection needed
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class AsyncContextManager:
    """Mock for `async with pool.acquire() as conn:` pattern."""
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


def _make_pool(conn):
    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=AsyncContextManager(conn))
    return mock_pool


# ---------------------------------------------------------------------------
# 1. dequeue() returns post-update state with status='claimed'
# ---------------------------------------------------------------------------

class TestDequeueReturnsClaimedStatus:
    @pytest.mark.asyncio
    async def test_returned_dicts_have_status_claimed(self):
        """dequeue() returns dicts with status='claimed' from UPDATE RETURNING."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"id": "aaa", "job_type": "validation_campaign", "status": "claimed"},
        ])
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import dequeue
            results = await dequeue("worker-1")

        assert len(results) == 1
        assert results[0]["status"] == "claimed"

    @pytest.mark.asyncio
    async def test_dequeue_sql_uses_update_returning(self):
        """dequeue() issues a single UPDATE ... RETURNING * statement."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import dequeue
            await dequeue("worker-1")

        sql = mock_conn.fetch.call_args.args[0]
        assert "UPDATE" in sql.upper()
        assert "RETURNING" in sql.upper()
        # Must NOT be a separate SELECT followed by UPDATE
        assert mock_conn.execute.call_count == 0  # no separate UPDATE execute call

    @pytest.mark.asyncio
    async def test_dequeue_sql_filters_known_job_types(self):
        """dequeue() query includes AND job_type = ANY(...) filter."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import dequeue
            await dequeue("worker-1")

        sql = mock_conn.fetch.call_args.args[0]
        assert "job_type" in sql
        assert "ANY" in sql.upper()

    @pytest.mark.asyncio
    async def test_dequeue_sql_uses_skip_locked(self):
        """dequeue() inner SELECT uses FOR UPDATE SKIP LOCKED."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import dequeue
            await dequeue("worker-1")

        sql = mock_conn.fetch.call_args.args[0]
        assert "SKIP LOCKED" in sql.upper()


# ---------------------------------------------------------------------------
# 2 & 3. mark_running() status guard
# ---------------------------------------------------------------------------

class TestMarkRunningStatusGuard:
    @pytest.mark.asyncio
    async def test_returns_true_when_job_was_claimed(self):
        """mark_running() returns True when UPDATE matched a 'claimed' row."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import mark_running
            result = await mark_running("job-id-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_job_not_claimed(self):
        """mark_running() returns False when no row was updated (job already reclaimed)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import mark_running
            result = await mark_running("job-id-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_sql_includes_and_status_claimed_guard(self):
        """mark_running() SQL includes AND status = 'claimed' guard."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import mark_running
            await mark_running("job-id-1")

        sql = mock_conn.execute.call_args.args[0]
        assert "status = 'claimed'" in sql


# ---------------------------------------------------------------------------
# 4 & 5. ack() status guard
# ---------------------------------------------------------------------------

class TestAckStatusGuard:
    @pytest.mark.asyncio
    async def test_returns_true_when_job_was_running(self):
        """ack() returns True when UPDATE matched a 'running' row."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import ack
            result = await ack("job-id-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_job_not_running(self):
        """ack() returns False when no row updated (job not in 'running' state)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import ack
            result = await ack("job-id-1")

        assert result is False

    @pytest.mark.asyncio
    async def test_sql_includes_and_status_running_guard(self):
        """ack() SQL includes AND status = 'running' guard."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import ack
            await ack("job-id-1")

        sql = mock_conn.execute.call_args.args[0]
        assert "status = 'running'" in sql


# ---------------------------------------------------------------------------
# 6. reclaim_stale() uses SKIP LOCKED
# ---------------------------------------------------------------------------

class TestReclaimStaleSkipLocked:
    @pytest.mark.asyncio
    async def test_sql_uses_skip_locked(self):
        """reclaim_stale() query uses FOR UPDATE SKIP LOCKED to avoid racing dequeue."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock()
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import reclaim_stale
            await reclaim_stale(600)

        sql = mock_conn.fetch.call_args.args[0]
        assert "SKIP LOCKED" in sql.upper()

    @pytest.mark.asyncio
    async def test_sql_uses_cte_pattern(self):
        """reclaim_stale() uses a CTE (WITH stale AS ...) to lock and update atomically."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.execute = AsyncMock()
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import reclaim_stale
            await reclaim_stale(600)

        sql = mock_conn.fetch.call_args.args[0]
        # Should be a CTE + UPDATE (not a simple UPDATE)
        assert "WITH" in sql.upper()
        assert "UPDATE" in sql.upper()

    @pytest.mark.asyncio
    async def test_returns_count_of_reclaimed_jobs(self):
        """reclaim_stale() returns the number of rows reclaimed."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"id": "id1", "job_type": "validation_pair", "old_worker": "worker-1"},
            {"id": "id2", "job_type": "validation_pair", "old_worker": "worker-2"},
        ])
        mock_conn.execute = AsyncMock()
        mock_pool = _make_pool(mock_conn)

        with patch("app.job_queue._get_pool", new=AsyncMock(return_value=mock_pool)):
            from app.job_queue import reclaim_stale
            count = await reclaim_stale(600)

        assert count == 2

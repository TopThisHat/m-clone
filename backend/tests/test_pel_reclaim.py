"""
Unit tests for XAUTOCLAIM PEL (Pending Entry List) reclaim logic.

Covers:
  1. Reclaimed messages are passed to _process_message pipeline
  2. Reclaim count is logged at INFO level
  3. No messages reclaimed → _process_message not called, no log
  4. _reclaim_pel_loop uses correct XAUTOCLAIM parameters
  5. Loop continues after a recoverable error (exception handling)
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# Unit tests — no database connection needed
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


def _make_consumer(streams=("test:stream",)):
    """Create a WorkflowConsumer with the shutdown event already set (single-iteration)."""
    from worker.consumer import WorkflowConsumer
    consumer = WorkflowConsumer(streams=list(streams))
    return consumer


async def _run_one_pel_iteration(consumer, mock_redis, *, stream="test:stream"):
    """
    Drive _reclaim_pel_loop through exactly one XAUTOCLAIM iteration by
    controlling asyncio.sleep: first call does nothing, second call sets shutdown.
    """
    sleep_calls = 0

    async def controlled_sleep(delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            consumer._shutdown.set()
        # No actual sleep — return immediately

    with (
        patch("asyncio.sleep", side_effect=controlled_sleep),
        patch("app.streams.get_redis", new=AsyncMock(return_value=mock_redis)),
    ):
        await consumer._reclaim_pel_loop(stream)


# ---------------------------------------------------------------------------
# 1. Reclaimed messages routed through _process_message
# ---------------------------------------------------------------------------

class TestPelReclaimProcessing:
    @pytest.mark.asyncio
    async def test_reclaimed_messages_dispatched_to_process_message(self):
        """Messages returned by XAUTOCLAIM are dispatched to _process_message."""
        consumer = _make_consumer()

        reclaimed_msgs = [
            ("1234-0", {"job_id": "job-1", "job_type": "validation_pair"}),
            ("1235-0", {"job_id": "job-2", "job_type": "validation_campaign"}),
        ]

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(
            return_value=("0-0", reclaimed_msgs, [])
        )

        processed = []

        async def capture_process(stream, msg_id, fields):
            processed.append((msg_id, fields))

        with patch.object(consumer, "_process_message", side_effect=capture_process):
            await _run_one_pel_iteration(consumer, mock_redis)

        # Allow spawned tasks to complete
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(processed) == 2
        assert processed[0][0] == "1234-0"
        assert processed[1][0] == "1235-0"

    @pytest.mark.asyncio
    async def test_no_reclaimed_messages_means_no_processing(self):
        """When XAUTOCLAIM returns empty list, _process_message is never called."""
        consumer = _make_consumer()

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))

        with patch.object(consumer, "_process_message", new=AsyncMock()) as mock_process:
            await _run_one_pel_iteration(consumer, mock_redis)

        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_reclaimed_message_includes_correct_stream(self):
        """_process_message receives the stream name that XAUTOCLAIM ran on."""
        stream = "jobs:validation_pair"
        consumer = _make_consumer(streams=[stream])

        reclaimed_msgs = [
            ("1234-0", {"job_id": "job-abc", "job_type": "validation_pair"}),
        ]
        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", reclaimed_msgs, []))

        call_args = []

        async def capture_args(s, msg_id, fields):
            call_args.append((s, msg_id, fields))

        with patch.object(consumer, "_process_message", side_effect=capture_args):
            await _run_one_pel_iteration(consumer, mock_redis, stream=stream)

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(call_args) == 1
        assert call_args[0][0] == stream  # stream passed correctly


# ---------------------------------------------------------------------------
# 2. INFO logging of reclaim count
# ---------------------------------------------------------------------------

class TestPelReclaimLogging:
    @pytest.mark.asyncio
    async def test_logs_info_when_messages_reclaimed(self, caplog):
        """INFO logged with count and stream name when messages are reclaimed."""
        consumer = _make_consumer(streams=["jobs:validation_pair"])

        reclaimed_msgs = [
            ("1000-0", {"job_id": "j1", "job_type": "validation_pair"}),
            ("1001-0", {"job_id": "j2", "job_type": "validation_pair"}),
            ("1002-0", {"job_id": "j3", "job_type": "validation_pair"}),
        ]
        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", reclaimed_msgs, []))

        with patch.object(consumer, "_process_message", new=AsyncMock()):
            with caplog.at_level(logging.INFO, logger="worker.consumer"):
                await _run_one_pel_iteration(
                    consumer, mock_redis, stream="jobs:validation_pair"
                )

        log_messages = [r.message for r in caplog.records]
        matching = [m for m in log_messages if "Reclaimed" in m and "XAUTOCLAIM" in m]
        assert matching, f"Expected INFO log about PEL reclaim, got: {log_messages}"
        assert "3" in matching[0]
        assert "jobs:validation_pair" in matching[0]

    @pytest.mark.asyncio
    async def test_no_log_when_no_messages_reclaimed(self, caplog):
        """No reclaim INFO log when XAUTOCLAIM returns empty results."""
        consumer = _make_consumer()

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))

        with caplog.at_level(logging.INFO, logger="worker.consumer"):
            await _run_one_pel_iteration(consumer, mock_redis)

        reclaim_logs = [r for r in caplog.records if "Reclaimed" in r.message]
        assert not reclaim_logs, "Should not log when nothing was reclaimed"


# ---------------------------------------------------------------------------
# 3. XAUTOCLAIM called with correct parameters
# ---------------------------------------------------------------------------

class TestPelReclaimParameters:
    @pytest.mark.asyncio
    async def test_xautoclaim_called_with_correct_stream_and_group(self):
        """XAUTOCLAIM is called with the right stream and consumer group."""
        consumer = _make_consumer(streams=["jobs:validation_pair"])

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))

        with patch.object(consumer, "_process_message", new=AsyncMock()):
            await _run_one_pel_iteration(
                consumer, mock_redis, stream="jobs:validation_pair"
            )

        from app.streams import GROUP_WORKERS
        call_kwargs = mock_redis.xautoclaim.call_args

        # Positional: stream, group, consumer_name
        assert call_kwargs.args[0] == "jobs:validation_pair"
        assert call_kwargs.args[1] == GROUP_WORKERS
        assert call_kwargs.args[2] == consumer._consumer_name

    @pytest.mark.asyncio
    async def test_xautoclaim_uses_5_minute_idle_threshold(self):
        """XAUTOCLAIM min_idle_time is 300,000ms (5 minutes)."""
        consumer = _make_consumer()

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))

        await _run_one_pel_iteration(consumer, mock_redis)

        call_kwargs = mock_redis.xautoclaim.call_args
        assert call_kwargs.kwargs.get("min_idle_time") == 300_000, (
            f"Expected min_idle_time=300000 (5 min), got {call_kwargs.kwargs}"
        )

    @pytest.mark.asyncio
    async def test_xautoclaim_starts_from_beginning_of_pel(self):
        """XAUTOCLAIM starts from '0-0' to check all PEL entries."""
        consumer = _make_consumer()

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))

        await _run_one_pel_iteration(consumer, mock_redis)

        call_kwargs = mock_redis.xautoclaim.call_args
        assert call_kwargs.kwargs.get("start_id") == "0-0", (
            f"Expected start_id='0-0', got {call_kwargs.kwargs}"
        )


# ---------------------------------------------------------------------------
# 4. Error resilience — loop continues after recoverable errors
# ---------------------------------------------------------------------------

class TestPelReclaimErrorHandling:
    @pytest.mark.asyncio
    async def test_recoverable_error_does_not_crash_loop(self):
        """Exception during XAUTOCLAIM is caught and loop continues."""
        consumer = _make_consumer()

        sleep_calls = 0

        async def controlled_sleep(delay):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                consumer._shutdown.set()

        mock_redis = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(
            side_effect=[
                Exception("transient Redis error"),  # First iteration fails
                ("0-0", [], []),                      # Second iteration succeeds
            ]
        )

        with (
            patch("asyncio.sleep", side_effect=controlled_sleep),
            patch("app.streams.get_redis", new=AsyncMock(return_value=mock_redis)),
        ):
            # Should not raise — errors are caught and loop retries
            await consumer._reclaim_pel_loop("test:stream")

        # Both iterations should have been attempted
        assert mock_redis.xautoclaim.call_count == 2

    @pytest.mark.asyncio
    async def test_cancelled_error_exits_loop(self):
        """asyncio.CancelledError exits the loop cleanly without error logging."""
        consumer = _make_consumer()

        async def immediate_cancel(delay):
            raise asyncio.CancelledError()

        mock_redis = AsyncMock()

        with (
            patch("asyncio.sleep", side_effect=immediate_cancel),
            patch("app.streams.get_redis", new=AsyncMock(return_value=mock_redis)),
        ):
            # Should return cleanly without raising
            await consumer._reclaim_pel_loop("test:stream")

        # xautoclaim never called — cancelled before it could run
        mock_redis.xautoclaim.assert_not_called()

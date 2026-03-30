"""
Integration tests for the end-to-end dispatch → worker lifecycle.

Tests the full PG job queue state machine:
  enqueue → dequeue (status='claimed') → mark_running → ack (status='done')

Requires a running PostgreSQL instance (docker compose up -d).

Run: cd backend && uv run python -m pytest tests/test_dispatch_integration.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def dispatched_job():
    """Enqueue a test job and yield its ID. Cleans up regardless of test outcome."""
    from app.job_queue import enqueue

    job_id = await enqueue(
        "validation_campaign",
        {"_test": True, "run_id": uuid.uuid4().hex},
        priority=999,  # Highest priority so it's dequeued first
    )
    yield job_id
    # Cleanup: delete regardless of final status
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.job_queue WHERE id = $1::uuid",
            job_id,
        )


# ---------------------------------------------------------------------------
# Dequeue returns claimed status
# ---------------------------------------------------------------------------

class TestDequeueClaimedStatus:
    @pytest.mark.asyncio
    async def test_dequeue_returns_status_claimed(self, dispatched_job):
        """dequeue() returns dicts with status='claimed' (UPDATE RETURNING result)."""
        from app.job_queue import dequeue

        worker_id = f"test-dispatcher-{uuid.uuid4().hex[:8]}"
        jobs = await dequeue(worker_id, batch_size=100)

        our_job = next((j for j in jobs if str(j["id"]) == dispatched_job), None)
        assert our_job is not None, f"Job {dispatched_job} not found in dequeue results"
        assert our_job["status"] == "claimed", (
            f"Expected status='claimed' from dequeue RETURNING, got {our_job['status']!r}"
        )

    @pytest.mark.asyncio
    async def test_dequeue_sets_worker_id_in_returned_dict(self, dispatched_job):
        """dequeue() returned dict includes the worker_id that claimed the job."""
        from app.job_queue import dequeue

        worker_id = f"test-dispatcher-{uuid.uuid4().hex[:8]}"
        jobs = await dequeue(worker_id, batch_size=100)

        our_job = next((j for j in jobs if str(j["id"]) == dispatched_job), None)
        assert our_job is not None
        assert our_job["worker_id"] == worker_id

    @pytest.mark.asyncio
    async def test_dequeued_job_not_returned_a_second_time(self, dispatched_job):
        """A claimed job is not returned by a subsequent dequeue call."""
        from app.job_queue import dequeue

        worker_id_1 = f"test-worker-a-{uuid.uuid4().hex[:8]}"
        worker_id_2 = f"test-worker-b-{uuid.uuid4().hex[:8]}"

        first_batch = await dequeue(worker_id_1, batch_size=100)
        assert any(str(j["id"]) == dispatched_job for j in first_batch)

        second_batch = await dequeue(worker_id_2, batch_size=100)
        assert not any(str(j["id"]) == dispatched_job for j in second_batch), (
            "Claimed job should not be returned by a second dequeue"
        )

    @pytest.mark.asyncio
    async def test_unknown_job_type_not_dequeued(self):
        """Jobs with unknown job_type are filtered out by dequeue()."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.job_queue
                    (job_type, payload, max_attempts, priority, run_at)
                VALUES ('unknown_type', '{}', 3, 0, NOW())
                RETURNING id
                """
            )
            unknown_job_id = str(row["id"])

        try:
            from app.job_queue import dequeue
            worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
            jobs = await dequeue(worker_id, batch_size=100)

            assert not any(str(j["id"]) == unknown_job_id for j in jobs), (
                "Job with unknown job_type should not be dequeued"
            )
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.job_queue WHERE id = $1::uuid", unknown_job_id
                )


# ---------------------------------------------------------------------------
# mark_running() status guard
# ---------------------------------------------------------------------------

class TestMarkRunningStatusGuard:
    @pytest.mark.asyncio
    async def test_mark_running_returns_true_for_claimed_job(self, dispatched_job):
        """mark_running() returns True when job is in 'claimed' state."""
        from app.job_queue import dequeue, mark_running

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
        jobs = await dequeue(worker_id, batch_size=100)
        our_job = next((j for j in jobs if str(j["id"]) == dispatched_job), None)
        assert our_job is not None, "Job must be dequeued first"

        result = await mark_running(dispatched_job)
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_running_returns_false_for_pending_job(self, dispatched_job):
        """mark_running() returns False when job is still 'pending' (not claimed)."""
        from app.job_queue import mark_running

        # Job is still in 'pending' state — not yet dequeued
        result = await mark_running(dispatched_job)
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_running_returns_false_after_already_running(self, dispatched_job):
        """mark_running() returns False when called twice (second call: not 'claimed')."""
        from app.job_queue import dequeue, mark_running

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
        await dequeue(worker_id, batch_size=100)

        first = await mark_running(dispatched_job)
        assert first is True

        second = await mark_running(dispatched_job)
        assert second is False


# ---------------------------------------------------------------------------
# ack() status guard
# ---------------------------------------------------------------------------

class TestAckStatusGuard:
    @pytest.mark.asyncio
    async def test_ack_returns_true_for_running_job(self, dispatched_job):
        """ack() returns True when job is in 'running' state."""
        from app.job_queue import ack, dequeue, mark_running

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
        await dequeue(worker_id, batch_size=100)
        await mark_running(dispatched_job)

        result = await ack(dispatched_job)
        assert result is True

    @pytest.mark.asyncio
    async def test_ack_returns_false_for_claimed_job(self, dispatched_job):
        """ack() returns False when job is 'claimed' but not yet 'running'."""
        from app.job_queue import ack, dequeue

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
        await dequeue(worker_id, batch_size=100)
        # Job is now 'claimed', not 'running'

        result = await ack(dispatched_job)
        assert result is False

    @pytest.mark.asyncio
    async def test_ack_returns_false_for_pending_job(self, dispatched_job):
        """ack() returns False when job is still 'pending'."""
        from app.job_queue import ack

        result = await ack(dispatched_job)
        assert result is False


# ---------------------------------------------------------------------------
# Full lifecycle: enqueue → dequeue → mark_running → ack
# ---------------------------------------------------------------------------

class TestFullDispatchLifecycle:
    @pytest.mark.asyncio
    async def test_job_reaches_done_via_full_lifecycle(self, dispatched_job):
        """
        Full PG lifecycle: pending → claimed → running → done.
        Simulates dispatcher dequeue + worker execution.
        """
        from app.job_queue import ack, dequeue, mark_running

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"

        # Step 1: Dispatcher dequeues the job
        jobs = await dequeue(worker_id, batch_size=100)
        our_job = next((j for j in jobs if str(j["id"]) == dispatched_job), None)
        assert our_job is not None
        assert our_job["status"] == "claimed"

        # Step 2: Worker marks it running
        running = await mark_running(dispatched_job)
        assert running is True

        # Verify PG state
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM playbook.job_queue WHERE id = $1::uuid",
                dispatched_job,
            )
        assert row["status"] == "running"

        # Step 3: Worker acks completion
        done = await ack(dispatched_job)
        assert done is True

        # Verify final PG state
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM playbook.job_queue WHERE id = $1::uuid",
                dispatched_job,
            )
        assert row["status"] == "done"

    @pytest.mark.asyncio
    async def test_job_status_is_claimed_immediately_after_dequeue(self, dispatched_job):
        """PG status transitions to 'claimed' during dequeue (verified via direct DB read)."""
        from app.job_queue import dequeue

        # Verify it starts as 'pending'
        async with _acquire() as conn:
            before = await conn.fetchrow(
                "SELECT status FROM playbook.job_queue WHERE id = $1::uuid",
                dispatched_job,
            )
        assert before["status"] == "pending"

        worker_id = f"test-worker-{uuid.uuid4().hex[:8]}"
        await dequeue(worker_id, batch_size=100)

        # Verify status transitioned to 'claimed' in PG
        async with _acquire() as conn:
            after = await conn.fetchrow(
                "SELECT status FROM playbook.job_queue WHERE id = $1::uuid",
                dispatched_job,
            )
        assert after["status"] == "claimed"

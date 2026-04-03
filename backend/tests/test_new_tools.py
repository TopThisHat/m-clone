"""Tests for Sprint 3 new tools: create_execution_plan, report_progress, submit_batch_job.

Unit tests (mocked -- no running database required).

Run: cd backend && uv run python -m pytest tests/test_new_tools.py -v
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.agent.tools import (
    TOOL_REGISTRY,
    _BATCH_JOB_MARKER,
    _PROGRESS_MARKER,
    create_execution_plan,
    report_progress,
    submit_batch_job,
)
from app.dependencies import get_agent_deps


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deps(**kwargs):
    """Create an AgentDeps instance suitable for unit tests."""
    return get_agent_deps(**kwargs)


# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

class TestMarkerConstants:
    """Verify the sentinel marker strings used by the orchestrator."""

    def test_progress_marker_value(self):
        assert _PROGRESS_MARKER == "__PROGRESS__:"

    def test_batch_job_marker_value(self):
        assert _BATCH_JOB_MARKER == "__BATCH_JOB__:"


# ---------------------------------------------------------------------------
# create_execution_plan
# ---------------------------------------------------------------------------

class TestCreateExecutionPlan:
    """Verify create_execution_plan stores state and returns markdown."""

    @pytest.mark.asyncio
    async def test_stores_plan_in_run_state(self):
        """Execution plan, step counter, and estimated calls are persisted."""
        deps = _make_deps()
        steps = [
            {
                "step_number": 1,
                "description": "Extract names",
                "tools": ["search_uploaded_documents"],
            },
            {
                "step_number": 2,
                "description": "Look up clients",
                "tools": ["batch_lookup_clients"],
                "depends_on": [1],
                "critical": True,
            },
        ]

        await create_execution_plan(
            deps=deps,
            task_summary="Process uploaded roster",
            steps=steps,
            estimated_tool_calls=15,
        )

        assert deps.run_state.execution_plan == steps
        assert deps.run_state.execution_step == 0
        assert deps.run_state.estimated_tool_calls == 15

    @pytest.mark.asyncio
    async def test_returns_markdown_output(self):
        """Return value should be formatted markdown with plan details."""
        deps = _make_deps()
        steps = [
            {
                "step_number": 1,
                "description": "Fetch data",
                "tools": ["web_search"],
            },
        ]

        result = await create_execution_plan(
            deps=deps,
            task_summary="Gather competitor intel",
            steps=steps,
            estimated_tool_calls=5,
        )

        assert "## Execution Plan: Gather competitor intel" in result
        assert "**Estimated tool calls:** 5" in result
        assert "### Steps" in result
        assert "1. Fetch data" in result
        assert "Tools: web_search" in result

    @pytest.mark.asyncio
    async def test_markdown_includes_dependencies_and_critical(self):
        """Steps with depends_on and critical flags render correctly."""
        deps = _make_deps()
        steps = [
            {
                "step_number": 1,
                "description": "Step one",
                "tools": ["web_search"],
            },
            {
                "step_number": 2,
                "description": "Step two",
                "tools": ["lookup_client"],
                "depends_on": [1],
                "critical": True,
            },
        ]

        result = await create_execution_plan(
            deps=deps,
            task_summary="Test plan",
            steps=steps,
        )

        assert "(depends on: 1)" in result
        assert "[CRITICAL]" in result

    @pytest.mark.asyncio
    async def test_default_estimated_tool_calls(self):
        """Default estimated_tool_calls should be 10."""
        deps = _make_deps()
        steps = [
            {"step_number": 1, "description": "Go", "tools": ["web_search"]},
        ]

        result = await create_execution_plan(
            deps=deps,
            task_summary="Quick task",
            steps=steps,
        )

        assert deps.run_state.estimated_tool_calls == 10
        assert "**Estimated tool calls:** 10" in result

    def test_registered_for_task_execution_only(self):
        """create_execution_plan should be available only in task_execution mode."""
        td = TOOL_REGISTRY["create_execution_plan"]
        assert td.modes == frozenset({"task_execution"})


# ---------------------------------------------------------------------------
# report_progress
# ---------------------------------------------------------------------------

class TestReportProgress:
    """Verify report_progress returns __PROGRESS__ prefixed JSON."""

    @pytest.mark.asyncio
    async def test_returns_progress_prefixed_json(self):
        """Output should start with the progress marker and contain valid JSON."""
        deps = _make_deps()

        result = await report_progress(
            deps=deps,
            message="Processing items",
        )

        assert result.startswith(_PROGRESS_MARKER)
        payload = json.loads(result[len(_PROGRESS_MARKER):])
        assert payload["message"] == "Processing items"
        assert payload["phase"] == "processing"

    @pytest.mark.asyncio
    async def test_calculates_percentage(self):
        """When current and total are provided, percent is calculated."""
        deps = _make_deps()

        result = await report_progress(
            deps=deps,
            message="Halfway done",
            current=50,
            total=200,
        )

        payload = json.loads(result[len(_PROGRESS_MARKER):])
        assert payload["current"] == 50
        assert payload["total"] == 200
        assert payload["percent"] == 25.0

    @pytest.mark.asyncio
    async def test_percentage_not_set_without_total(self):
        """percent should NOT appear when total is missing."""
        deps = _make_deps()

        result = await report_progress(
            deps=deps,
            message="Step 3",
            current=3,
        )

        payload = json.loads(result[len(_PROGRESS_MARKER):])
        assert payload["current"] == 3
        assert "total" not in payload
        assert "percent" not in payload

    @pytest.mark.asyncio
    async def test_percentage_not_set_when_total_is_zero(self):
        """percent should NOT appear when total is 0 (division guard)."""
        deps = _make_deps()

        result = await report_progress(
            deps=deps,
            message="No items",
            current=0,
            total=0,
        )

        payload = json.loads(result[len(_PROGRESS_MARKER):])
        assert "percent" not in payload

    @pytest.mark.asyncio
    async def test_includes_step_label_and_phase(self):
        """step_label and phase should appear in the payload when provided."""
        deps = _make_deps()

        result = await report_progress(
            deps=deps,
            message="Aggregating results",
            step_label="Step 2: Aggregate",
            phase="aggregating",
        )

        payload = json.loads(result[len(_PROGRESS_MARKER):])
        assert payload["step_label"] == "Step 2: Aggregate"
        assert payload["phase"] == "aggregating"

    def test_registered_for_data_processing_and_task_execution(self):
        """report_progress should be available in data_processing and task_execution."""
        td = TOOL_REGISTRY["report_progress"]
        assert td.modes == frozenset({"data_processing", "task_execution"})


# ---------------------------------------------------------------------------
# submit_batch_job
# ---------------------------------------------------------------------------

class TestSubmitBatchJob:
    """Verify submit_batch_job enqueue behavior and error handling."""

    @pytest.mark.asyncio
    async def test_handles_import_failure_gracefully(self):
        """When app.job_queue or app.streams is unavailable, returns fallback message."""
        deps = _make_deps()
        data = [{"name": "Alice"}, {"name": "Bob"}]

        with patch.dict(
            "sys.modules",
            {"app.job_queue": None, "app.streams": None},
        ):
            # Force a fresh import failure by removing cached modules
            result = await submit_batch_job(
                deps=deps,
                job_type="batch_client_lookup",
                data=data,
            )

        assert "Batch job system unavailable" in result
        assert "2 items inline" in result
        assert "batch_lookup_clients" in result

    @pytest.mark.asyncio
    async def test_successful_submission_returns_marker(self):
        """On success, returns __BATCH_JOB__ prefixed JSON with job_id and item_count."""
        deps = _make_deps(user_sid="user-test-123")
        data = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}]

        mock_enqueue = AsyncMock(return_value="job-uuid-abc")
        mock_publish = AsyncMock()

        with (
            patch("app.agent.tools.enqueue", mock_enqueue, create=True),
            patch("app.agent.tools.publish_job", mock_publish, create=True),
            patch("app.agent.tools.STREAM_DATA_PROCESSING", "jobs:data_processing", create=True),
        ):
            # Patch the lazy imports inside the function
            import types

            fake_job_queue = types.ModuleType("app.job_queue")
            fake_job_queue.enqueue = mock_enqueue  # type: ignore[attr-defined]

            fake_streams = types.ModuleType("app.streams")
            fake_streams.publish_job = mock_publish  # type: ignore[attr-defined]
            fake_streams.STREAM_DATA_PROCESSING = "jobs:data_processing"  # type: ignore[attr-defined]

            with patch.dict("sys.modules", {
                "app.job_queue": fake_job_queue,
                "app.streams": fake_streams,
            }):
                result = await submit_batch_job(
                    deps=deps,
                    job_type="batch_client_lookup",
                    data=data,
                    options={"priority": "high"},
                )

        assert result.startswith(_BATCH_JOB_MARKER)
        payload = json.loads(result[len(_BATCH_JOB_MARKER):])
        assert payload["job_id"] == "job-uuid-abc"
        assert payload["item_count"] == 3

    @pytest.mark.asyncio
    async def test_enqueue_exception_falls_back(self):
        """If enqueue raises, the tool returns a fallback message instead of crashing."""
        deps = _make_deps()
        data = [{"name": "X"}] * 50

        import types

        fake_job_queue = types.ModuleType("app.job_queue")
        fake_job_queue.enqueue = AsyncMock(side_effect=RuntimeError("Redis down"))  # type: ignore[attr-defined]

        fake_streams = types.ModuleType("app.streams")
        fake_streams.publish_job = AsyncMock()  # type: ignore[attr-defined]
        fake_streams.STREAM_DATA_PROCESSING = "jobs:data_processing"  # type: ignore[attr-defined]

        with patch.dict("sys.modules", {
            "app.job_queue": fake_job_queue,
            "app.streams": fake_streams,
        }):
            result = await submit_batch_job(
                deps=deps,
                job_type="batch_enrichment",
                data=data,
            )

        assert "Batch job system unavailable" in result
        assert "Redis down" in result
        assert "50 items inline" in result

    def test_registered_for_data_processing_and_task_execution(self):
        """submit_batch_job should be available in data_processing and task_execution."""
        td = TOOL_REGISTRY["submit_batch_job"]
        assert td.modes == frozenset({"data_processing", "task_execution"})

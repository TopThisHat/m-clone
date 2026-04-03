"""
Unit tests for batch data processing workflows.

Covers:
  1. BatchClientLookupWorkflow processes all items with mocked resolver
  2. Per-item error isolation — one failure does not abort remaining items
  3. Progress tracking via update_job_progress
  4. Empty items list completes immediately
  5. STREAM_DATA_PROCESSING constant exists and is mapped in JOB_TYPE_TO_STREAM
  6. All three data_processing workflow types are registered in the registry
  7. BatchEnrichmentWorkflow and BatchExtractionWorkflow basic execution
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# Unit tests -- no database connection needed
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


def _make_job(
    job_type: str = "data_processing_batch_client_lookup",
    items: list | None = None,
    options: dict | None = None,
    user_sid: str | None = None,
    job_id: str = "00000000-0000-0000-0000-000000000001",
) -> dict:
    """Build a minimal job dict matching what the consumer passes to workflows."""
    payload = {
        "items": items or [],
        "options": options or {},
    }
    if user_sid:
        payload["user_sid"] = user_sid
    return {
        "id": job_id,
        "job_type": job_type,
        "payload": payload,
        "parent_job_id": None,
        "root_job_id": None,
        "attempts": 0,
        "max_attempts": 3,
        "validation_job_id": None,
    }


# ---------------------------------------------------------------------------
# 1. STREAM_DATA_PROCESSING constant and JOB_TYPE_TO_STREAM mapping
# ---------------------------------------------------------------------------

class TestStreamConstants:
    def test_stream_data_processing_constant_exists(self):
        from app.streams import STREAM_DATA_PROCESSING
        assert STREAM_DATA_PROCESSING == "jobs:data_processing"

    def test_job_type_to_stream_maps_batch_client_lookup(self):
        from app.streams import JOB_TYPE_TO_STREAM, STREAM_DATA_PROCESSING
        assert JOB_TYPE_TO_STREAM["data_processing_batch_client_lookup"] == STREAM_DATA_PROCESSING

    def test_job_type_to_stream_maps_batch_enrichment(self):
        from app.streams import JOB_TYPE_TO_STREAM, STREAM_DATA_PROCESSING
        assert JOB_TYPE_TO_STREAM["data_processing_batch_enrichment"] == STREAM_DATA_PROCESSING

    def test_job_type_to_stream_maps_batch_extraction(self):
        from app.streams import JOB_TYPE_TO_STREAM, STREAM_DATA_PROCESSING
        assert JOB_TYPE_TO_STREAM["data_processing_batch_extraction"] == STREAM_DATA_PROCESSING

    def test_stream_included_in_all_workflow_streams(self):
        from worker.config import ALL_WORKFLOW_STREAMS
        from app.streams import STREAM_DATA_PROCESSING
        assert STREAM_DATA_PROCESSING in ALL_WORKFLOW_STREAMS


# ---------------------------------------------------------------------------
# 2. Workflow registration
# ---------------------------------------------------------------------------

class TestWorkflowRegistration:
    def test_batch_client_lookup_is_registered(self):
        import worker.workflows  # noqa: F401
        from worker.registry import registry
        assert "data_processing_batch_client_lookup" in registry._handlers

    def test_batch_enrichment_is_registered(self):
        import worker.workflows  # noqa: F401
        from worker.registry import registry
        assert "data_processing_batch_enrichment" in registry._handlers

    def test_batch_extraction_is_registered(self):
        import worker.workflows  # noqa: F401
        from worker.registry import registry
        assert "data_processing_batch_extraction" in registry._handlers

    def test_data_processing_module_in_init_list(self):
        from worker.workflows import _WORKFLOW_MODULES
        assert "worker.workflows.data_processing" in _WORKFLOW_MODULES


# ---------------------------------------------------------------------------
# 3. BatchClientLookupWorkflow — happy path
# ---------------------------------------------------------------------------

class TestBatchClientLookupWorkflow:
    @pytest.mark.asyncio
    async def test_processes_all_items_with_mocked_resolver(self):
        """All items are processed and results collected."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        items = [
            {"name": "Alice Smith", "company": "Acme"},
            {"name": "Bob Jones"},
            {"name": "Carol White", "company": "Globex"},
        ]
        job = _make_job(items=items)

        mock_resolve = AsyncMock(return_value={
            "gwm_id": "GWM123",
            "confidence": 0.95,
            "match_found": True,
        })

        workflow = BatchClientLookupWorkflow(job)

        with patch(
            "worker.workflows.data_processing.BatchClientLookupWorkflow._resolve_client",
            mock_resolve,
        ), patch(
            "worker.workflows.data_processing.BatchClientLookupWorkflow._update_progress",
            new_callable=AsyncMock,
        ) as mock_progress:
            await workflow.run()

        # All three items resolved
        assert mock_resolve.call_count == 3
        # Progress was updated (items < 10, so only at completion)
        assert mock_progress.call_count >= 1
        # Last progress call has all 3 items completed
        last_call = mock_progress.call_args
        assert last_call[0][0] == 3  # completed
        assert last_call[0][1] == 3  # total
        assert last_call[0][2] == 0  # failed

    @pytest.mark.asyncio
    async def test_resolve_client_with_importerror_returns_stub(self):
        """When client_resolver is not importable, _resolve_client returns stub."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        job = _make_job(items=[{"name": "Test User"}])
        workflow = BatchClientLookupWorkflow(job)

        with patch(
            "builtins.__import__",
            side_effect=_make_import_error_for("app.agent.client_resolver"),
        ):
            result = await workflow._resolve_client("Test User")

        assert result["gwm_id"] is None
        assert result["confidence"] == 0.0
        assert result["match_found"] is False


# ---------------------------------------------------------------------------
# 4. Per-item error isolation
# ---------------------------------------------------------------------------

class TestPerItemErrorIsolation:
    @pytest.mark.asyncio
    async def test_one_failure_does_not_abort_remaining(self):
        """A single item failure should not prevent other items from processing."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        items = [
            {"name": "Good One"},
            {"name": "Bad One"},
            {"name": "Good Two"},
        ]
        job = _make_job(items=items)

        call_count = 0

        async def _mock_resolve(name, company=None):
            nonlocal call_count
            call_count += 1
            if name == "Bad One":
                raise RuntimeError("Lookup service unavailable")
            return {"gwm_id": "GWM999", "confidence": 0.9, "match_found": True}

        workflow = BatchClientLookupWorkflow(job)

        with patch.object(workflow, "_resolve_client", side_effect=_mock_resolve), \
             patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        # All three items were attempted
        assert call_count == 3

        # Final progress: 3 completed, 1 failed
        last_call = mock_progress.call_args
        assert last_call[0][0] == 3  # completed
        assert last_call[0][1] == 3  # total
        assert last_call[0][2] == 1  # failed

        # Results should have the error for "Bad One"
        results = last_call[0][3]
        error_items = [r for r in results if r["status"] == "error"]
        assert len(error_items) == 1
        assert error_items[0]["name"] == "Bad One"
        assert "Lookup service unavailable" in error_items[0]["error"]

    @pytest.mark.asyncio
    async def test_all_items_fail_gracefully(self):
        """Even if every item fails, workflow completes without raising."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        items = [{"name": "Fail One"}, {"name": "Fail Two"}]
        job = _make_job(items=items)

        async def _always_fail(name, company=None):
            raise RuntimeError("always fails")

        workflow = BatchClientLookupWorkflow(job)

        with patch.object(workflow, "_resolve_client", side_effect=_always_fail), \
             patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        last_call = mock_progress.call_args
        assert last_call[0][0] == 2  # completed
        assert last_call[0][2] == 2  # all failed


# ---------------------------------------------------------------------------
# 5. Progress tracking
# ---------------------------------------------------------------------------

class TestProgressTracking:
    @pytest.mark.asyncio
    async def test_progress_updated_at_completion(self):
        """Progress is always updated when completed == total."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        items = [{"name": f"Person {i}"} for i in range(3)]
        job = _make_job(items=items)

        workflow = BatchClientLookupWorkflow(job)

        with patch.object(workflow, "_resolve_client", new_callable=AsyncMock, return_value={
            "gwm_id": "X", "confidence": 1.0, "match_found": True,
        }), patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        # At least the final call must have completed == total
        final_call = mock_progress.call_args
        assert final_call[0][0] == 3  # completed == total

    @pytest.mark.asyncio
    async def test_progress_updated_every_10_items(self):
        """With 25 items, progress should be called at 10, 20, and 25."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        items = [{"name": f"Person {i}"} for i in range(25)]
        job = _make_job(items=items)

        workflow = BatchClientLookupWorkflow(job)

        with patch.object(workflow, "_resolve_client", new_callable=AsyncMock, return_value={
            "gwm_id": "X", "confidence": 1.0, "match_found": True,
        }), patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        # Expected progress calls at: 10, 20, 25
        assert mock_progress.call_count == 3
        completed_values = [call[0][0] for call in mock_progress.call_args_list]
        assert completed_values == [10, 20, 25]

    @pytest.mark.asyncio
    async def test_update_progress_calls_job_queue(self):
        """_update_progress delegates to update_job_progress in job_queue."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        job = _make_job(items=[])
        workflow = BatchClientLookupWorkflow(job)

        mock_update = AsyncMock()
        with patch("app.job_queue.update_job_progress", mock_update):
            await workflow._update_progress(5, 10, 1, [{"index": 0, "status": "ok"}])

        mock_update.assert_called_once_with(
            workflow.job_id,
            {
                "items_completed": 5,
                "items_total": 10,
                "items_failed": 1,
                "results": [{"index": 0, "status": "ok"}],
            },
        )

    @pytest.mark.asyncio
    async def test_update_progress_handles_import_error_gracefully(self):
        """If update_job_progress cannot be imported, _update_progress does not raise."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        job = _make_job(items=[])
        workflow = BatchClientLookupWorkflow(job)

        with patch(
            "builtins.__import__",
            side_effect=_make_import_error_for("app.job_queue"),
        ):
            # Should not raise
            await workflow._update_progress(0, 0, 0, [])

    @pytest.mark.asyncio
    async def test_update_progress_handles_db_exception_gracefully(self):
        """If update_job_progress raises, _update_progress logs but does not propagate."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        job = _make_job(items=[])
        workflow = BatchClientLookupWorkflow(job)

        mock_update = AsyncMock(side_effect=RuntimeError("DB down"))
        with patch("app.job_queue.update_job_progress", mock_update):
            # Should not raise
            await workflow._update_progress(1, 1, 0, [])


# ---------------------------------------------------------------------------
# 6. Empty items list
# ---------------------------------------------------------------------------

class TestEmptyItemsList:
    @pytest.mark.asyncio
    async def test_empty_items_completes_immediately(self):
        """An empty items list should update progress once and return."""
        from worker.workflows.data_processing import BatchClientLookupWorkflow

        job = _make_job(items=[])
        workflow = BatchClientLookupWorkflow(job)

        with patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        mock_progress.assert_called_once_with(0, 0, 0, [])

    @pytest.mark.asyncio
    async def test_empty_enrichment_completes_immediately(self):
        from worker.workflows.data_processing import BatchEnrichmentWorkflow

        job = _make_job(job_type="data_processing_batch_enrichment", items=[])
        workflow = BatchEnrichmentWorkflow(job)

        with patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        mock_progress.assert_called_once_with(0, 0, 0, [])

    @pytest.mark.asyncio
    async def test_empty_extraction_completes_immediately(self):
        from worker.workflows.data_processing import BatchExtractionWorkflow

        job = _make_job(job_type="data_processing_batch_extraction", items=[])
        workflow = BatchExtractionWorkflow(job)

        with patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        mock_progress.assert_called_once_with(0, 0, 0, [])


# ---------------------------------------------------------------------------
# 7. BatchEnrichmentWorkflow and BatchExtractionWorkflow basic execution
# ---------------------------------------------------------------------------

class TestBatchEnrichmentWorkflow:
    @pytest.mark.asyncio
    async def test_processes_items(self):
        from worker.workflows.data_processing import BatchEnrichmentWorkflow

        items = [{"entity_id": "e1"}, {"entity_id": "e2"}]
        job = _make_job(job_type="data_processing_batch_enrichment", items=items)
        workflow = BatchEnrichmentWorkflow(job)

        with patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        last_call = mock_progress.call_args
        assert last_call[0][0] == 2  # completed
        assert last_call[0][1] == 2  # total
        assert last_call[0][2] == 0  # failed

    @pytest.mark.asyncio
    async def test_per_item_error_isolation(self):
        from worker.workflows.data_processing import BatchEnrichmentWorkflow

        items = [{"entity_id": "e1"}, {"entity_id": "e2"}]
        job = _make_job(job_type="data_processing_batch_enrichment", items=items)
        workflow = BatchEnrichmentWorkflow(job)

        call_count = 0

        async def _fail_first(item):
            nonlocal call_count
            call_count += 1
            if item.get("entity_id") == "e1":
                raise RuntimeError("enrichment failed")
            return {"enriched": True, "attributes_added": 3}

        with patch.object(workflow, "_enrich_entity", side_effect=_fail_first), \
             patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        assert call_count == 2
        last_call = mock_progress.call_args
        assert last_call[0][0] == 2  # completed
        assert last_call[0][2] == 1  # failed


class TestBatchExtractionWorkflow:
    @pytest.mark.asyncio
    async def test_processes_items(self):
        from worker.workflows.data_processing import BatchExtractionWorkflow

        items = [{"text": "some text"}, {"text": "more text"}]
        job = _make_job(job_type="data_processing_batch_extraction", items=items)
        workflow = BatchExtractionWorkflow(job)

        with patch.object(workflow, "_update_progress", new_callable=AsyncMock) as mock_progress:
            await workflow.run()

        last_call = mock_progress.call_args
        assert last_call[0][0] == 2  # completed
        assert last_call[0][1] == 2  # total
        assert last_call[0][2] == 0  # failed


# ---------------------------------------------------------------------------
# 8. update_job_progress function in job_queue
# ---------------------------------------------------------------------------

class TestUpdateJobProgress:
    @pytest.mark.asyncio
    async def test_function_exists_and_is_importable(self):
        from app.job_queue import update_job_progress
        assert callable(update_job_progress)

    @pytest.mark.asyncio
    async def test_calls_db_with_merged_payload(self):
        """update_job_progress issues an UPDATE with jsonb merge."""
        from app.job_queue import update_job_progress

        mock_conn = AsyncMock()

        # Build a mock pool whose .acquire() returns an async context manager
        # yielding mock_conn.
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_conn
        mock_ctx.__aexit__.return_value = False

        mock_pool = MagicMock()
        mock_pool.acquire.return_value = mock_ctx

        with patch("app.job_queue._get_pool", new_callable=AsyncMock, return_value=mock_pool):
            await update_job_progress("test-job-id", {
                "items_completed": 5,
                "items_total": 10,
            })

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        # Verify the SQL uses jsonb merge
        sql = call_args[0][0]
        assert "||" in sql or "jsonb" in sql
        # Verify the job_id was passed
        assert call_args[0][1] == "test-job-id"
        # Verify the progress data was serialized
        progress_json = json.loads(call_args[0][2])
        assert progress_json["items_completed"] == 5
        assert progress_json["items_total"] == 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_import_error_for(module_name: str):
    """Return a side_effect function that raises ImportError only for a specific module."""
    _real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _import_side_effect(name, *args, **kwargs):
        if name == module_name:
            raise ImportError(f"No module named '{module_name}'")
        return _real_import(name, *args, **kwargs)

    return _import_side_effect

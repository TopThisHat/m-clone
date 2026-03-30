"""
Unit tests for workflow registration resilience.

Covers:
  1. Import failure for one module raises RuntimeError naming that module
  2. Empty workflow registry raises RuntimeError at startup
  3. All workflow modules import successfully in normal operation
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
import pytest_asyncio


# Unit tests — no database connection needed
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# 1. Import failure raises RuntimeError with the failing module name
# ---------------------------------------------------------------------------

class TestWorkflowImportResilience:
    def test_failed_import_raises_runtime_error_with_module_name(self):
        """RuntimeError raised by __init__.py names the failing workflow module."""
        real_import = importlib.import_module

        def fail_for_validation(name):
            if name == "worker.workflows.validation":
                raise ImportError("missing dependency")
            return real_import(name)

        import worker.workflows
        with patch("importlib.import_module", side_effect=fail_for_validation):
            with pytest.raises(RuntimeError) as exc_info:
                importlib.reload(worker.workflows)

        assert "worker.workflows.validation" in str(exc_info.value)

    def test_failed_import_raises_runtime_error_for_research_module(self):
        """RuntimeError names 'research' module when it fails to import."""
        real_import = importlib.import_module

        def fail_for_research(name):
            if name == "worker.workflows.research":
                raise ImportError("broken import")
            return real_import(name)

        import worker.workflows
        with patch("importlib.import_module", side_effect=fail_for_research):
            with pytest.raises(RuntimeError) as exc_info:
                importlib.reload(worker.workflows)

        assert "worker.workflows.research" in str(exc_info.value)

    def test_failed_import_wraps_original_exception(self):
        """RuntimeError is chained from the original ImportError (has __cause__)."""
        real_import = importlib.import_module
        original_error = ImportError("missing dep for clustering")

        def fail_for_clustering(name):
            if name == "worker.workflows.attribute_clustering":
                raise original_error
            return real_import(name)

        import worker.workflows
        with patch("importlib.import_module", side_effect=fail_for_clustering):
            with pytest.raises(RuntimeError) as exc_info:
                importlib.reload(worker.workflows)

        # The original ImportError should be chained as __cause__
        assert exc_info.value.__cause__ is original_error

    def test_first_failing_module_stops_registration(self):
        """When module 1 fails, modules 2-4 are never attempted."""
        real_import = importlib.import_module
        attempted_modules = []

        def track_and_fail(name):
            if name.startswith("worker.workflows."):
                attempted_modules.append(name)
                if name == "worker.workflows.validation":
                    raise ImportError("broken")
            return real_import(name)

        import worker.workflows
        with patch("importlib.import_module", side_effect=track_and_fail):
            with pytest.raises(RuntimeError):
                importlib.reload(worker.workflows)

        # Only the first workflow module should have been attempted
        assert "worker.workflows.validation" in attempted_modules
        assert "worker.workflows.research" not in attempted_modules


# ---------------------------------------------------------------------------
# 2. Empty registry raises RuntimeError at startup
# ---------------------------------------------------------------------------

class TestEmptyRegistryStartup:
    @pytest.mark.asyncio
    async def test_main_raises_when_no_handlers_registered(self):
        """worker/main.py raises RuntimeError when registry has no handlers."""
        from worker.registry import registry
        from worker.main import main

        # Temporarily clear the registry
        original_handlers = dict(registry._handlers)
        registry._handlers.clear()
        try:
            with pytest.raises(RuntimeError, match="No workflow handlers registered"):
                await main()
        finally:
            registry._handlers.update(original_handlers)

    @pytest.mark.asyncio
    async def test_registry_error_raised_before_redis_connection(self):
        """Empty registry check happens before any Redis or DB connection attempt."""
        from worker.registry import registry
        from worker.main import main

        original_handlers = dict(registry._handlers)
        registry._handlers.clear()
        try:
            # If DB/Redis were attempted, they would fail differently.
            # An empty registry should raise RuntimeError before any connections.
            with (
                patch("app.openai_factory.initialize") as mock_openai,
                patch("app.db.get_pool") as mock_db,
                patch("app.streams.get_redis") as mock_redis,
            ):
                with pytest.raises(RuntimeError, match="No workflow handlers registered"):
                    await main()

            # These should never be called if registry check fails first
            mock_openai.assert_not_called()
            mock_db.assert_not_called()
            mock_redis.assert_not_called()
        finally:
            registry._handlers.update(original_handlers)


# ---------------------------------------------------------------------------
# 3. Normal import succeeds — all modules registered
# ---------------------------------------------------------------------------

class TestWorkflowRegistrationSuccess:
    def test_all_workflow_modules_import_without_error(self):
        """Reloading worker.workflows succeeds when all modules are available."""
        import worker.workflows
        # Should not raise
        importlib.reload(worker.workflows)

    def test_registry_is_non_empty_after_import(self):
        """All workflow handlers are registered in registry after import."""
        import worker.workflows  # noqa: F401 — ensure imported
        from worker.registry import registry

        assert registry._handlers, "Expected at least one registered workflow handler"

    def test_known_job_types_are_registered(self):
        """validation_campaign, validation_pair, validation_cluster handlers present."""
        import worker.workflows  # noqa: F401
        from worker.registry import registry

        expected_types = {"validation_campaign", "validation_pair", "validation_cluster"}
        registered_types = set(registry._handlers.keys())

        missing = expected_types - registered_types
        assert not missing, f"Missing handlers for job types: {missing}"

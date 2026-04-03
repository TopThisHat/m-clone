"""Unit tests for the decoupled entity extraction / client lookup worker.

Verifies that:
  1. Entity extraction ALWAYS runs regardless of enable_client_lookup.
  2. Client lookup is SKIPPED when enable_client_lookup=False.
  3. Client lookup RUNS when enable_client_lookup=True.
  4. Existing agent tools (batch_lookup_clients, extract_and_lookup_entities)
     are unaffected by the new flag.

All tests are unit-level (no Redis, no database, no real LLM calls).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from worker.entity_extraction import (
    ExtractionResult,
    ExtractedEntity,
    _process_message,
)


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extraction_result(
    *,
    persons: list[str] | None = None,
    other_entities: list[str] | None = None,
) -> ExtractionResult:
    """Build a minimal ExtractionResult for testing."""
    entities: list[ExtractedEntity] = []
    for name in (persons or []):
        entities.append(ExtractedEntity(name=name, type="person"))
    for name in (other_entities or []):
        entities.append(ExtractedEntity(name=name, type="company"))
    return ExtractionResult(entities=entities, relationships=[])


def _make_db_mocks():
    """Return (mock_conn, mock_cm) for patching _acquire."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_conn, mock_cm


# ---------------------------------------------------------------------------
# 1. Entity extraction ALWAYS runs
# ---------------------------------------------------------------------------

class TestEntityExtractionAlwaysRuns:

    @pytest.mark.asyncio
    async def test_extraction_runs_when_client_lookup_disabled(self):
        """KG extraction must be called even when enable_client_lookup=False."""
        extraction_result = _make_extraction_result(persons=["Alice Smith"])
        _, mock_cm = _make_db_mocks()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ) as mock_extract, patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-1", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-1"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ):
            result = await _process_message(
                "session-1", "Some report text",
                enable_client_lookup=False,
            )

        mock_extract.assert_called_once()
        assert result["entities"] == 1

    @pytest.mark.asyncio
    async def test_extraction_runs_when_client_lookup_enabled(self):
        """KG extraction must be called when enable_client_lookup=True."""
        extraction_result = _make_extraction_result(persons=["Bob Jones"])
        _, mock_cm = _make_db_mocks()

        mock_batch = AsyncMock(return_value=[
            {"name": "Bob Jones", "status": "matched", "gwm_id": "GWM-001", "confidence": 0.9},
        ])

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ) as mock_extract, patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-2", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-2"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            result = await _process_message(
                "session-2", "Another report",
                enable_client_lookup=True,
            )

        mock_extract.assert_called_once()
        assert result["entities"] == 1

    @pytest.mark.asyncio
    async def test_extraction_runs_with_default_flag(self):
        """Default call (no enable_client_lookup arg) still runs extraction."""
        extraction_result = _make_extraction_result(other_entities=["Acme Corp"])
        _, mock_cm = _make_db_mocks()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ) as mock_extract, patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-3", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-3"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ):
            result = await _process_message("session-3", "text")

        mock_extract.assert_called_once()
        assert result["entities"] == 1


# ---------------------------------------------------------------------------
# 2. Client lookup SKIPPED when enable_client_lookup=False
# ---------------------------------------------------------------------------

class TestClientLookupSkippedWhenDisabled:

    @pytest.mark.asyncio
    async def test_batch_resolve_not_called_when_disabled(self):
        """batch_resolve_clients must NOT be called when flag is False."""
        extraction_result = _make_extraction_result(persons=["Carol White"])
        _, mock_cm = _make_db_mocks()
        mock_batch = AsyncMock()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-4", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-4"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            result = await _process_message(
                "session-4", "Some text",
                enable_client_lookup=False,
            )

        mock_batch.assert_not_called()
        assert result["client_lookups"] == 0

    @pytest.mark.asyncio
    async def test_client_lookups_zero_in_return_when_disabled(self):
        """Return dict should have client_lookups=0 when flag is False."""
        extraction_result = _make_extraction_result(persons=["Dave Green"])
        _, mock_cm = _make_db_mocks()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-5", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-5"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ):
            result = await _process_message(
                "session-5", "Report about Dave Green",
                enable_client_lookup=False,
            )

        assert result["client_lookups"] == 0

    @pytest.mark.asyncio
    async def test_no_client_lookup_for_empty_extraction(self):
        """When extraction yields nothing, client_lookups must be 0 (early return)."""
        empty_result = ExtractionResult(entities=[], relationships=[])

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=empty_result),
        ):
            result = await _process_message(
                "session-6", "text with no entities",
                enable_client_lookup=False,
            )

        assert result["client_lookups"] == 0
        assert result["entities"] == 0


# ---------------------------------------------------------------------------
# 3. Client lookup RUNS when enable_client_lookup=True
# ---------------------------------------------------------------------------

class TestClientLookupRunsWhenEnabled:

    @pytest.mark.asyncio
    async def test_batch_resolve_called_for_persons_when_enabled(self):
        """batch_resolve_clients is called with person entities when flag is True."""
        extraction_result = _make_extraction_result(
            persons=["Eve Brown", "Frank Miller"],
            other_entities=["GlobalCorp"],  # company should NOT be looked up
        )
        _, mock_cm = _make_db_mocks()
        mock_batch = AsyncMock(return_value=[
            {"name": "Eve Brown", "status": "matched", "gwm_id": "GWM-101", "confidence": 0.95},
            {"name": "Frank Miller", "status": "no_match", "gwm_id": None, "confidence": None},
        ])

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            result = await _process_message(
                "session-7", "Report text",
                enable_client_lookup=True,
            )

        mock_batch.assert_called_once()
        called_people = mock_batch.call_args[0][0]
        # Only person entities should be passed for lookup, not company
        person_names = {p["name"] for p in called_people}
        assert "Eve Brown" in person_names
        assert "Frank Miller" in person_names
        assert "GlobalCorp" not in person_names
        assert result["client_lookups"] == 2

    @pytest.mark.asyncio
    async def test_client_lookups_count_in_return_when_enabled(self):
        """Return dict reflects the number of lookups performed."""
        extraction_result = _make_extraction_result(persons=["Grace Lee"])
        _, mock_cm = _make_db_mocks()
        mock_batch = AsyncMock(return_value=[
            {"name": "Grace Lee", "status": "matched", "gwm_id": "GWM-200", "confidence": 0.88},
        ])

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-g", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-g"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            result = await _process_message(
                "session-8", "Text about Grace Lee",
                enable_client_lookup=True,
            )

        assert result["client_lookups"] == 1

    @pytest.mark.asyncio
    async def test_no_lookup_when_no_persons_even_if_enabled(self):
        """When no person entities are extracted, batch_resolve is not called even with flag=True."""
        extraction_result = _make_extraction_result(other_entities=["Microsoft", "Apple"])
        _, mock_cm = _make_db_mocks()
        mock_batch = AsyncMock()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-corp", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-corp"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            result = await _process_message(
                "session-9", "Tech company analysis",
                enable_client_lookup=True,
            )

        mock_batch.assert_not_called()
        assert result["client_lookups"] == 0

    @pytest.mark.asyncio
    async def test_lookup_error_does_not_fail_extraction(self):
        """A client lookup failure must not propagate — extraction result is still returned."""
        extraction_result = _make_extraction_result(persons=["Henry Ford"])
        _, mock_cm = _make_db_mocks()
        mock_batch = AsyncMock(side_effect=RuntimeError("DB unavailable"))

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction_result),
        ), patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("entity-uuid-h", "team_hit")),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-h"}),
        ), patch(
            "app.db._pool._acquire",
            return_value=mock_cm,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_batch,
        ):
            # Should NOT raise even though batch_resolve_clients fails
            result = await _process_message(
                "session-10", "Henry Ford biography",
                enable_client_lookup=True,
            )

        assert result["entities"] == 1
        assert result["client_lookups"] == 0  # failed lookup → 0, no exception


# ---------------------------------------------------------------------------
# 4. publish_for_extraction stream schema
# ---------------------------------------------------------------------------

class TestPublishForExtractionSchema:

    @pytest.mark.asyncio
    async def test_enable_client_lookup_false_by_default(self):
        """publish_for_extraction omits or sends 'false' for enable_client_lookup by default."""
        from app.streams import publish_for_extraction

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1-0")

        with patch("app.streams.get_redis", AsyncMock(return_value=mock_redis)):
            await publish_for_extraction("sess-a", "some text")

        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        # When False (default), the field should be absent OR explicitly "false"
        assert fields.get("enable_client_lookup", "false") == "false"

    @pytest.mark.asyncio
    async def test_enable_client_lookup_true_when_passed(self):
        """publish_for_extraction passes 'true' for enable_client_lookup when requested."""
        from app.streams import publish_for_extraction

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1-0")

        with patch("app.streams.get_redis", AsyncMock(return_value=mock_redis)):
            await publish_for_extraction("sess-b", "some text", enable_client_lookup=True)

        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert fields["enable_client_lookup"] == "true"

    @pytest.mark.asyncio
    async def test_enable_client_lookup_false_explicit(self):
        """publish_for_extraction sends 'false' when explicitly False."""
        from app.streams import publish_for_extraction

        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1-0")

        with patch("app.streams.get_redis", AsyncMock(return_value=mock_redis)):
            await publish_for_extraction("sess-c", "some text", enable_client_lookup=False)

        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert fields.get("enable_client_lookup", "false") == "false"


# ---------------------------------------------------------------------------
# 5. Existing agent tools unaffected
# ---------------------------------------------------------------------------

class TestExistingAgentToolsUnchanged:

    @pytest.mark.asyncio
    async def test_batch_lookup_clients_tool_still_works(self):
        """The batch_lookup_clients agent tool resolves names without needing the flag."""
        from app.agent.tools import execute_tool
        from app.dependencies import AgentDeps

        deps = MagicMock(spec=AgentDeps)
        mock_resolve = AsyncMock(return_value=[
            {"name": "Ivan King", "status": "matched", "gwm_id": "GWM-300", "confidence": 0.92},
        ])

        with patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_resolve,
        ), patch(
            "app.agent.batch_resolver.format_results_as_compact_json",
            return_value='{"summary":{"total":1,"matched":1,"no_match":0,"errors":0},"results":[{"name":"Ivan King","gwm_id":"GWM-300","confidence":0.92,"status":"matched"}]}',
        ):
            result = await execute_tool(
                "batch_lookup_clients",
                {"people": [{"name": "Ivan King"}]},
                deps,
            )

        assert result  # returns non-empty JSON

    @pytest.mark.asyncio
    async def test_extract_and_lookup_entities_tool_still_works(self):
        """The extract_and_lookup_entities tool still runs extraction + lookup in-memory."""
        from app.agent.tools import execute_tool
        from app.dependencies import AgentDeps

        deps = MagicMock(spec=AgentDeps)
        deps.doc_texts = ["Jane Doe is the CEO of Acme."]
        deps.uploaded_doc_metadata = [{"filename": "roster.pdf"}]
        deps.uploaded_filenames = ["roster.pdf"]

        mock_extract = AsyncMock(return_value=(["Jane Doe"], 1))
        mock_resolve = AsyncMock(return_value=[
            {"name": "Jane Doe", "status": "matched", "gwm_id": "GWM-400", "confidence": 0.85},
        ])

        with patch(
            "app.agent.batch_resolver.extract_person_names",
            mock_extract,
        ), patch(
            "app.agent.batch_resolver.batch_resolve_clients",
            mock_resolve,
        ), patch(
            "app.agent.batch_resolver.format_results_as_compact_json",
            return_value='{"summary":{"total":1,"matched":1,"no_match":0,"errors":0},"results":[{"name":"Jane Doe","gwm_id":"GWM-400","confidence":0.85,"status":"matched"}]}',
        ):
            result = await execute_tool(
                "extract_and_lookup_entities",
                {"filename": "roster.pdf"},
                deps,
            )

        mock_extract.assert_called_once()
        mock_resolve.assert_called_once()
        assert result  # returns non-empty result

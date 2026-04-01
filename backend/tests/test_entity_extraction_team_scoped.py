"""Unit tests for team-scoped entity resolution and flagging (m-clone-659t).

Covers:
  5.1 — db_find_or_create_entity tuple return destructuring
  5.2 — Resolution mode structured logging
  5.3 — Auto-flag master_copy entities
  5.4 — _relationship_already_exists team_id scoping

All tests are unit-level (no Redis, no database, no real LLM calls).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from worker.entity_extraction import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    _relationship_already_exists,
    _store_extraction_result,
)

TEAM_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEAM_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
MASTER_TEAM = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
# 5.1 — Tuple return destructuring
# ---------------------------------------------------------------------------

class TestTupleReturnDestructuring:

    @pytest.mark.asyncio
    async def test_entity_id_stored_from_tuple(self):
        """entity_id from the (id, mode) tuple is used in the entity_id_map."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Apple", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-apple", "team_hit")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch("app.db.db_flag_entity_for_review", AsyncMock()):
            counts = await _store_extraction_result("sess-1", result, team_id=TEAM_A)

        assert counts["entities"] == 1

    @pytest.mark.asyncio
    async def test_inline_subject_entity_destructured(self):
        """Entities created inline for relationships also destructure the tuple."""
        result = ExtractionResult(
            entities=[],
            relationships=[
                ExtractedRelationship(
                    subject="Alice", predicate="owns", predicate_family="ownership",
                    object="Widget Co", confidence=0.9,
                ),
            ],
        )
        _, mock_cm = _make_db_mocks()
        call_count = 0

        async def mock_find_or_create(name, etype, aliases, *, team_id, **kw):
            nonlocal call_count
            call_count += 1
            return (f"uuid-{call_count}", "created")

        with patch(
            "app.db.db_find_or_create_entity", AsyncMock(side_effect=mock_find_or_create),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-1"}),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch("app.db.db_flag_entity_for_review", AsyncMock()):
            counts = await _store_extraction_result("sess-2", result, team_id=TEAM_A)

        assert counts["relationships"] == 1


# ---------------------------------------------------------------------------
# 5.2 — Resolution mode logging
# ---------------------------------------------------------------------------

class TestResolutionModeLogging:

    @pytest.mark.asyncio
    async def test_entity_resolved_log_emitted(self, caplog):
        """An INFO log with entity_resolved is emitted for each resolved entity."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Google", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-google", "team_hit")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch("app.db.db_flag_entity_for_review", AsyncMock()), caplog.at_level(
            logging.INFO, logger="worker.entity_extraction",
        ):
            await _store_extraction_result("sess-log", result, team_id=TEAM_A)

        resolved_logs = [r for r in caplog.records if "entity_resolved" in r.message]
        assert len(resolved_logs) == 1
        log_msg = resolved_logs[0].message
        assert "session=sess-log" in log_msg
        assert f"team={TEAM_A}" in log_msg
        assert "entity=Google" in log_msg
        assert "mode=team_hit" in log_msg
        assert "id=uuid-google" in log_msg

    @pytest.mark.asyncio
    async def test_master_copy_mode_logged(self, caplog):
        """When resolution mode is master_copy, the log reflects that."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Meta", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-meta", "master_copy")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", AsyncMock(),
        ), caplog.at_level(logging.INFO, logger="worker.entity_extraction"):
            await _store_extraction_result("sess-mc", result, team_id=TEAM_A)

        resolved_logs = [r for r in caplog.records if "entity_resolved" in r.message]
        assert len(resolved_logs) == 1
        assert "mode=master_copy" in resolved_logs[0].message

    @pytest.mark.asyncio
    async def test_inline_entity_logging(self, caplog):
        """Inline entities (from relationships) also get entity_resolved logs."""
        result = ExtractionResult(
            entities=[],
            relationships=[
                ExtractedRelationship(
                    subject="Bob", predicate="owns", predicate_family="ownership",
                    object="Acme", confidence=0.9,
                ),
            ],
        )
        _, mock_cm = _make_db_mocks()
        call_idx = 0

        async def mock_find_or_create(name, etype, aliases, *, team_id, **kw):
            nonlocal call_idx
            call_idx += 1
            return (f"uuid-{call_idx}", "created")

        with patch(
            "app.db.db_find_or_create_entity", AsyncMock(side_effect=mock_find_or_create),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-1"}),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", AsyncMock(),
        ), caplog.at_level(logging.INFO, logger="worker.entity_extraction"):
            await _store_extraction_result("sess-inline", result, team_id=TEAM_A)

        resolved_logs = [r for r in caplog.records if "entity_resolved" in r.message]
        # Two entities: subject "Bob" and object "Acme"
        assert len(resolved_logs) == 2
        names_logged = {log.message.split("entity=")[1].split(" ")[0] for log in resolved_logs}
        assert "Bob" in names_logged
        assert "Acme" in names_logged


# ---------------------------------------------------------------------------
# 5.3 — Auto-flag master_copy entities
# ---------------------------------------------------------------------------

class TestAutoFlagMasterCopy:

    @pytest.mark.asyncio
    async def test_flag_called_for_master_copy(self):
        """db_flag_entity_for_review is called when resolution_mode is master_copy."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Netflix", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()
        mock_flag = AsyncMock(return_value={"id": "flag-1"})

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-netflix", "master_copy")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", mock_flag,
        ):
            await _store_extraction_result("sess-flag", result, team_id=TEAM_A)

        mock_flag.assert_called_once_with("uuid-netflix", TEAM_A, "sourced_from_master")

    @pytest.mark.asyncio
    async def test_flag_not_called_for_team_hit(self):
        """db_flag_entity_for_review is NOT called when resolution_mode is team_hit."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Amazon", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()
        mock_flag = AsyncMock()

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-amazon", "team_hit")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", mock_flag,
        ):
            await _store_extraction_result("sess-noflag", result, team_id=TEAM_A)

        mock_flag.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_not_called_for_created(self):
        """db_flag_entity_for_review is NOT called when resolution_mode is created."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="NewCo", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()
        mock_flag = AsyncMock()

        with patch(
            "app.db.db_find_or_create_entity",
            AsyncMock(return_value=("uuid-newco", "created")),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", mock_flag,
        ):
            await _store_extraction_result("sess-created", result, team_id=TEAM_A)

        mock_flag.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_called_for_inline_master_copy(self):
        """Inline entities (from relationships) also trigger flagging on master_copy."""
        result = ExtractionResult(
            entities=[],
            relationships=[
                ExtractedRelationship(
                    subject="Jane", predicate="owns", predicate_family="ownership",
                    object="WidgetCo", confidence=0.9,
                ),
            ],
        )
        _, mock_cm = _make_db_mocks()
        mock_flag = AsyncMock(return_value={"id": "flag-2"})
        call_idx = 0

        async def mock_find_or_create(name, etype, aliases, *, team_id, **kw):
            nonlocal call_idx
            call_idx += 1
            # First call (subject) = master_copy, second (object) = created
            mode = "master_copy" if call_idx == 1 else "created"
            return (f"uuid-{call_idx}", mode)

        with patch(
            "app.db.db_find_or_create_entity", AsyncMock(side_effect=mock_find_or_create),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-1"}),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "app.db.db_flag_entity_for_review", mock_flag,
        ):
            await _store_extraction_result("sess-inline-flag", result, team_id=TEAM_A)

        # Only the subject (master_copy) should be flagged, not the object (created)
        mock_flag.assert_called_once_with("uuid-1", TEAM_A, "sourced_from_master")


# ---------------------------------------------------------------------------
# 5.4 — _relationship_already_exists includes team_id
# ---------------------------------------------------------------------------

class TestRelationshipAlreadyExistsTeamScoped:

    @pytest.mark.asyncio
    async def test_passes_team_id_in_query(self):
        """The query includes team_id as a parameter."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        result = await _relationship_already_exists(
            mock_conn, "subj-id", "obj-id", "owns", "ownership", team_id=TEAM_A,
        )

        assert result is False
        # Verify team_id was passed as a parameter
        call_args = mock_conn.fetchrow.call_args_list[0]
        positional = call_args[0]
        assert TEAM_A in positional

    @pytest.mark.asyncio
    async def test_existing_relationship_found(self):
        """Returns True when an existing relationship matches in the same team."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": "rel-123"})

        result = await _relationship_already_exists(
            mock_conn, "subj-id", "obj-id", "owns", "ownership", team_id=TEAM_A,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_team_id_required_parameter(self):
        """team_id is a required parameter (TypeError if missing)."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        with pytest.raises(TypeError):
            await _relationship_already_exists(
                mock_conn, "subj-id", "obj-id", "owns", "ownership",
            )

    @pytest.mark.asyncio
    async def test_relationship_dedup_uses_effective_team_id(self):
        """The caller in _store_extraction_result passes effective_team_id to dedup."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="Alpha", type="company")],
            relationships=[
                ExtractedRelationship(
                    subject="Alpha", predicate="owns", predicate_family="ownership",
                    object="Beta", confidence=0.9,
                ),
            ],
        )
        _, mock_cm = _make_db_mocks()
        call_idx = 0

        async def mock_find_or_create(name, etype, aliases, *, team_id, **kw):
            nonlocal call_idx
            call_idx += 1
            return (f"uuid-{call_idx}", "team_hit")

        mock_rel_exists = AsyncMock(return_value=False)

        with patch(
            "app.db.db_find_or_create_entity", AsyncMock(side_effect=mock_find_or_create),
        ), patch(
            "app.db.db_upsert_relationship",
            AsyncMock(return_value={"status": "inserted", "new_id": "rel-1"}),
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch(
            "worker.entity_extraction._relationship_already_exists", mock_rel_exists,
        ), patch(
            "app.db.db_flag_entity_for_review", AsyncMock(),
        ):
            await _store_extraction_result("sess-dedup", result, team_id=TEAM_A)

        # Verify _relationship_already_exists was called with team_id=TEAM_A
        mock_rel_exists.assert_called_once()
        _, kwargs = mock_rel_exists.call_args
        assert kwargs.get("team_id") == TEAM_A


# ---------------------------------------------------------------------------
# team_id fallback to settings.kg_master_team_id
# ---------------------------------------------------------------------------

class TestTeamIdFallback:

    @pytest.mark.asyncio
    async def test_none_team_id_falls_back_to_master(self):
        """When team_id is None, effective_team_id uses settings.kg_master_team_id."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="FallbackCo", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()
        mock_find = AsyncMock(return_value=("uuid-fallback", "created"))

        with patch(
            "app.db.db_find_or_create_entity", mock_find,
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch("app.db.db_flag_entity_for_review", AsyncMock()):
            await _store_extraction_result("sess-fallback", result, team_id=None)

        # The call to db_find_or_create_entity should use master team id
        _, kwargs = mock_find.call_args
        assert kwargs["team_id"] == MASTER_TEAM

    @pytest.mark.asyncio
    async def test_explicit_team_id_used_as_is(self):
        """When team_id is provided, it is used directly."""
        result = ExtractionResult(
            entities=[ExtractedEntity(name="ExplicitCo", type="company")],
            relationships=[],
        )
        _, mock_cm = _make_db_mocks()
        mock_find = AsyncMock(return_value=("uuid-explicit", "team_hit"))

        with patch(
            "app.db.db_find_or_create_entity", mock_find,
        ), patch(
            "app.db._pool._acquire", return_value=mock_cm,
        ), patch("app.db.db_flag_entity_for_review", AsyncMock()):
            await _store_extraction_result("sess-explicit", result, team_id=TEAM_B)

        _, kwargs = mock_find.call_args
        assert kwargs["team_id"] == TEAM_B

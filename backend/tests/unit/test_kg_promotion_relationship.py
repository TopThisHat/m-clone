"""Tests for promote_relationships_to_master() in kg_promotion.py.

Validates the SQL fix: relationship lookup and INSERT now use
``team_id = $N::uuid`` with ``settings.kg_master_team_id`` instead of
the previous ``team_id IS NULL`` / ``NULL`` literal.

All tests use mocked DB connections (AsyncMock) so no live database
is required.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MASTER_TEAM_ID = "00000000-0000-0000-0000-000000000001"
TEAM_ID = str(uuid.uuid4())
SUBJECT_TEAM = str(uuid.uuid4())
OBJECT_TEAM = str(uuid.uuid4())
SUBJECT_MASTER = str(uuid.uuid4())
OBJECT_MASTER = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


def _make_rel_row(
    *,
    predicate: str = "acquired",
    predicate_family: str = "acquisition",
    confidence: float = 0.90,
    evidence: str = "press release",
    subject_id: str = SUBJECT_TEAM,
    object_id: str = OBJECT_TEAM,
    source_session_id: str = SESSION_ID,
) -> MagicMock:
    """Create a dict-like mock row for a kg_relationships record."""
    row = MagicMock()
    data = {
        "subject_id": uuid.UUID(subject_id),
        "object_id": uuid.UUID(object_id),
        "predicate": predicate,
        "predicate_family": predicate_family,
        "confidence": confidence,
        "evidence": evidence,
        "source_session_id": source_session_id,
    }
    row.__getitem__ = lambda self, key: data[key]
    row.__contains__ = lambda self, key: key in data
    row.get = lambda key, default=None: data.get(key, default)
    return row


class _FakeTransaction:
    """Async context manager that does nothing (simulates conn.transaction())."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _build_conn_mock(
    fetch_return: list | None = None,
    fetchrow_return=None,
):
    """Build an AsyncMock connection with transaction() support."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.execute = AsyncMock()
    conn.transaction = lambda: _FakeTransaction()
    return conn


@asynccontextmanager
async def _fake_acquire_factory(conn):
    """Replacement for _acquire that yields our mocked connection."""
    yield conn


def _patch_acquire_and_settings(conn):
    """Return a combined context manager that patches _acquire and settings.

    Patches at the source module level so the function-local imports
    inside promote_relationships_to_master() pick up the mocks.
    """
    mock_settings = MagicMock()
    mock_settings.kg_master_team_id = MASTER_TEAM_ID

    return (
        patch("app.db._pool._acquire", lambda: _fake_acquire_factory(conn)),
        patch("app.config.settings", mock_settings),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRelationshipLookupUsesTeamId:
    """Verify the SELECT uses ``team_id = $4::uuid`` with master_team_id."""

    @pytest.mark.asyncio
    async def test_lookup_passes_master_team_id(self):
        """The fetchrow call for existing master relationship must pass
        master_team_id as the 4th positional argument, not use IS NULL."""
        rel_row = _make_rel_row()
        conn = _build_conn_mock(fetch_return=[rel_row], fetchrow_return=None)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            await promote_relationships_to_master(TEAM_ID, entity_id_map)

        # The fetchrow call should have 4 arguments (subject, object, predicate_family, master_team_id)
        fetchrow_call = conn.fetchrow.call_args
        assert fetchrow_call is not None, "fetchrow was not called"

        sql = fetchrow_call[0][0]
        args = fetchrow_call[0][1:]

        assert "team_id = $4::uuid" in sql, (
            f"Expected 'team_id = $4::uuid' in SQL, got: {sql}"
        )
        assert "IS NULL" not in sql, (
            f"SQL should NOT contain 'IS NULL' for team_id, got: {sql}"
        )
        assert args == (SUBJECT_MASTER, OBJECT_MASTER, "acquisition", MASTER_TEAM_ID)


class TestRelationshipInsertUsesTeamId:
    """Verify the INSERT uses ``$8::uuid`` with master_team_id."""

    @pytest.mark.asyncio
    async def test_insert_passes_master_team_id(self):
        """The INSERT must use $8::uuid for team_id, not NULL literal."""
        rel_row = _make_rel_row()
        conn = _build_conn_mock(fetch_return=[rel_row], fetchrow_return=None)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            await promote_relationships_to_master(TEAM_ID, entity_id_map)

        # Find the INSERT execute call (not the UPDATE one)
        insert_call = None
        for c in conn.execute.call_args_list:
            if "INSERT INTO playbook.kg_relationships" in c[0][0]:
                insert_call = c
                break

        assert insert_call is not None, "INSERT execute was not called"

        sql = insert_call[0][0]
        args = insert_call[0][1:]

        assert "$8::uuid" in sql, (
            f"Expected '$8::uuid' in INSERT SQL, got: {sql}"
        )
        assert "NULL)" not in sql, (
            f"INSERT SQL should not end with NULL for team_id, got: {sql}"
        )
        assert args[-1] == MASTER_TEAM_ID, (
            f"Last arg to INSERT should be master_team_id, got: {args[-1]}"
        )
        assert len(args) == 8, f"INSERT should have 8 arguments, got {len(args)}"


class TestDuplicateRelationshipSkipped:
    """When existing master relationship has the same predicate, skip it."""

    @pytest.mark.asyncio
    async def test_duplicate_skipped(self):
        rel_row = _make_rel_row(predicate="acquired", confidence=0.95)

        existing_row = MagicMock()
        existing_data = {
            "id": uuid.UUID(str(uuid.uuid4())),
            "predicate": "acquired",  # Same predicate -> duplicate
        }
        existing_row.__getitem__ = lambda self, key: existing_data[key]

        conn = _build_conn_mock(fetch_return=[rel_row], fetchrow_return=existing_row)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            result = await promote_relationships_to_master(TEAM_ID, entity_id_map)

        assert result == 0, "Duplicate relationships should be skipped (count = 0)"

        # No INSERT should have been called
        for c in conn.execute.call_args_list:
            assert "INSERT INTO playbook.kg_relationships" not in c[0][0]


class TestLowConfidenceConflictSkipped:
    """Conflict with confidence < 0.8 should be skipped for human review."""

    @pytest.mark.asyncio
    async def test_low_confidence_conflict_skipped(self):
        # The DB fetch filters by >= PROMOTION_CONFIDENCE_THRESHOLD (0.85),
        # so in production rows always have confidence >= 0.85.  The conflict
        # skip branch checks < 0.8.  We mock the rows directly, so we can
        # inject a row with confidence = 0.79 to exercise this branch.
        rel_row = _make_rel_row(predicate="partnered_with", confidence=0.79)

        existing_row = MagicMock()
        existing_data = {
            "id": uuid.UUID(str(uuid.uuid4())),
            "predicate": "invested_in",  # Different predicate -> conflict
        }
        existing_row.__getitem__ = lambda self, key: existing_data[key]

        conn = _build_conn_mock(fetch_return=[rel_row], fetchrow_return=existing_row)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            result = await promote_relationships_to_master(TEAM_ID, entity_id_map)

        assert result == 0, "Low-confidence conflicts should be skipped"

        # No INSERT should have been called
        for c in conn.execute.call_args_list:
            assert "INSERT INTO playbook.kg_relationships" not in c[0][0]


class TestHighConfidenceConflictSupersedes:
    """Conflict with confidence >= 0.8 should supersede existing relationship."""

    @pytest.mark.asyncio
    async def test_high_confidence_supersedes(self):
        existing_id = str(uuid.uuid4())
        rel_row = _make_rel_row(predicate="partnered_with", confidence=0.92)

        existing_row = MagicMock()
        existing_data = {
            "id": uuid.UUID(existing_id),
            "predicate": "invested_in",  # Different predicate -> conflict
        }
        existing_row.__getitem__ = lambda self, key: existing_data[key]

        conn = _build_conn_mock(fetch_return=[rel_row], fetchrow_return=existing_row)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            result = await promote_relationships_to_master(TEAM_ID, entity_id_map)

        assert result == 1, "High-confidence conflict should supersede and count as promoted"

        # Should have deactivated the old relationship
        deactivate_calls = [
            c for c in conn.execute.call_args_list
            if "is_active = FALSE" in c[0][0]
        ]
        assert len(deactivate_calls) == 1, "Should deactivate old relationship"
        assert deactivate_calls[0][0][1] == existing_id

        # Should have inserted the new relationship
        insert_calls = [
            c for c in conn.execute.call_args_list
            if "INSERT INTO playbook.kg_relationships" in c[0][0]
        ]
        assert len(insert_calls) == 1, "Should insert new relationship"


class TestPromotedCount:
    """Verify that promoted_count accurately reflects the number of promotions."""

    @pytest.mark.asyncio
    async def test_count_multiple_promotions(self):
        """Two relationships with no existing master counterparts should both promote."""
        subject2_team = str(uuid.uuid4())
        object2_team = str(uuid.uuid4())
        subject2_master = str(uuid.uuid4())
        object2_master = str(uuid.uuid4())

        rel_row_1 = _make_rel_row(predicate="acquired", confidence=0.90)
        rel_row_2 = _make_rel_row(
            predicate="funded",
            predicate_family="funding",
            confidence=0.88,
            subject_id=subject2_team,
            object_id=object2_team,
        )

        conn = _build_conn_mock(
            fetch_return=[rel_row_1, rel_row_2],
            fetchrow_return=None,  # No existing master relationships
        )

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
            OBJECT_TEAM: OBJECT_MASTER,
            subject2_team: subject2_master,
            object2_team: object2_master,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            result = await promote_relationships_to_master(TEAM_ID, entity_id_map)

        assert result == 2, f"Expected 2 promotions, got {result}"

        insert_calls = [
            c for c in conn.execute.call_args_list
            if "INSERT INTO playbook.kg_relationships" in c[0][0]
        ]
        assert len(insert_calls) == 2

    @pytest.mark.asyncio
    async def test_count_zero_when_no_relationships(self):
        """No team relationships means zero promoted."""
        conn = _build_conn_mock(fetch_return=[], fetchrow_return=None)

        entity_id_map = {
            SUBJECT_TEAM: SUBJECT_MASTER,
        }

        p1, p2 = _patch_acquire_and_settings(conn)
        with p1, p2:
            from worker.workflows.kg_promotion import promote_relationships_to_master

            result = await promote_relationships_to_master(TEAM_ID, entity_id_map)

        assert result == 0

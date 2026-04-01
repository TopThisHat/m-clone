"""Tests for promote_entity_to_master() SQL fixes (bead m-clone-xecs).

Validates:
  - master_team_id from settings is used (not NULL) in lookup and INSERT
  - ON CONFLICT uses (LOWER(name), team_id), not ((LOWER(name)))
  - metadata parameter uses ::jsonb cast
  - "already_exists" path merges aliases correctly

These are pure unit tests (no DB required). The autouse _ensure_schema
fixture from conftest.py is overridden below to avoid needing a live
PostgreSQL connection.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Override the autouse fixture from conftest.py so these unit tests
# do not require a running database.
@pytest.fixture(autouse=True)
def _ensure_schema():
    """No-op override — these tests mock the DB entirely."""
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_MASTER_TEAM_ID = "00000000-0000-0000-0000-000000000099"
FAKE_ENTITY_ID = str(uuid.uuid4())
FAKE_TEAM_ID = str(uuid.uuid4())
FAKE_MASTER_ID = str(uuid.uuid4())


def _make_entity_record(
    name: str = "Acme Corp",
    entity_type: str = "organization",
    aliases: list[str] | None = None,
    metadata: str | None = None,
) -> dict[str, Any]:
    """Return a dict that behaves like an asyncpg Record for testing."""
    return {
        "id": uuid.UUID(FAKE_ENTITY_ID),
        "name": name,
        "entity_type": entity_type,
        "aliases": aliases or ["ACME"],
        "metadata": metadata or '{"source": "test"}',
    }


class _FakeConn:
    """Minimal stub matching the asyncpg connection interface used by
    promote_entity_to_master.  Captures SQL strings + args for assertions."""

    def __init__(
        self,
        entity_row: dict[str, Any] | None,
        existing_master: dict[str, Any] | None = None,
        insert_master: dict[str, Any] | None = None,
    ) -> None:
        self._entity_row = entity_row
        self._existing_master = existing_master
        self._insert_master = insert_master

        # Capture all SQL calls
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append((sql, args))
        # First fetchrow: load entity
        if "FROM playbook.kg_entities WHERE id" in sql:
            return self._entity_row
        # Second fetchrow: check existing master
        if "FROM playbook.kg_entities" in sql and "LOWER(name)" in sql and "INSERT" not in sql:
            return self._existing_master
        # Third fetchrow: INSERT ... RETURNING id
        if "INSERT INTO playbook.kg_entities" in sql:
            return self._insert_master
        return None

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append((sql, args))

    def transaction(self) -> "_FakeTxn":
        return _FakeTxn()


class _FakeTxn:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        pass


class _FakeAcquire:
    """Context manager that yields a _FakeConn."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Unit tests — mock the DB connection
# ---------------------------------------------------------------------------


class TestPromoteEntitySQL:
    """Verify that the SQL emitted by promote_entity_to_master is correct."""

    @pytest.mark.asyncio
    async def test_master_lookup_uses_team_id_not_null(self) -> None:
        """The SELECT that checks for an existing master entity must use
        ``team_id = $2::uuid`` with settings.kg_master_team_id, not
        ``team_id IS NULL``."""
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        # Find the master-lookup SQL call
        lookup_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "LOWER(name) = LOWER" in sql and "INSERT" not in sql
        ]
        assert len(lookup_calls) == 1, f"Expected 1 master lookup call, got {len(lookup_calls)}"
        sql, args = lookup_calls[0]

        # Must NOT contain "IS NULL"
        assert "team_id IS NULL" not in sql, (
            "Master lookup must use team_id = $2::uuid, not IS NULL"
        )
        # Must contain parameterised team_id comparison
        assert "team_id = $2::uuid" in sql
        # Second argument must be the master team id
        assert args[1] == FAKE_MASTER_TEAM_ID

    @pytest.mark.asyncio
    async def test_insert_on_conflict_uses_team_id(self) -> None:
        """The INSERT ON CONFLICT clause must be
        ``(LOWER(name), team_id)`` not ``((LOWER(name)))``."""
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        insert_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "INSERT INTO playbook.kg_entities" in sql
        ]
        assert len(insert_calls) == 1
        sql, args = insert_calls[0]

        assert "ON CONFLICT (LOWER(name), team_id)" in sql, (
            f"Expected ON CONFLICT (LOWER(name), team_id), got: {sql}"
        )
        # Must NOT have the old double-paren form
        assert "((LOWER(name)))" not in sql

    @pytest.mark.asyncio
    async def test_insert_metadata_has_jsonb_cast(self) -> None:
        """The INSERT must cast metadata with ::jsonb ($4::jsonb)."""
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        insert_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "INSERT INTO playbook.kg_entities" in sql
        ]
        assert len(insert_calls) == 1
        sql, _ = insert_calls[0]

        assert "$4::jsonb" in sql, (
            f"Expected $4::jsonb cast for metadata, got: {sql}"
        )

    @pytest.mark.asyncio
    async def test_insert_passes_master_team_id_as_fifth_arg(self) -> None:
        """The INSERT fetchrow must receive master_team_id as the 5th
        positional argument (matching $5::uuid)."""
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        insert_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "INSERT INTO playbook.kg_entities" in sql
        ]
        assert len(insert_calls) == 1
        sql, args = insert_calls[0]

        assert "$5::uuid" in sql
        # args: (name, entity_type, aliases, metadata, master_team_id)
        assert len(args) == 5, f"Expected 5 args, got {len(args)}: {args}"
        assert args[4] == FAKE_MASTER_TEAM_ID

    @pytest.mark.asyncio
    async def test_already_exists_merges_aliases(self) -> None:
        """When an entity already exists in the master graph, aliases from
        the team entity must be merged via UPDATE."""
        team_aliases = ["ACME", "Acme Inc"]
        conn = _FakeConn(
            entity_row=_make_entity_record(aliases=team_aliases),
            existing_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            result = await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        assert result["action"] == "already_exists"
        assert result["master_entity_id"] == FAKE_MASTER_ID

        # Check that UPDATE was called with the aliases
        update_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "UPDATE playbook.kg_entities" in sql and "aliases" in sql
        ]
        assert len(update_calls) == 1
        sql, args = update_calls[0]

        assert "array_agg(DISTINCT a)" in sql
        assert "unnest(aliases || $2::text[])" in sql
        # Second arg should be the team aliases list
        assert args[1] == team_aliases

    @pytest.mark.asyncio
    async def test_skipped_when_entity_not_found(self) -> None:
        """When the team entity does not exist, action should be 'skipped'."""
        conn = _FakeConn(entity_row=None)
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            result = await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        assert result == {"action": "skipped", "master_entity_id": None}

    @pytest.mark.asyncio
    async def test_promoted_returns_master_id(self) -> None:
        """A successful promotion returns action='promoted' and the new master id."""
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            result = await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        assert result["action"] == "promoted"
        assert result["master_entity_id"] == FAKE_MASTER_ID

    @pytest.mark.asyncio
    async def test_promotion_records_in_kg_promotions(self) -> None:
        """Both 'promoted' and 'already_exists' paths must INSERT into
        playbook.kg_promotions."""
        # Test the "promoted" path
        conn = _FakeConn(
            entity_row=_make_entity_record(),
            existing_master=None,
            insert_master={"id": uuid.UUID(FAKE_MASTER_ID)},
        )
        settings_mock = MagicMock()
        settings_mock.kg_master_team_id = FAKE_MASTER_TEAM_ID

        with (
            patch("app.db._pool._acquire", return_value=_FakeAcquire(conn)),
            patch("app.config.settings", settings_mock),
        ):
            from worker.workflows.kg_promotion import promote_entity_to_master
            await promote_entity_to_master(FAKE_ENTITY_ID, FAKE_TEAM_ID)

        promo_calls = [
            (sql, args)
            for sql, args in conn.calls
            if "INSERT INTO playbook.kg_promotions" in sql
        ]
        assert len(promo_calls) == 1
        _, args = promo_calls[0]
        assert args[0] == FAKE_TEAM_ID
        assert args[1] == FAKE_MASTER_ID

"""Unit tests for Programs business logic and validation.

Tests Pydantic model validation, row-to-dict conversion, and
edge cases without requiring a database connection.
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.program import ProgramCreate, ProgramOut, ProgramUpdate


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Pydantic Model Validation
# ---------------------------------------------------------------------------

class TestProgramCreateModel:

    def test_minimal_create(self):
        body = ProgramCreate(name="2024 NFL Draft")
        assert body.name == "2024 NFL Draft"
        assert body.description is None
        assert body.team_id is None

    def test_full_create(self):
        body = ProgramCreate(
            name="NBA Free Agency 2024",
            description="Track all NBA free agent signings",
            team_id="abc-123",
        )
        assert body.name == "NBA Free Agency 2024"
        assert body.description == "Track all NBA free agent signings"
        assert body.team_id == "abc-123"

    def test_create_requires_name(self):
        with pytest.raises(Exception):
            ProgramCreate()


class TestProgramUpdateModel:

    def test_empty_update(self):
        body = ProgramUpdate()
        assert body.name is None
        assert body.description is None

    def test_partial_update_name(self):
        body = ProgramUpdate(name="Updated Name")
        assert body.name == "Updated Name"
        assert body.description is None

    def test_partial_update_description(self):
        body = ProgramUpdate(description="New desc")
        assert body.name is None
        assert body.description == "New desc"

    def test_full_update(self):
        body = ProgramUpdate(name="New Name", description="New desc")
        assert body.name == "New Name"
        assert body.description == "New desc"


class TestProgramOutModel:

    def test_out_roundtrip(self):
        out = ProgramOut(
            id="abc",
            owner_sid="user-1",
            team_id=None,
            name="Test Program",
            description="A description",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert out.id == "abc"
        assert out.owner_sid == "user-1"
        assert out.team_id is None
        assert out.name == "Test Program"

    def test_out_with_team_id(self):
        out = ProgramOut(
            id="abc",
            owner_sid="user-1",
            team_id="team-xyz",
            name="Team Program",
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert out.team_id == "team-xyz"

    def test_out_requires_mandatory_fields(self):
        with pytest.raises(Exception):
            ProgramOut(id="abc")


# ---------------------------------------------------------------------------
# Row-to-dict conversion
# ---------------------------------------------------------------------------

class TestProgramRowToDict:

    def test_uuid_fields_converted_to_str(self):
        from app.db.programs import _program_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "team_id": uuid4(),
            "owner_sid": "user-1",
            "name": "Test",
            "description": None,
            "created_at": now,
            "updated_at": now,
        }
        result = _program_row_to_dict(row_dict)
        assert isinstance(result["id"], str)
        assert isinstance(result["team_id"], str)
        assert isinstance(result["created_at"], str)
        assert isinstance(result["updated_at"], str)

    def test_none_uuid_stays_none(self):
        from app.db.programs import _program_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "team_id": None,
            "owner_sid": "user-1",
            "name": "Test",
            "description": None,
            "created_at": now,
            "updated_at": now,
        }
        result = _program_row_to_dict(row_dict)
        assert result["team_id"] is None

    def test_none_timestamp_stays_none(self):
        from app.db.programs import _program_row_to_dict

        row_dict = {
            "id": uuid4(),
            "team_id": None,
            "owner_sid": "user-1",
            "name": "Test",
            "description": None,
            "created_at": None,
            "updated_at": None,
        }
        result = _program_row_to_dict(row_dict)
        assert result["created_at"] is None
        assert result["updated_at"] is None


# ---------------------------------------------------------------------------
# DB function logic (mocked DB)
# ---------------------------------------------------------------------------

class TestDbUpdateProgramLogic:

    @pytest.mark.asyncio
    async def test_noop_update_calls_get(self):
        """When no fields are provided, db_update_program fetches current state."""
        from app.db import programs

        fake_program = {
            "id": str(uuid4()),
            "owner_sid": "user-1",
            "team_id": None,
            "name": "Unchanged",
            "description": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        with patch.object(programs, "db_get_program", new_callable=AsyncMock, return_value=fake_program):
            result = await programs.db_update_program(fake_program["id"])
            assert result == fake_program

    @pytest.mark.asyncio
    async def test_delete_returns_bool(self):
        """db_delete_program returns True when DELETE affected 1 row."""
        from app.db import programs

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(programs, "_acquire", return_value=mock_cm):
            result = await programs.db_delete_program(str(uuid4()))
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_no_rows(self):
        """db_delete_program returns False when DELETE affected 0 rows."""
        from app.db import programs

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(programs, "_acquire", return_value=mock_cm):
            result = await programs.db_delete_program(str(uuid4()))
            assert result is False

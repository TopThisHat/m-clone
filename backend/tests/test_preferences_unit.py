"""Unit tests for Preferences DB layer and Pydantic models.

Tests row-to-dict conversion, get/upsert logic using mocked asyncpg
connections, and model validation. No running database required.
"""
from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.preference import PreferencesOut, PreferencesUpsert


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Pydantic Model Validation
# ---------------------------------------------------------------------------

class TestPreferencesUpsertModel:

    def test_minimal_upsert(self):
        body = PreferencesUpsert(preferences={"sort_order": "asc"})
        assert body.preferences == {"sort_order": "asc"}
        assert body.campaign_id is None

    def test_full_upsert(self):
        body = PreferencesUpsert(
            campaign_id="abc-123",
            preferences={"columns": ["name", "score"], "sort_order": "desc"},
        )
        assert body.campaign_id == "abc-123"
        assert body.preferences["columns"] == ["name", "score"]

    def test_upsert_requires_preferences(self):
        with pytest.raises(Exception):
            PreferencesUpsert()

    def test_upsert_empty_preferences(self):
        body = PreferencesUpsert(preferences={})
        assert body.preferences == {}


class TestPreferencesOutModel:

    def test_out_roundtrip(self):
        out = PreferencesOut(
            id="abc",
            user_sid="user-1",
            campaign_id=None,
            preferences={"theme": "dark"},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert out.id == "abc"
        assert out.user_sid == "user-1"
        assert out.campaign_id is None
        assert out.preferences == {"theme": "dark"}

    def test_out_with_campaign_id(self):
        out = PreferencesOut(
            id="abc",
            user_sid="user-1",
            campaign_id="camp-xyz",
            preferences={},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert out.campaign_id == "camp-xyz"

    def test_out_requires_mandatory_fields(self):
        with pytest.raises(Exception):
            PreferencesOut(id="abc")


# ---------------------------------------------------------------------------
# Row-to-dict conversion
# ---------------------------------------------------------------------------

class TestPreferenceRowToDict:

    def test_uuid_fields_converted_to_str(self):
        from app.db.preferences import _preference_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": uuid4(),
            "preferences": {"sort": "asc"},
            "created_at": now,
            "updated_at": now,
        }
        result = _preference_row_to_dict(row_dict)
        assert isinstance(result["id"], str)
        assert isinstance(result["campaign_id"], str)
        assert isinstance(result["created_at"], str)
        assert isinstance(result["updated_at"], str)

    def test_none_campaign_id_stays_none(self):
        from app.db.preferences import _preference_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": {},
            "created_at": now,
            "updated_at": now,
        }
        result = _preference_row_to_dict(row_dict)
        assert result["campaign_id"] is None

    def test_none_timestamps_stay_none(self):
        from app.db.preferences import _preference_row_to_dict

        row_dict = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": {},
            "created_at": None,
            "updated_at": None,
        }
        result = _preference_row_to_dict(row_dict)
        assert result["created_at"] is None
        assert result["updated_at"] is None

    def test_json_string_preferences_decoded(self):
        from app.db.preferences import _preference_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": json.dumps({"columns": ["a", "b"]}),
            "created_at": now,
            "updated_at": now,
        }
        result = _preference_row_to_dict(row_dict)
        assert result["preferences"] == {"columns": ["a", "b"]}


# ---------------------------------------------------------------------------
# db_get_preferences (mocked DB)
# ---------------------------------------------------------------------------

class TestDbGetPreferences:

    @pytest.mark.asyncio
    async def test_get_global_preferences(self):
        from app.db import preferences

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": {"sort": "asc"},
            "created_at": now,
            "updated_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            result = await preferences.db_get_preferences("user-1")
            assert result is not None
            assert result["user_sid"] == "user-1"
            assert result["campaign_id"] is None
            # Verify SQL checks for NULL campaign_id
            sql = mock_conn.fetchrow.call_args[0][0]
            assert "campaign_id IS NULL" in sql

    @pytest.mark.asyncio
    async def test_get_campaign_preferences(self):
        from app.db import preferences

        now = datetime.datetime.now(datetime.timezone.utc)
        campaign_id = uuid4()
        fake_row = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": campaign_id,
            "preferences": {"columns": ["name"]},
            "created_at": now,
            "updated_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            result = await preferences.db_get_preferences("user-1", str(campaign_id))
            assert result is not None
            assert result["campaign_id"] == str(campaign_id)
            # Verify SQL uses campaign_id parameter
            sql = mock_conn.fetchrow.call_args[0][0]
            assert "campaign_id = $2" in sql

    @pytest.mark.asyncio
    async def test_get_returns_none_when_missing(self):
        from app.db import preferences

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            result = await preferences.db_get_preferences("user-1")
            assert result is None


# ---------------------------------------------------------------------------
# db_upsert_preferences (mocked DB)
# ---------------------------------------------------------------------------

class TestDbUpsertPreferences:

    @pytest.mark.asyncio
    async def test_upsert_returns_dict(self):
        from app.db import preferences

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": {"sort": "desc"},
            "created_at": now,
            "updated_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            result = await preferences.db_upsert_preferences(
                "user-1", None, {"sort": "desc"}
            )
            assert isinstance(result["id"], str)
            assert result["preferences"] == {"sort": "desc"}

    @pytest.mark.asyncio
    async def test_upsert_sql_contains_on_conflict(self):
        from app.db import preferences

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": None,
            "preferences": {},
            "created_at": now,
            "updated_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            await preferences.db_upsert_preferences("user-1", None, {})
            sql = mock_conn.fetchrow.call_args[0][0]
            assert "ON CONFLICT" in sql
            assert "DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_upsert_with_campaign_id(self):
        from app.db import preferences

        campaign_id = str(uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "user_sid": "user-1",
            "campaign_id": uuid4(),
            "preferences": {"view": "grid"},
            "created_at": now,
            "updated_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(preferences, "_acquire", return_value=mock_cm):
            result = await preferences.db_upsert_preferences(
                "user-1", campaign_id, {"view": "grid"}
            )
            assert result is not None
            # Verify campaign_id was passed as argument
            call_args = mock_conn.fetchrow.call_args[0]
            assert call_args[1] == "user-1"
            assert call_args[2] == campaign_id

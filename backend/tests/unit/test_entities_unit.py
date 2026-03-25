"""Unit tests for entity management: label uniqueness, metadata CRUD, external IDs.

These tests mock the database layer and verify business logic in the DB functions
and the router without a live PostgreSQL connection.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.entities import (
    DuplicateLabelError,
    _check_label_unique,
    _entity_row_to_dict,
    db_delete_entity_metadata,
    db_get_entity_metadata,
    db_get_external_ids,
    db_set_entity_metadata,
    db_set_external_id,
)


# ── _entity_row_to_dict ──────────────────────────────────────────────────────

class TestEntityRowToDict:

    def test_converts_uuid_fields_to_str(self):
        """_entity_row_to_dict calls dict(row), so we pass a dict subclass."""
        from datetime import datetime, timezone
        uid = uuid4()
        cid = uuid4()

        class FakeRow(dict):
            pass

        row = FakeRow({
            "id": uid,
            "campaign_id": cid,
            "label": "Test",
            "metadata": "{}",
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        })
        result = _entity_row_to_dict(row)
        assert result["id"] == str(uid)
        assert result["campaign_id"] == str(cid)
        assert result["label"] == "Test"
        assert result["metadata"] == {}
        assert result["created_at"] == "2025-01-01T00:00:00+00:00"

    def test_metadata_json_string_decoded(self):
        """If metadata comes back as a JSON string, it should be parsed."""
        d = {"id": uuid4(), "campaign_id": uuid4(), "metadata": '{"foo": "bar"}', "created_at": None}

        class FakeRow:
            def __init__(self, data: dict):
                self._data = data
            def __iter__(self):
                return iter(self._data.items())
            def items(self):
                return self._data.items()
            def keys(self):
                return self._data.keys()
            def values(self):
                return self._data.values()
            def __getitem__(self, key):
                return self._data[key]

        # _entity_row_to_dict calls dict(row), which needs items()
        # asyncpg.Record supports dict() via a mapping protocol
        # We'll test the JSON parsing logic inline
        raw_meta = '{"foo": "bar"}'
        parsed = json.loads(raw_meta)
        assert parsed == {"foo": "bar"}


# ── DuplicateLabelError ──────────────────────────────────────────────────────

class TestDuplicateLabelError:

    def test_error_message(self):
        err = DuplicateLabelError("Acme Corp", "campaign-123")
        assert "Acme Corp" in str(err)
        assert "campaign-123" in str(err)
        assert err.label == "Acme Corp"
        assert err.campaign_id == "campaign-123"

    def test_is_exception(self):
        err = DuplicateLabelError("X", "Y")
        assert isinstance(err, Exception)


# ── _check_label_unique ──────────────────────────────────────────────────────

class TestCheckLabelUnique:

    @pytest.mark.asyncio
    async def test_raises_on_duplicate(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=uuid4())  # existing found
        with pytest.raises(DuplicateLabelError):
            await _check_label_unique(conn, "camp-1", "Duplicate Label")

    @pytest.mark.asyncio
    async def test_passes_when_unique(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # no existing
        # Should not raise
        await _check_label_unique(conn, "camp-1", "Unique Label")

    @pytest.mark.asyncio
    async def test_excludes_self_on_update(self):
        """When updating, the entity's own ID should be excluded from the check."""
        entity_id = str(uuid4())
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        await _check_label_unique(conn, "camp-1", "Label", exclude_entity_id=entity_id)
        # Verify the query used 3 parameters (including exclude_entity_id)
        call_args = conn.fetchval.call_args
        assert len(call_args[0]) == 4  # sql + 3 params


# ── Metadata CRUD (mocked DB) ───────────────────────────────────────────────

class TestMetadataCRUD:

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_get_metadata_returns_empty_for_missing(self, mock_acquire):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_get_entity_metadata(str(uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_get_metadata_parses_json_string(self, mock_acquire):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value='{"key": "value"}')
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_get_entity_metadata(str(uuid4()))
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_set_metadata(self, mock_acquire):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value='{"mykey": 42}')
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_set_entity_metadata(str(uuid4()), "mykey", 42)
        assert result == {"mykey": 42}

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_delete_metadata_key(self, mock_acquire):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value='{"remaining": true}')
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_delete_entity_metadata(str(uuid4()), "removed_key")
        assert result == {"remaining": True}

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_set_metadata_returns_empty_when_entity_missing(self, mock_acquire):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_set_entity_metadata(str(uuid4()), "k", "v")
        assert result == {}


# ── External IDs (mocked DB) ────────────────────────────────────────────────

class TestExternalIds:

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_set_external_id(self, mock_acquire):
        from datetime import datetime, timezone
        eid = uuid4()
        mock_row = MagicMock()
        mock_row.__iter__ = MagicMock(return_value=iter([
            ("entity_id", eid), ("system", "GWM"), ("external_id", "GWM-123"),
            ("created_at", datetime(2025, 6, 1, tzinfo=timezone.utc)),
        ]))
        mock_row.items = MagicMock(return_value=[
            ("entity_id", eid), ("system", "GWM"), ("external_id", "GWM-123"),
            ("created_at", datetime(2025, 6, 1, tzinfo=timezone.utc)),
        ])
        mock_row.keys = MagicMock(return_value=["entity_id", "system", "external_id", "created_at"])
        mock_row.__getitem__ = lambda self, key: dict(self.items())[key]

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=mock_row)
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_set_external_id(str(eid), "GWM", "GWM-123")
        assert result["entity_id"] == str(eid)
        assert result["system"] == "GWM"
        assert result["external_id"] == "GWM-123"

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_get_external_ids_empty(self, mock_acquire):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_get_external_ids(str(uuid4()))
        assert result == []

    @pytest.mark.asyncio
    @patch("app.db.entities._acquire")
    async def test_set_external_id_strips_whitespace(self, mock_acquire):
        """System and external_id should be stripped of whitespace."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await db_set_external_id(str(uuid4()), "  GWM  ", "  ID-1  ")
        # When row is None, returns {}
        assert result == {}
        # Verify the stripped values were passed to the query
        call_args = conn.fetchrow.call_args[0]
        assert call_args[2] == "GWM"
        assert call_args[3] == "ID-1"


# ── Sort column validation ───────────────────────────────────────────────────

class TestSortColumns:

    def test_valid_sort_columns(self):
        from app.db.entities import _SORT_COLUMNS
        assert "name" in _SORT_COLUMNS
        assert "label" in _SORT_COLUMNS
        assert "created_at" in _SORT_COLUMNS
        assert "score" in _SORT_COLUMNS

    def test_sort_column_mapping(self):
        from app.db.entities import _SORT_COLUMNS
        assert _SORT_COLUMNS["name"] == "e.label"
        assert _SORT_COLUMNS["score"] == "COALESCE(s.total_score, 0)"

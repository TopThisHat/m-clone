"""Unit tests for comment team attribution.

Tests Pydantic model validation and DB helper logic without a live database.
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.routers.comments import CommentCreate, HighlightAnchor


# Override the autouse schema fixture — no DB needed for unit tests.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# CommentCreate model
# ---------------------------------------------------------------------------

class TestCommentCreateModel:

    def test_minimal_create_no_team(self):
        body = CommentCreate(body="Hello world")
        assert body.body == "Hello world"
        assert body.team_id is None
        assert body.parent_id is None
        assert body.comment_type == "comment"

    def test_create_with_team_id(self):
        team_uuid = str(uuid.uuid4())
        body = CommentCreate(body="Team comment", team_id=team_uuid)
        assert body.team_id == team_uuid

    def test_create_team_id_none_is_valid(self):
        body = CommentCreate(body="Personal comment", team_id=None)
        assert body.team_id is None

    def test_create_requires_body(self):
        with pytest.raises(Exception):
            CommentCreate()

    def test_create_with_all_fields(self):
        team_uuid = str(uuid.uuid4())
        parent_uuid = str(uuid.uuid4())
        body = CommentCreate(
            body="Suggestion text",
            parent_id=parent_uuid,
            highlight_anchor=HighlightAnchor(quote="some text"),
            comment_type="suggestion",
            proposed_text="replacement",
            team_id=team_uuid,
        )
        assert body.team_id == team_uuid
        assert body.comment_type == "suggestion"
        assert body.proposed_text == "replacement"


# ---------------------------------------------------------------------------
# db_create_comment signature
# ---------------------------------------------------------------------------

class TestDbCreateCommentSignature:

    @pytest.mark.asyncio
    async def test_create_comment_accepts_team_fields(self):
        """db_create_comment must accept team_id and team_name kwargs."""
        from app.db import comments as comments_module

        expected_row = {
            "id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "author_sid": "user-1",
            "body": "Hello",
            "mentions": "[]",
            "parent_id": None,
            "highlight_anchor": None,
            "comment_type": "comment",
            "proposed_text": None,
            "suggestion_status": "open",
            "team_id": uuid.uuid4(),
            "team_name": "Acme Corp",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=MagicMock(**expected_row, **{"__iter__": lambda s: iter(expected_row.items()), "keys": lambda s: expected_row.keys()}))

        # Use a real asyncpg.Record-like dict via MagicMock
        mock_record = dict(expected_row)

        class FakeRecord:
            def __iter__(self):
                return iter(mock_record.items())
            def keys(self):
                return mock_record.keys()
            def __getitem__(self, k):
                return mock_record[k]
            def __contains__(self, k):
                return k in mock_record

        mock_conn.fetchrow = AsyncMock(return_value=FakeRecord())

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        team_id = str(uuid.uuid4())
        with patch.object(comments_module, "_acquire", return_value=mock_cm):
            result = await comments_module.db_create_comment(
                session_id=str(uuid.uuid4()),
                author_sid="user-1",
                body="Hello",
                mentions=[],
                team_id=team_id,
                team_name="Acme Corp",
            )
        # fetchrow was called — function accepted the new kwargs without error
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_comment_null_team_is_default(self):
        """db_create_comment defaults team_id and team_name to None."""
        from app.db import comments as comments_module

        mock_record = {
            "id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "author_sid": "user-1",
            "body": "Hello",
            "mentions": "[]",
            "parent_id": None,
            "highlight_anchor": None,
            "comment_type": "comment",
            "proposed_text": None,
            "suggestion_status": "open",
            "team_id": None,
            "team_name": None,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }

        class FakeRecord:
            def __iter__(self): return iter(mock_record.items())
            def keys(self): return mock_record.keys()
            def __getitem__(self, k): return mock_record[k]
            def __contains__(self, k): return k in mock_record

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=FakeRecord())

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(comments_module, "_acquire", return_value=mock_cm):
            # No team_id / team_name — should not raise
            result = await comments_module.db_create_comment(
                session_id=str(uuid.uuid4()),
                author_sid="user-1",
                body="Hello",
                mentions=[],
            )
        assert result["team_id"] is None
        assert result["team_name"] is None


# ---------------------------------------------------------------------------
# Comment response shape (team fields present)
# ---------------------------------------------------------------------------

class TestCommentResponseShape:

    def test_row_to_dict_includes_team_fields(self):
        """_row_to_dict must convert team_id UUID to str and pass through team_name."""
        from app.db.comments import _row_to_dict

        team_uuid = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)
        row = {
            "id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "author_sid": "user-1",
            "body": "Hello",
            "mentions": "[]",
            "parent_id": None,
            "highlight_anchor": None,
            "comment_type": "comment",
            "proposed_text": None,
            "suggestion_status": "open",
            "team_id": team_uuid,
            "team_name": "Acme Corp",
            "created_at": now,
            "updated_at": now,
        }

        # _row_to_dict expects an asyncpg.Record-like object
        class FakeRecord:
            def __iter__(self): return iter(row.items())
            def keys(self): return row.keys()
            def __getitem__(self, k): return row[k]
            def __contains__(self, k): return k in row

        result = _row_to_dict(FakeRecord())
        assert isinstance(result["team_id"], str)
        assert result["team_id"] == str(team_uuid)
        assert result["team_name"] == "Acme Corp"

    def test_row_to_dict_null_team_stays_none(self):
        """team_id = NULL in DB must stay None (not raise) in _row_to_dict."""
        from app.db.comments import _row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row = {
            "id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "author_sid": "user-1",
            "body": "Personal",
            "mentions": "[]",
            "parent_id": None,
            "highlight_anchor": None,
            "comment_type": "comment",
            "proposed_text": None,
            "suggestion_status": "open",
            "team_id": None,
            "team_name": None,
            "created_at": now,
            "updated_at": now,
        }

        class FakeRecord:
            def __iter__(self): return iter(row.items())
            def keys(self): return row.keys()
            def __getitem__(self, k): return row[k]
            def __contains__(self, k): return k in row

        result = _row_to_dict(FakeRecord())
        assert result["team_id"] is None
        assert result["team_name"] is None

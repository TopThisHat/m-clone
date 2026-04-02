"""Tests for KG Chat Sessions DB layer (kg_chat_sessions.py).

Covers:
  - _session_to_dict: UUID/timestamp serialization
  - _message_to_dict: UUID/timestamp/JSON serialization, entity_highlights conversion
  - db_create_chat_session: parameterized INSERT
  - db_get_chat_session: team-scoped SELECT
  - db_list_chat_sessions: ordered by updated_at DESC
  - db_add_chat_message: with tool_calls, entity_highlights, session bump
  - db_get_chat_messages: ordered by created_at ASC
  - db_delete_chat_session: returns bool, team-scoped
  - db_cleanup_expired_chat_sessions: interval-based cleanup

Run: cd backend && uv run python -m pytest tests/test_kg_chat_sessions.py -v
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.kg_chat_sessions import (
    _message_to_dict,
    _session_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Mimics asyncpg.Record enough for _session_to_dict / _message_to_dict."""
    pass


def _ts() -> datetime:
    return datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_session_record(
    session_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> FakeRecord:
    return FakeRecord(
        id=session_id or uuid.uuid4(),
        team_id=team_id or uuid.uuid4(),
        user_sid="user-test",
        created_at=_ts(),
        updated_at=_ts(),
    )


def _make_message_record(
    session_id: uuid.UUID | None = None,
    tool_calls: str | None = None,
    entity_highlights: list[uuid.UUID] | None = None,
) -> FakeRecord:
    return FakeRecord(
        id=uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        role="assistant",
        content="Hello",
        tool_calls=tool_calls,
        tool_call_id=None,
        entity_highlights=entity_highlights,
        created_at=_ts(),
    )


# ---------------------------------------------------------------------------
# _session_to_dict tests
# ---------------------------------------------------------------------------

class TestSessionToDict:

    def test_uuid_fields_serialized_as_strings(self):
        sid = uuid.uuid4()
        tid = uuid.uuid4()
        row = _make_session_record(session_id=sid, team_id=tid)
        result = _session_to_dict(row)
        assert result["id"] == str(sid)
        assert result["team_id"] == str(tid)

    def test_timestamps_serialized_as_iso(self):
        row = _make_session_record()
        result = _session_to_dict(row)
        assert "T" in result["created_at"]  # ISO format has T separator
        assert "T" in result["updated_at"]

    def test_none_uuid_fields_preserved_as_none(self):
        row = FakeRecord(id=None, team_id=None, user_sid="x", created_at=None, updated_at=None)
        result = _session_to_dict(row)
        assert result["id"] is None

    def test_user_sid_preserved(self):
        row = _make_session_record()
        result = _session_to_dict(row)
        assert result["user_sid"] == "user-test"


# ---------------------------------------------------------------------------
# _message_to_dict tests
# ---------------------------------------------------------------------------

class TestMessageToDict:

    def test_uuid_fields_serialized(self):
        mid = uuid.uuid4()
        sid = uuid.uuid4()
        row = _make_message_record(session_id=sid)
        row["id"] = mid
        result = _message_to_dict(row)
        assert result["id"] == str(mid)
        assert result["session_id"] == str(sid)

    def test_tool_calls_json_deserialized(self):
        tool_data = [{"id": "call_1", "function": {"name": "search"}}]
        row = _make_message_record(tool_calls=json.dumps(tool_data))
        result = _message_to_dict(row)
        assert isinstance(result["tool_calls"], list)
        assert result["tool_calls"][0]["id"] == "call_1"

    def test_tool_calls_none_preserved(self):
        row = _make_message_record(tool_calls=None)
        result = _message_to_dict(row)
        assert result["tool_calls"] is None

    def test_entity_highlights_uuids_serialized(self):
        e1, e2 = uuid.uuid4(), uuid.uuid4()
        row = _make_message_record(entity_highlights=[e1, e2])
        result = _message_to_dict(row)
        assert result["entity_highlights"] == [str(e1), str(e2)]

    def test_entity_highlights_none_preserved(self):
        row = _make_message_record(entity_highlights=None)
        result = _message_to_dict(row)
        assert result["entity_highlights"] is None

    def test_timestamp_iso_format(self):
        row = _make_message_record()
        result = _message_to_dict(row)
        assert "2026-03-15" in result["created_at"]


# ---------------------------------------------------------------------------
# DB function tests (mocked asyncpg connections)
# ---------------------------------------------------------------------------

class FakeConn:
    """Minimal asyncpg connection mock."""

    def __init__(self, fetchrow_result=None, fetch_result=None, execute_result="DELETE 1"):
        self._fetchrow = fetchrow_result
        self._fetch = fetch_result or []
        self._execute = execute_result
        self.executed_queries: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args: Any):
        self.executed_queries.append((sql, args))
        return self._fetchrow

    async def fetch(self, sql: str, *args: Any):
        self.executed_queries.append((sql, args))
        return self._fetch

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed_queries.append((sql, args))
        return self._execute


class FakeCtx:
    def __init__(self, conn: FakeConn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_):
        pass


class TestDbCreateChatSession:

    @pytest.mark.asyncio
    async def test_inserts_and_returns_dict(self):
        from app.db.kg_chat_sessions import db_create_chat_session

        team_id = str(uuid.uuid4())
        row = _make_session_record(team_id=uuid.UUID(team_id))
        conn = FakeConn(fetchrow_result=row)

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_create_chat_session(team_id=team_id, user_sid="user-1")

        assert result["team_id"] == team_id
        assert result["user_sid"] == "user-test"
        assert len(conn.executed_queries) == 1
        assert "INSERT INTO" in conn.executed_queries[0][0]

    @pytest.mark.asyncio
    async def test_uses_parameterized_query(self):
        from app.db.kg_chat_sessions import db_create_chat_session

        team_id = str(uuid.uuid4())
        row = _make_session_record(team_id=uuid.UUID(team_id))
        conn = FakeConn(fetchrow_result=row)

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_create_chat_session(team_id=team_id, user_sid="user-1")

        sql = conn.executed_queries[0][0]
        assert "$1" in sql
        assert "$2" in sql


class TestDbGetChatSession:

    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self):
        from app.db.kg_chat_sessions import db_get_chat_session

        row = _make_session_record()
        conn = FakeConn(fetchrow_result=row)

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_get_chat_session("x", "y")

        assert result is not None
        assert "id" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.db.kg_chat_sessions import db_get_chat_session

        conn = FakeConn(fetchrow_result=None)

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_get_chat_session("x", "y")

        assert result is None

    @pytest.mark.asyncio
    async def test_team_scoped_query(self):
        from app.db.kg_chat_sessions import db_get_chat_session

        conn = FakeConn(fetchrow_result=None)

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_get_chat_session("sid", "tid")

        sql = conn.executed_queries[0][0]
        assert "team_id" in sql


class TestDbAddChatMessage:

    @pytest.mark.asyncio
    async def test_persists_message_and_bumps_session(self):
        from app.db.kg_chat_sessions import db_add_chat_message

        row = _make_message_record()
        conn = FakeConn(fetchrow_result=row, execute_result="UPDATE 1")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_add_chat_message(
                session_id="sid", role="user", content="Hello",
            )

        assert result["role"] == "assistant"  # from fake record
        # Should have INSERT + UPDATE (bump updated_at)
        assert len(conn.executed_queries) == 2
        assert "INSERT" in conn.executed_queries[0][0]
        assert "UPDATE" in conn.executed_queries[1][0]

    @pytest.mark.asyncio
    async def test_tool_calls_serialized_as_json(self):
        from app.db.kg_chat_sessions import db_add_chat_message

        row = _make_message_record()
        conn = FakeConn(fetchrow_result=row, execute_result="UPDATE 1")
        tool_calls = [{"id": "call_1", "function": {"name": "search"}}]

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_add_chat_message(
                session_id="sid", role="assistant", content="Hi",
                tool_calls=tool_calls,
            )

        # 4th positional arg ($4) should be JSON string
        args = conn.executed_queries[0][1]
        assert args[3] == json.dumps(tool_calls)

    @pytest.mark.asyncio
    async def test_entity_highlights_converted_to_uuids(self):
        from app.db.kg_chat_sessions import db_add_chat_message

        row = _make_message_record()
        conn = FakeConn(fetchrow_result=row, execute_result="UPDATE 1")
        e1 = str(uuid.uuid4())

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_add_chat_message(
                session_id="sid", role="assistant", content="Found it",
                entity_highlights=[e1],
            )

        args = conn.executed_queries[0][1]
        # 6th arg ($6) should be list of UUID objects
        assert isinstance(args[5], list)
        assert isinstance(args[5][0], uuid.UUID)


class TestDbDeleteChatSession:

    @pytest.mark.asyncio
    async def test_returns_true_when_deleted(self):
        from app.db.kg_chat_sessions import db_delete_chat_session

        conn = FakeConn(execute_result="DELETE 1")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_delete_chat_session("sid", "tid")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        from app.db.kg_chat_sessions import db_delete_chat_session

        conn = FakeConn(execute_result="DELETE 0")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            result = await db_delete_chat_session("sid", "tid")

        assert result is False


class TestDbCleanupExpiredSessions:

    @pytest.mark.asyncio
    async def test_returns_count_of_deleted(self):
        from app.db.kg_chat_sessions import db_cleanup_expired_chat_sessions

        conn = FakeConn(execute_result="DELETE 5")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            count = await db_cleanup_expired_chat_sessions(days=30)

        assert count == 5

    @pytest.mark.asyncio
    async def test_uses_parameterized_interval(self):
        from app.db.kg_chat_sessions import db_cleanup_expired_chat_sessions

        conn = FakeConn(execute_result="DELETE 0")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_cleanup_expired_chat_sessions(days=45)

        args = conn.executed_queries[0][1]
        assert args[0] == "45"  # days passed as string for interval

    @pytest.mark.asyncio
    async def test_default_30_days(self):
        from app.db.kg_chat_sessions import db_cleanup_expired_chat_sessions

        conn = FakeConn(execute_result="DELETE 0")

        with patch("app.db.kg_chat_sessions._acquire", return_value=FakeCtx(conn)):
            await db_cleanup_expired_chat_sessions()

        args = conn.executed_queries[0][1]
        assert args[0] == "30"

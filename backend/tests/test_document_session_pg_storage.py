"""Tests for PostgreSQL document session storage (m-clone-oi8e).

Unit tests run without a real database by mocking _acquire.
Integration tests require a running PostgreSQL instance and are marked with
``@pytest.mark.integration``.

Run all:    cd backend && uv run python -m pytest tests/test_document_session_pg_storage.py -v
Run unit:   cd backend && uv run python -m pytest tests/test_document_session_pg_storage.py -v -m "not integration"
Run integration: cd backend && uv run python -m pytest tests/test_document_session_pg_storage.py -v -m integration
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.redis_client import _memory_store, get_documents, set_documents, append_document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_docs(n: int = 1, text_size: int = 10) -> list[dict]:
    """Return a list of *n* minimal doc dicts with *text_size* chars of text."""
    return [
        {
            "filename": f"file{i}.pdf",
            "text": "x" * text_size,
            "type": "pdf",
            "char_count": text_size,
        }
        for i in range(n)
    ]


def _pg_mock_not_available(exc: Exception | None = None):
    """Return a context manager that raises *exc* (or RuntimeError) on PG call."""
    error = exc or RuntimeError("PG unavailable")
    async def _raise(*_a, **_kw):
        raise error
    return _raise


# ---------------------------------------------------------------------------
# Section 1: Unit tests for db/document_sessions.py
# ---------------------------------------------------------------------------

class TestPgUpsertDocumentSession:
    """Unit tests for pg_upsert_document_session (mocked asyncpg)."""

    def _make_conn(self) -> AsyncMock:
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="INSERT 0 1")
        return conn

    @asynccontextmanager
    async def _fake_acquire(self, conn):
        yield conn

    def test_upsert_calls_execute(self):
        from app.db.document_sessions import pg_upsert_document_session
        conn = self._make_conn()
        docs = _make_docs(2, text_size=100)

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire(conn)):
            asyncio.get_event_loop().run_until_complete(
                pg_upsert_document_session("abc123", docs)
            )

        conn.execute.assert_called_once()
        sql, key, payload, hours = conn.execute.call_args[0]
        assert "$1::uuid" in sql
        assert key == "abc123"
        parsed = json.loads(payload)
        assert len(parsed) == 2
        assert parsed[0]["filename"] == "file0.pdf"

    def test_upsert_uses_settings_ttl_by_default(self):
        from app.db.document_sessions import pg_upsert_document_session
        from app.config import settings
        conn = self._make_conn()

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire(conn)):
            asyncio.get_event_loop().run_until_complete(
                pg_upsert_document_session("key1", _make_docs())
            )

        _, _, _, hours = conn.execute.call_args[0]
        assert hours == str(settings.redis_ttl_hours)

    def test_upsert_respects_custom_ttl(self):
        from app.db.document_sessions import pg_upsert_document_session
        conn = self._make_conn()

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire(conn)):
            asyncio.get_event_loop().run_until_complete(
                pg_upsert_document_session("key2", _make_docs(), ttl_hours=48)
            )

        _, _, _, hours = conn.execute.call_args[0]
        assert hours == "48"


class TestPgGetDocumentSession:
    """Unit tests for pg_get_document_session."""

    @asynccontextmanager
    async def _fake_acquire_with_row(self, row):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        yield conn

    def test_returns_none_when_not_found(self):
        from app.db.document_sessions import pg_get_document_session

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_with_row(None)):
            result = asyncio.get_event_loop().run_until_complete(
                pg_get_document_session("nonexistent")
            )
        assert result is None

    def test_returns_docs_list_when_found(self):
        from app.db.document_sessions import pg_get_document_session
        docs = _make_docs(3)
        row = {"texts": json.dumps(docs)}

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_with_row(row)):
            result = asyncio.get_event_loop().run_until_complete(
                pg_get_document_session("existing-key")
            )

        assert result is not None
        assert len(result) == 3
        assert result[0]["filename"] == "file0.pdf"
        assert result[0]["text"] == "x" * 10

    def test_handles_asyncpg_decoded_jsonb(self):
        """asyncpg may return JSONB already decoded as a list (not a string)."""
        from app.db.document_sessions import pg_get_document_session
        docs = _make_docs(1)
        row = {"texts": docs}  # already a list, not a JSON string

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_with_row(row)):
            result = asyncio.get_event_loop().run_until_complete(
                pg_get_document_session("key-decoded")
            )

        assert result is not None
        assert result[0]["filename"] == "file0.pdf"


class TestPgDeleteExpiredSessions:
    """Unit tests for pg_delete_expired_sessions."""

    @asynccontextmanager
    async def _fake_acquire_delete(self, result_str: str):
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value=result_str)
        yield conn

    def test_returns_count(self):
        from app.db.document_sessions import pg_delete_expired_sessions

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_delete("DELETE 5")):
            count = asyncio.get_event_loop().run_until_complete(pg_delete_expired_sessions())

        assert count == 5

    def test_returns_zero_on_no_deletions(self):
        from app.db.document_sessions import pg_delete_expired_sessions

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_delete("DELETE 0")):
            count = asyncio.get_event_loop().run_until_complete(pg_delete_expired_sessions())

        assert count == 0

    def test_returns_zero_on_unexpected_format(self):
        from app.db.document_sessions import pg_delete_expired_sessions

        with patch("app.db.document_sessions._acquire", return_value=self._fake_acquire_delete("UNEXPECTED")):
            count = asyncio.get_event_loop().run_until_complete(pg_delete_expired_sessions())

        assert count == 0


# ---------------------------------------------------------------------------
# Section 2: Unit tests for redis_client dual-write behaviour
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_memory_store():
    _memory_store.clear()
    yield
    _memory_store.clear()


_no_redis = patch("app.redis_client._get_client", new_callable=AsyncMock, return_value=None)


class TestSetDocumentsDualWrite:
    """set_documents should write to PG even when Redis is unavailable."""

    @_no_redis
    def test_pg_write_called_on_set(self, _mock):
        docs = _make_docs(1)
        pg_upsert = AsyncMock()

        with patch("app.db.document_sessions.pg_upsert_document_session", pg_upsert):
            asyncio.get_event_loop().run_until_complete(set_documents("k-set", docs))

        pg_upsert.assert_called_once()
        call_key, call_docs, _ = pg_upsert.call_args[0]
        assert call_key == "k-set"
        assert call_docs[0]["text"] == docs[0]["text"]

    @_no_redis
    def test_pg_write_failure_does_not_raise(self, _mock):
        """A PG write error must never bubble up to the caller."""
        docs = _make_docs(1)

        with patch(
            "app.db.document_sessions.pg_upsert_document_session",
            side_effect=RuntimeError("PG down"),
        ):
            # Should NOT raise
            asyncio.get_event_loop().run_until_complete(set_documents("k-pg-fail", docs))

        # In-memory store should still be populated
        assert "k-pg-fail" in _memory_store


class TestAppendDocumentDualWrite:
    """append_document should write to PG after appending."""

    @_no_redis
    def test_pg_write_called_on_append(self, _mock):
        pg_upsert = AsyncMock()
        loop = asyncio.get_event_loop()

        with patch("app.db.document_sessions.pg_upsert_document_session", pg_upsert):
            loop.run_until_complete(
                set_documents("k-app", _make_docs(1))
            )
            pg_upsert.reset_mock()
            loop.run_until_complete(
                append_document("k-app", "b.pdf", "more text")
            )

        pg_upsert.assert_called_once()
        _, call_docs, _ = pg_upsert.call_args[0]
        # Should include both docs after append
        assert len(call_docs) == 2

    @_no_redis
    def test_append_no_session_cap_applied(self, _mock):
        """After removing SESSION_TEXT_CAP, large texts must NOT be truncated."""
        loop = asyncio.get_event_loop()
        large_text = "y" * 600_000  # 600KB — previously would have been truncated

        with patch("app.db.document_sessions.pg_upsert_document_session", AsyncMock()):
            result, truncated = loop.run_until_complete(
                append_document("k-large", "big.pdf", large_text)
            )

        assert truncated is False
        assert result[0]["char_count"] == 600_000


class TestGetDocumentsPgFallback:
    """get_documents should fall back to PG when Redis misses."""

    @_no_redis
    def test_pg_fallback_when_memory_miss(self, _mock):
        """When both Redis and memory miss, PG is queried."""
        docs = _make_docs(2, text_size=50)
        pg_get = AsyncMock(return_value=docs)

        with patch("app.db.document_sessions.pg_get_document_session", pg_get):
            session = asyncio.get_event_loop().run_until_complete(
                get_documents("pg-session-key")
            )

        assert session is not None
        assert len(session.filenames) == 2
        assert session.filenames[0] == "file0.pdf"
        assert len(session.text) > 0
        pg_get.assert_called_once_with("pg-session-key")

    @_no_redis
    def test_pg_fallback_returns_none_when_pg_also_misses(self, _mock):
        """When PG also returns None, get_documents returns None."""
        pg_get = AsyncMock(return_value=None)

        with patch("app.db.document_sessions.pg_get_document_session", pg_get):
            session = asyncio.get_event_loop().run_until_complete(
                get_documents("missing-key")
            )

        assert session is None

    @_no_redis
    def test_pg_fallback_error_returns_none(self, _mock):
        """A PG error during fallback must not raise — return None instead."""
        with patch(
            "app.db.document_sessions.pg_get_document_session",
            side_effect=RuntimeError("PG down"),
        ):
            session = asyncio.get_event_loop().run_until_complete(
                get_documents("broken-pg-key")
            )

        assert session is None

    @_no_redis
    def test_memory_hit_does_not_query_pg(self, _mock):
        """If the session is in memory, PG must NOT be queried."""
        docs = _make_docs(1)
        asyncio.get_event_loop().run_until_complete(
            set_documents("mem-key", docs, ttl_hours=1)
        )
        pg_get = AsyncMock()

        with patch("app.db.document_sessions.pg_get_document_session", pg_get):
            session = asyncio.get_event_loop().run_until_complete(
                get_documents("mem-key")
            )

        assert session is not None
        pg_get.assert_not_called()


# ---------------------------------------------------------------------------
# Section 3: Integration tests (require running PostgreSQL)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDocumentSessionIntegration:
    """Integration tests that hit a real PostgreSQL database.

    Requires DATABASE_URL to be set.  Run with:
        cd backend && uv run python -m pytest tests/test_document_session_pg_storage.py -v -m integration
    """

    async def _upsert_and_get(self, key: str, docs: list[dict]) -> list[dict] | None:
        from app.db.document_sessions import pg_upsert_document_session, pg_get_document_session
        await pg_upsert_document_session(key, docs)
        return await pg_get_document_session(key)

    async def _cleanup(self, key: str) -> None:
        from app.db._pool import _acquire
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.document_sessions WHERE session_key = $1::uuid",
                key,
            )

    def test_upsert_and_get_roundtrip(self):
        """Full round-trip: write to PG, read back, verify content."""
        loop = asyncio.get_event_loop()
        key = str(uuid.uuid4())
        docs = _make_docs(3, text_size=1000)

        try:
            result = loop.run_until_complete(self._upsert_and_get(key, docs))
            assert result is not None
            assert len(result) == 3
            assert result[0]["text"] == "x" * 1000
            assert result[1]["filename"] == "file1.pdf"
        finally:
            loop.run_until_complete(self._cleanup(key))

    def test_upsert_overwrites_existing_row(self):
        """A second upsert replaces the previous content."""
        loop = asyncio.get_event_loop()
        from app.db.document_sessions import pg_upsert_document_session, pg_get_document_session
        key = str(uuid.uuid4())
        docs_v1 = _make_docs(1, text_size=100)
        docs_v2 = _make_docs(2, text_size=200)

        try:
            loop.run_until_complete(pg_upsert_document_session(key, docs_v1))
            loop.run_until_complete(pg_upsert_document_session(key, docs_v2))
            result = loop.run_until_complete(pg_get_document_session(key))
            assert result is not None
            assert len(result) == 2
            assert result[0]["char_count"] == 200
        finally:
            loop.run_until_complete(self._cleanup(key))

    def test_expired_row_returns_none(self):
        """A row whose expires_at is in the past must not be returned."""
        loop = asyncio.get_event_loop()
        from app.db._pool import _acquire
        key = str(uuid.uuid4())
        docs = _make_docs(1)

        async def _insert_expired():
            async with _acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO playbook.document_sessions (session_key, texts, expires_at)
                    VALUES ($1::uuid, $2::jsonb, NOW() - INTERVAL '1 hour')
                    """,
                    key, json.dumps(docs),
                )

        try:
            loop.run_until_complete(_insert_expired())
            from app.db.document_sessions import pg_get_document_session
            result = loop.run_until_complete(pg_get_document_session(key))
            assert result is None
        finally:
            loop.run_until_complete(self._cleanup(key))

    def test_delete_expired_sessions(self):
        """pg_delete_expired_sessions removes expired rows and keeps fresh ones."""
        loop = asyncio.get_event_loop()
        from app.db._pool import _acquire
        from app.db.document_sessions import pg_delete_expired_sessions, pg_upsert_document_session
        expired_key = str(uuid.uuid4())
        fresh_key = str(uuid.uuid4())
        docs = _make_docs(1)

        async def _insert_expired():
            async with _acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO playbook.document_sessions (session_key, texts, expires_at)
                    VALUES ($1::uuid, $2::jsonb, NOW() - INTERVAL '1 hour')
                    """,
                    expired_key, json.dumps(docs),
                )

        try:
            loop.run_until_complete(_insert_expired())
            loop.run_until_complete(pg_upsert_document_session(fresh_key, docs, ttl_hours=24))

            deleted = loop.run_until_complete(pg_delete_expired_sessions())
            assert deleted >= 1

            from app.db.document_sessions import pg_get_document_session
            assert loop.run_until_complete(pg_get_document_session(expired_key)) is None
            assert loop.run_until_complete(pg_get_document_session(fresh_key)) is not None
        finally:
            loop.run_until_complete(self._cleanup(fresh_key))

    def test_large_document_stored_and_retrieved(self):
        """A 2MB+ document must be stored in full and retrieved without truncation."""
        loop = asyncio.get_event_loop()
        from app.db.document_sessions import pg_upsert_document_session, pg_get_document_session
        key = str(uuid.uuid4())
        large_text = "A" * 2_200_000  # ~2.1 MB of text
        docs = [{
            "filename": "large_report.pdf",
            "text": large_text,
            "type": "pdf",
            "char_count": len(large_text),
        }]

        try:
            loop.run_until_complete(pg_upsert_document_session(key, docs))
            result = loop.run_until_complete(pg_get_document_session(key))
            assert result is not None
            assert len(result) == 1
            assert result[0]["char_count"] == 2_200_000
            assert len(result[0]["text"]) == 2_200_000
        finally:
            loop.run_until_complete(self._cleanup(key))

    def test_redis_miss_falls_back_to_pg(self):
        """When Redis has no key, get_documents must fall back to PG."""
        loop = asyncio.get_event_loop()
        from app.db.document_sessions import pg_upsert_document_session
        key = str(uuid.uuid4())
        docs = _make_docs(2, text_size=500)

        try:
            # Write only to PG (skip Redis)
            loop.run_until_complete(pg_upsert_document_session(key, docs))

            # get_documents should fall back to PG since Redis won't have this key
            with patch("app.redis_client._get_client", new_callable=AsyncMock, return_value=None):
                session = loop.run_until_complete(get_documents(key))

            assert session is not None
            assert len(session.filenames) == 2
            assert len(session.text) > 0
        finally:
            loop.run_until_complete(self._cleanup(key))

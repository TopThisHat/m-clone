"""Tests for request model backward-compat validators and research endpoint wiring."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.job import AsyncResearchRequest
from app.models.request import ResearchRequest
from app.redis_client import DocumentSession


# ------------------------------------------------------------------
# ResearchRequest validator
# ------------------------------------------------------------------

class TestResearchRequestValidator:
    def test_doc_session_key_direct(self):
        req = ResearchRequest(query="q", doc_session_key="abc")
        assert req.doc_session_key == "abc"

    def test_pdf_session_key_migrated(self, caplog):
        with caplog.at_level(logging.WARNING):
            req = ResearchRequest.model_validate(
                {"query": "q", "pdf_session_key": "old-key"}
            )
        assert req.doc_session_key == "old-key"
        assert "deprecated" in caplog.text

    def test_both_keys_doc_wins(self):
        req = ResearchRequest.model_validate(
            {"query": "q", "pdf_session_key": "old", "doc_session_key": "new"}
        )
        assert req.doc_session_key == "new"

    def test_neither_key(self):
        req = ResearchRequest(query="q")
        assert req.doc_session_key is None

    def test_no_warning_when_doc_key_used(self, caplog):
        with caplog.at_level(logging.WARNING):
            ResearchRequest.model_validate({"query": "q", "doc_session_key": "k"})
        assert "deprecated" not in caplog.text

    def test_session_id_accepted(self):
        req = ResearchRequest(query="q", session_id="sess-1")
        assert req.session_id == "sess-1"

    def test_session_id_defaults_none(self):
        req = ResearchRequest(query="q")
        assert req.session_id is None


# ------------------------------------------------------------------
# AsyncResearchRequest validator
# ------------------------------------------------------------------

class TestAsyncResearchRequestValidator:
    def test_doc_session_key_direct(self):
        req = AsyncResearchRequest(query="q", webhook_url="https://example.com/hook", doc_session_key="abc")
        assert req.doc_session_key == "abc"

    def test_pdf_session_key_migrated(self, caplog):
        with caplog.at_level(logging.WARNING):
            req = AsyncResearchRequest.model_validate(
                {"query": "q", "webhook_url": "https://example.com/hook", "pdf_session_key": "old-key"}
            )
        assert req.doc_session_key == "old-key"
        assert "deprecated" in caplog.text

    def test_both_keys_doc_wins(self):
        req = AsyncResearchRequest.model_validate(
            {"query": "q", "webhook_url": "https://example.com/hook",
             "pdf_session_key": "old", "doc_session_key": "new"}
        )
        assert req.doc_session_key == "new"

    def test_neither_key(self):
        req = AsyncResearchRequest(query="q", webhook_url="https://example.com/hook")
        assert req.doc_session_key is None


# ------------------------------------------------------------------
# Research endpoint wiring: get_document_text called with doc_session_key
# ------------------------------------------------------------------

class TestResearchEndpointWiring:
    """Verify research.py calls get_document_text (not get_pdf_text) and
    unpacks DocumentSession into get_agent_deps kwargs."""

    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_streaming_endpoint_unpacks_doc_session(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc
    ):
        from app.routers.research import research_endpoint

        session = DocumentSession(
            text="doc text",
            filenames=["a.pdf", "b.csv"],
            metadata=[{"filename": "a.pdf"}, {"filename": "b.csv"}],
        )
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: test\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="test query", doc_session_key="sess-123")
        user = {"sub": "user-1"}

        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), user))

        mock_get_doc.assert_awaited_once_with("sess-123")
        mock_deps.assert_called_once()
        call_kwargs = mock_deps.call_args.kwargs
        assert call_kwargs["doc_context"] == "doc text"
        assert call_kwargs["uploaded_filenames"] == ["a.pdf", "b.csv"]
        assert call_kwargs["uploaded_doc_metadata"] == [{"filename": "a.pdf"}, {"filename": "b.csv"}]

    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_streaming_endpoint_none_session_key(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc
    ):
        from app.routers.research import research_endpoint

        session = DocumentSession(text="", filenames=[], metadata=[])
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: test\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="q")
        user = {"sub": "u1"}

        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), user))

        mock_get_doc.assert_awaited_once_with(None)
        call_kwargs = mock_deps.call_args.kwargs
        assert call_kwargs["doc_context"] == ""
        assert call_kwargs["uploaded_filenames"] == []
        assert call_kwargs["uploaded_doc_metadata"] == []


# ------------------------------------------------------------------
# Session recovery: doc_session_key recovered from PG via session_id
# ------------------------------------------------------------------

class TestSessionRecovery:
    """Verify that when doc_session_key is null but session_id is present,
    the endpoint recovers the key from PG before calling get_document_text."""

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_recovers_doc_key_from_pg(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc, mock_db_doc_key,
    ):
        """When session_id is provided and doc_session_key is null,
        the PG lookup recovers the key."""
        from app.routers.research import research_endpoint

        mock_db_doc_key.return_value = "recovered-key-123"
        session = DocumentSession(
            text="recovered text",
            filenames=["report.pdf"],
            metadata=[{"filename": "report.pdf"}],
        )
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="summarize", session_id="sess-abc")
        assert body.doc_session_key is None  # not provided

        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_awaited_once_with("sess-abc")
        mock_get_doc.assert_awaited_once_with("recovered-key-123")

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_no_doc_key_in_session_proceeds_without_documents(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc, mock_db_doc_key,
    ):
        """When the PG session has no doc_session_key, proceed without documents."""
        from app.routers.research import research_endpoint

        mock_db_doc_key.return_value = None
        session = DocumentSession(text="", filenames=[], metadata=[])
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="hello", session_id="sess-xyz")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_awaited_once_with("sess-xyz")
        # doc_key stays None since PG returned None
        mock_get_doc.assert_awaited_once_with(None)

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_no_session_id_skips_recovery(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc, mock_db_doc_key,
    ):
        """When no session_id is provided, skip PG lookup entirely."""
        from app.routers.research import research_endpoint

        session = DocumentSession(text="", filenames=[], metadata=[])
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="just a question")
        assert body.session_id is None
        assert body.doc_session_key is None

        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_not_awaited()
        mock_get_doc.assert_awaited_once_with(None)

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_doc_key_present_skips_recovery(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc, mock_db_doc_key,
    ):
        """When doc_session_key is already present, skip PG lookup even if
        session_id is also provided."""
        from app.routers.research import research_endpoint

        session = DocumentSession(
            text="direct text", filenames=["f.pdf"], metadata=[{"filename": "f.pdf"}],
        )
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(
            query="about the doc", doc_session_key="direct-key", session_id="sess-zzz",
        )
        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_not_awaited()
        mock_get_doc.assert_awaited_once_with("direct-key")

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_document_text", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_db_error_during_recovery_is_handled(
        self, _teams, _admin, mock_stream, mock_deps, mock_get_doc, mock_db_doc_key,
    ):
        """When the PG lookup raises an exception, the endpoint proceeds
        gracefully without documents (does not crash)."""
        from app.routers.research import research_endpoint

        mock_db_doc_key.side_effect = RuntimeError("DB connection lost")
        session = DocumentSession(text="", filenames=[], metadata=[])
        mock_get_doc.return_value = session
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="test", session_id="sess-err")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_awaited_once_with("sess-err")
        # Falls through with None because recovery failed gracefully
        mock_get_doc.assert_awaited_once_with(None)


# ------------------------------------------------------------------
# Task 6.8: Integration test — session_id recovery with real Redis
# ------------------------------------------------------------------

class TestSessionRecoveryIntegration:
    """Integration test for session_id recovery that exercises the real
    get_document_text → get_documents → in-memory store path.

    Unlike the unit tests in TestSessionRecovery which mock get_document_text,
    these tests let the real function run against the in-memory Redis fallback
    store to verify document content actually flows through to get_agent_deps.
    Only the PG lookup (db_get_session_doc_key) is mocked because it requires
    a live database connection.
    """

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_full_flow_session_recovery_with_real_redis_store(
        self, _teams, _admin, mock_stream, mock_deps, mock_db_doc_key,
    ):
        """End-to-end: session_id triggers PG lookup → recovered key reads real
        in-memory store → document content arrives in get_agent_deps kwargs.

        This is the integration test for Task 6.8: follow-up request with
        session_id recovers document context when doc_session_key is null.
        """
        from app.redis_client import _memory_store, set_documents
        from app.routers.research import research_endpoint

        loop = asyncio.get_event_loop()

        # 1. Seed the in-memory Redis store with real document data
        doc_key = "integration-doc-key-abc"
        _memory_store.clear()
        loop.run_until_complete(set_documents(doc_key, [
            {
                "filename": "quarterly_report.pdf",
                "text": "Revenue grew 15% in Q3 2025.",
                "type": "pdf",
                "char_count": 28,
                "pages": 5,
            },
            {
                "filename": "team_roster.csv",
                "text": "Name,Role\nAlice,Engineer\nBob,Designer",
                "type": "csv",
                "char_count": 37,
                "rows": 2,
            },
        ]))

        # 2. Configure PG mock to return the doc key
        mock_db_doc_key.return_value = doc_key

        # 3. Capture what get_agent_deps receives
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        # 4. Send request with session_id but NO doc_session_key
        body = ResearchRequest(query="What was Q3 revenue?", session_id="sess-integ-1")
        assert body.doc_session_key is None

        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        # 5. Verify PG was consulted
        mock_db_doc_key.assert_awaited_once_with("sess-integ-1")

        # 6. Verify get_agent_deps received real document content
        call_kwargs = mock_deps.call_args.kwargs
        assert "Revenue grew 15%" in call_kwargs["doc_context"]
        assert "team_roster.csv" in call_kwargs["uploaded_filenames"]
        assert "quarterly_report.pdf" in call_kwargs["uploaded_filenames"]
        assert len(call_kwargs["uploaded_doc_metadata"]) == 2

        # Verify metadata includes format-specific fields
        pdf_meta = next(
            m for m in call_kwargs["uploaded_doc_metadata"]
            if m.get("filename") == "quarterly_report.pdf"
        )
        assert pdf_meta["type"] == "pdf"
        assert pdf_meta["char_count"] == 28

        csv_meta = next(
            m for m in call_kwargs["uploaded_doc_metadata"]
            if m.get("filename") == "team_roster.csv"
        )
        assert csv_meta["type"] == "csv"
        assert csv_meta["char_count"] == 37

        # Cleanup
        _memory_store.clear()

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_recovery_with_expired_redis_key_gives_empty_context(
        self, _teams, _admin, mock_stream, mock_deps, mock_db_doc_key,
    ):
        """When PG returns a doc key but Redis no longer has the data (TTL expired),
        the endpoint proceeds with empty document context (no crash)."""
        from app.redis_client import _memory_store
        from app.routers.research import research_endpoint

        loop = asyncio.get_event_loop()

        # Ensure the in-memory store is empty (simulates expired TTL)
        _memory_store.clear()

        # PG returns a key, but the key no longer exists in Redis
        mock_db_doc_key.return_value = "expired-key-xyz"
        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(query="summarize the doc", session_id="sess-expired")
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        mock_db_doc_key.assert_awaited_once_with("sess-expired")

        # get_agent_deps should receive empty context since Redis key is gone
        call_kwargs = mock_deps.call_args.kwargs
        assert call_kwargs["doc_context"] == ""
        assert call_kwargs["uploaded_filenames"] == []
        assert call_kwargs["uploaded_doc_metadata"] == []

    @patch("app.routers.research.db_get_session_doc_key", new_callable=AsyncMock)
    @patch("app.routers.research.get_agent_deps")
    @patch("app.routers.research.stream_research")
    @patch("app.routers.research.db_is_super_admin", new_callable=AsyncMock, return_value=False)
    @patch("app.routers.research.db_list_user_teams", new_callable=AsyncMock, return_value=[])
    def test_direct_doc_key_bypasses_recovery_uses_real_store(
        self, _teams, _admin, mock_stream, mock_deps, mock_db_doc_key,
    ):
        """When doc_session_key is provided directly, PG is not consulted but
        the real in-memory store is still used to fetch document content."""
        from app.redis_client import _memory_store, set_documents
        from app.routers.research import research_endpoint

        loop = asyncio.get_event_loop()

        # Seed the store
        _memory_store.clear()
        loop.run_until_complete(set_documents("direct-key-999", [
            {
                "filename": "notes.docx",
                "text": "Meeting notes from Monday.",
                "type": "docx",
                "char_count": 26,
            },
        ]))

        mock_deps.return_value = MagicMock()

        async def fake_stream(*a, **kw):
            yield "data: ok\n\n"

        mock_stream.return_value = fake_stream()

        body = ResearchRequest(
            query="what were the meeting notes?",
            doc_session_key="direct-key-999",
            session_id="sess-both",
        )
        loop.run_until_complete(research_endpoint(body, MagicMock(), {"sub": "u1"}))

        # PG should NOT be consulted when doc_session_key is already present
        mock_db_doc_key.assert_not_awaited()

        # Verify real document content from the store
        call_kwargs = mock_deps.call_args.kwargs
        assert "Meeting notes from Monday" in call_kwargs["doc_context"]
        assert call_kwargs["uploaded_filenames"] == ["notes.docx"]
        assert len(call_kwargs["uploaded_doc_metadata"]) == 1
        assert call_kwargs["uploaded_doc_metadata"][0]["type"] == "docx"

        _memory_store.clear()

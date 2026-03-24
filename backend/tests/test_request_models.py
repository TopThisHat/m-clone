"""Tests for request model backward-compat validators and research endpoint wiring."""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


# ------------------------------------------------------------------
# AsyncResearchRequest validator
# ------------------------------------------------------------------

class TestAsyncResearchRequestValidator:
    def test_doc_session_key_direct(self):
        req = AsyncResearchRequest(query="q", webhook_url="http://x", doc_session_key="abc")
        assert req.doc_session_key == "abc"

    def test_pdf_session_key_migrated(self, caplog):
        with caplog.at_level(logging.WARNING):
            req = AsyncResearchRequest.model_validate(
                {"query": "q", "webhook_url": "http://x", "pdf_session_key": "old-key"}
            )
        assert req.doc_session_key == "old-key"
        assert "deprecated" in caplog.text

    def test_both_keys_doc_wins(self):
        req = AsyncResearchRequest.model_validate(
            {"query": "q", "webhook_url": "http://x",
             "pdf_session_key": "old", "doc_session_key": "new"}
        )
        assert req.doc_session_key == "new"

    def test_neither_key(self):
        req = AsyncResearchRequest(query="q", webhook_url="http://x")
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

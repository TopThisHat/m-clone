"""Tests for the upload endpoint refactor (Task 3).

Uses unittest.mock — no database or Redis required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.redis_client import DocumentSession
from app.routers.documents import (
    SESSION_TEXT_CAP,
    get_document_text,
    router,
)

# ---------------------------------------------------------------------------
# App fixture — standalone, no DB
# ---------------------------------------------------------------------------

_fake_user = {"sid": "test-user", "display_name": "Tester", "email": "t@t.com"}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    # Override auth dependency globally
    from app.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _fake_user
    return app


@pytest.fixture
def app():
    return _build_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PDF_BYTES = b"%PDF-fake-content"
_META_PDF = {"type": "pdf", "pages": 3}
_EXTRACTED = "Hello world from PDF"


def _upload(client, filename="test.pdf", contents=_PDF_BYTES, session_key=None):
    params = {}
    if session_key is not None:
        params["session_key"] = session_key
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, contents, "application/octet-stream")},
        params=params,
    )


# ---------------------------------------------------------------------------
# 3.1 — Supported / unsupported formats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.set_documents", new_callable=AsyncMock)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value=_EXTRACTED)
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_upload_supported_format(mock_meta, mock_extract, mock_set, client):
    resp = await _upload(client, filename="report.pdf")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "report.pdf"
    assert body["type"] == "pdf"
    assert body["char_count"] == len(_EXTRACTED)
    assert body["pages"] == 3
    mock_meta.assert_called_once()
    mock_extract.assert_called_once()
    mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_upload_unsupported_format(client):
    resp = await _upload(client, filename="readme.txt", contents=b"hi")
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 3.1 — Oversized file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.settings")
async def test_upload_oversized_file(mock_settings, client):
    mock_settings.max_upload_size_mb = 1  # 1 MB limit
    big = b"x" * (2 * 1024 * 1024)  # 2 MB
    resp = await _upload(client, filename="big.pdf", contents=big)
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# 3.2 — Extraction failure / empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.get_format_metadata", side_effect=RuntimeError("corrupt"))
async def test_upload_extraction_failure(mock_meta, client):
    resp = await _upload(client, filename="bad.pdf")
    assert resp.status_code == 422
    assert "Failed to extract" in resp.json()["detail"]


@pytest.mark.asyncio
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value="")
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_upload_empty_extraction(mock_meta, mock_extract, client):
    resp = await _upload(client, filename="empty.pdf")
    assert resp.status_code == 422
    assert "Could not extract" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 3.3 — session_key: append vs new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.set_documents", new_callable=AsyncMock)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value=_EXTRACTED)
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_upload_without_session_key(mock_meta, mock_extract, mock_set, client):
    resp = await _upload(client, filename="doc.pdf")
    assert resp.status_code == 200
    body = resp.json()
    # New session → fresh UUID key
    assert "session_key" in body
    assert body["session_key"] != ""
    mock_set.assert_called_once()


@pytest.mark.asyncio
@patch("app.routers.documents.append_document", new_callable=AsyncMock)
@patch("app.routers.documents.get_documents", new_callable=AsyncMock)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value=_EXTRACTED)
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_upload_with_session_key_append(mock_meta, mock_extract, mock_get, mock_append, client):
    existing_key = str(uuid.uuid4())
    mock_get.return_value = DocumentSession(
        text="old text",
        filenames=["old.pdf"],
        metadata=[{"filename": "old.pdf", "type": "pdf", "char_count": 8}],
    )
    mock_append.return_value = [
        {"filename": "old.pdf", "type": "pdf", "char_count": 8},
        {"filename": "new.pdf", "type": "pdf", "char_count": len(_EXTRACTED), "pages": 3},
    ]
    resp = await _upload(client, filename="new.pdf", session_key=existing_key)
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_key"] == existing_key
    assert len(body["documents"]) == 2
    mock_append.assert_called_once()


@pytest.mark.asyncio
@patch("app.routers.documents.set_documents", new_callable=AsyncMock)
@patch("app.routers.documents.get_documents", new_callable=AsyncMock, return_value=None)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value=_EXTRACTED)
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_upload_with_stale_session_key(mock_meta, mock_extract, mock_get, mock_set, client):
    stale_key = str(uuid.uuid4())
    resp = await _upload(client, filename="doc.pdf", session_key=stale_key)
    assert resp.status_code == 200
    body = resp.json()
    # Stale key → new session with new key
    assert body["session_key"] != stale_key
    mock_set.assert_called_once()


# ---------------------------------------------------------------------------
# 3.4 — Session text cap / truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.append_document", new_callable=AsyncMock)
@patch("app.routers.documents.get_documents", new_callable=AsyncMock)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock)
@patch("app.routers.documents.get_format_metadata", return_value=_META_PDF)
async def test_session_text_cap_truncation(mock_meta, mock_extract, mock_get, mock_append, client):
    existing_key = str(uuid.uuid4())
    existing_chars = SESSION_TEXT_CAP - 100  # Only 100 chars of room
    mock_get.return_value = DocumentSession(
        text="x" * existing_chars,
        filenames=["big.pdf"],
        metadata=[{"filename": "big.pdf", "type": "pdf", "char_count": existing_chars}],
    )
    new_text = "A" * 500  # 500 chars — would exceed cap
    mock_extract.return_value = new_text
    mock_append.return_value = [
        {"filename": "big.pdf", "type": "pdf", "char_count": existing_chars},
        {"filename": "extra.pdf", "type": "pdf", "char_count": 100, "pages": 3},
    ]

    resp = await _upload(client, filename="extra.pdf", session_key=existing_key)
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert body["char_count"] == 100  # truncated to 100


# ---------------------------------------------------------------------------
# 3.5 — Unified response schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.set_documents", new_callable=AsyncMock)
@patch("app.routers.documents.extract_text", new_callable=AsyncMock, return_value=_EXTRACTED)
@patch("app.routers.documents.get_format_metadata", return_value={"type": "xlsx", "sheets": 5})
async def test_unified_response_schema(mock_meta, mock_extract, mock_set, client):
    resp = await _upload(client, filename="data.xlsx")
    assert resp.status_code == 200
    body = resp.json()

    # Required fields
    for field in ("session_key", "filename", "char_count", "session_char_count",
                  "type", "truncated", "documents"):
        assert field in body, f"Missing field: {field}"

    assert body["type"] == "xlsx"
    assert body["sheets"] == 5
    assert body["truncated"] is False
    assert isinstance(body["documents"], list)
    assert len(body["documents"]) == 1


# ---------------------------------------------------------------------------
# 3.6 — Config: max_upload_size_mb syncs to max_pdf_size_mb
# ---------------------------------------------------------------------------


def test_config_max_upload_size_syncs_to_pdf():
    from app.config import Settings

    s = Settings(
        openai_api_key="k", tavily_api_key="k",
        max_upload_size_mb=30,
    )
    assert s.max_upload_size_mb == 30
    assert s.max_pdf_size_mb == 30


def test_config_max_pdf_size_defaults_to_upload():
    from app.config import Settings

    s = Settings(
        openai_api_key="k", tavily_api_key="k",
        max_pdf_size_mb=15,
    )
    # max_upload_size_mb was None → synced from max_pdf_size_mb
    assert s.max_upload_size_mb == 15
    assert s.max_pdf_size_mb == 15


# ---------------------------------------------------------------------------
# 3.7 — get_document_text returns DocumentSession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.routers.documents.get_documents", new_callable=AsyncMock, return_value=None)
async def test_get_document_text_no_session(mock_get):
    result = await get_document_text("missing-key")
    assert isinstance(result, DocumentSession)
    assert result.text == ""
    assert result.filenames == []
    assert result.metadata == []


@pytest.mark.asyncio
async def test_get_document_text_no_key():
    result = await get_document_text(None)
    assert isinstance(result, DocumentSession)
    assert result.text == ""


@pytest.mark.asyncio
@patch("app.routers.documents.get_documents", new_callable=AsyncMock)
async def test_get_document_text_with_session(mock_get):
    session = DocumentSession(
        text="hello",
        filenames=["a.pdf"],
        metadata=[{"filename": "a.pdf", "type": "pdf", "char_count": 5}],
    )
    mock_get.return_value = session
    result = await get_document_text("key-123")
    assert result is session

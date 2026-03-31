"""Integration tests for the unified POST /api/documents/upload endpoint.

Covers:
  - mode=session (default): stores text in Redis, triggers schema analysis
  - mode=kg: publishes to entity_extraction stream, returns KG receipt
  - Deprecated /upload-to-kg still works (backward compat)
  - Frontend-facing response shapes are stable
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_test_client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def _auth_override():
    return {"sub": "test-upload-user", "email": "test@test.com"}


def _csv_file(content: str = "name,revenue\nAcme,100\nBeta,200") -> tuple[str, io.BytesIO, str]:
    return ("file", io.BytesIO(content.encode()), "test.csv")


# ── mode=session tests ────────────────────────────────────────────────────────


class TestUploadSessionMode:
    """Tests for upload with mode=session (default)."""

    def test_default_mode_is_session(self):
        """Uploading without a mode param stores text in Redis and returns session_key."""
        from app.auth import get_current_user

        mock_redis_doc = MagicMock()
        mock_redis_doc.get = AsyncMock(return_value=None)
        mock_redis_doc.set = AsyncMock(return_value=True)
        mock_redis_doc.setex = AsyncMock()
        mock_redis_doc.delete = AsyncMock()
        mock_redis_doc.expire = AsyncMock()

        with (
            patch("app.routers.documents.set_documents", AsyncMock()),
            patch("app.routers.documents.get_documents", AsyncMock(return_value=None)),
            patch("app.routers.documents.analyze_schema", AsyncMock()),
        ):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "session_key" in body
        assert body["filename"] == "test.csv"
        assert body["type"] == "csv"
        assert "char_count" in body
        assert "session_char_count" in body
        assert "documents" in body

    def test_explicit_mode_session_returns_session_key(self):
        """mode=session explicitly returns the session-upload response shape."""
        from app.auth import get_current_user

        with (
            patch("app.routers.documents.set_documents", AsyncMock()),
            patch("app.routers.documents.get_documents", AsyncMock(return_value=None)),
            patch("app.routers.documents.analyze_schema", AsyncMock()),
        ):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload?mode=session",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "session_key" in body
        assert "session_id" not in body  # KG field absent

    def test_session_mode_does_not_publish_to_stream(self):
        """mode=session must NOT call publish_for_extraction."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with (
            patch("app.routers.documents.set_documents", AsyncMock()),
            patch("app.routers.documents.get_documents", AsyncMock(return_value=None)),
            patch("app.routers.documents.analyze_schema", AsyncMock()),
            patch("app.routers.documents.publish_for_extraction", mock_publish),
        ):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_publish.assert_not_called()


# ── mode=kg tests ─────────────────────────────────────────────────────────────


class TestUploadKGMode:
    """Tests for upload with mode=kg."""

    def test_kg_mode_returns_processing_receipt(self):
        """mode=kg returns session_id, status='processing', and a message."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with patch("app.routers.documents.publish_for_extraction", mock_publish):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload?mode=kg",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert body["filename"] == "test.csv"
        assert body["status"] == "processing"
        assert "message" in body
        assert "char_count" in body
        # session-mode fields must be absent
        assert "session_key" not in body
        assert "documents" not in body

    def test_kg_mode_calls_publish_for_extraction(self):
        """mode=kg publishes text to the entity_extraction stream."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with patch("app.routers.documents.publish_for_extraction", mock_publish):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload?mode=kg",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args.kwargs
        assert call_kwargs.get("is_document") is True

    def test_kg_mode_forwards_team_id(self):
        """team_id query param is forwarded to publish_for_extraction."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with patch("app.routers.documents.publish_for_extraction", mock_publish):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload?mode=kg&team_id=team-abc",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        call_kwargs = mock_publish.call_args.kwargs
        assert call_kwargs.get("team_id") == "team-abc"

    def test_kg_mode_does_not_store_in_redis(self):
        """mode=kg must NOT call set_documents."""
        from app.auth import get_current_user

        mock_set_docs = AsyncMock()

        with (
            patch("app.routers.documents.publish_for_extraction", AsyncMock()),
            patch("app.routers.documents.set_documents", mock_set_docs),
        ):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload?mode=kg",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        mock_set_docs.assert_not_called()


# ── Deprecated /upload-to-kg endpoint backward compat ─────────────────────────


class TestDeprecatedUploadToKG:
    """Tests that /upload-to-kg still works (backward compat)."""

    def test_deprecated_endpoint_returns_same_shape(self):
        """Deprecated /upload-to-kg returns the same KG receipt shape."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with patch("app.routers.documents.publish_for_extraction", mock_publish):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload-to-kg",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert body["status"] == "processing"
        assert "char_count" in body
        mock_publish.assert_called_once()

    def test_deprecated_endpoint_forwards_team_id(self):
        """Deprecated /upload-to-kg passes team_id to publish_for_extraction."""
        from app.auth import get_current_user

        mock_publish = AsyncMock()

        with patch("app.routers.documents.publish_for_extraction", mock_publish):
            app = _make_test_client()
            app.app.dependency_overrides[get_current_user] = _auth_override
            try:
                name, buf, fname = _csv_file()
                resp = app.post(
                    "/api/documents/upload-to-kg?team_id=t-xyz",
                    files={name: (fname, buf, "text/csv")},
                )
            finally:
                app.app.dependency_overrides.clear()

        assert resp.status_code == 200
        call_kwargs = mock_publish.call_args.kwargs
        assert call_kwargs.get("team_id") == "t-xyz"


# ── Invalid mode ───────────────────────────────────────────────────────────────


class TestInvalidMode:
    """Validation tests for the mode query parameter."""

    def test_unknown_mode_returns_422(self):
        """An unrecognised mode value returns HTTP 422."""
        from app.auth import get_current_user

        app = _make_test_client()
        app.app.dependency_overrides[get_current_user] = _auth_override
        try:
            name, buf, fname = _csv_file()
            resp = app.post(
                "/api/documents/upload?mode=invalid",
                files={name: (fname, buf, "text/csv")},
            )
        finally:
            app.app.dependency_overrides.clear()

        assert resp.status_code == 422

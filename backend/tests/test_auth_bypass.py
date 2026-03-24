"""Tests for auth-bypass vulnerability fixes.

These are unit tests that use FastAPI's TestClient with dependency overrides,
so they do NOT require a running database.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import create_jwt, get_current_user, get_optional_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(sid: str = "user-1", name: str = "Test User") -> str:
    return create_jwt(sid, name)


def _auth_cookie(sid: str = "user-1") -> dict[str, str]:
    return {"jwt": _make_jwt(sid)}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Fresh TestClient that patches out heavy startup side-effects."""
    with patch("app.main.init_schema", new_callable=AsyncMock):
        with patch("app.main.scheduler"):
            with patch("app.config.settings") as mock_settings:
                mock_settings.database_url = ""
                mock_settings.aws_secret_name = ""
                mock_settings.aws_mode = False
                mock_settings.allowed_origins = ["*"]
                mock_settings.jwt_secret = "test-secret-key"
                mock_settings.dev_auth_bypass = True
                mock_settings.openai_api_key = "fake"
                mock_settings.tavily_api_key = "fake"
                mock_settings.anthropic_api_key = ""
                mock_settings.default_model = "openai:gpt-4o"
                mock_settings.max_pdf_size_mb = 20

                from app.main import app
                yield TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# 1. Research endpoints — unauthenticated requests return 401
# ===========================================================================

class TestResearchAuth:
    def test_research_no_auth_returns_401(self, client):
        resp = client.post("/api/research", json={"query": "test"})
        assert resp.status_code == 401

    def test_research_async_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/research/async",
            json={"query": "test", "webhook_url": "http://example.com"},
        )
        assert resp.status_code == 401

    def test_clarify_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/research/clarify/some-id",
            json={"answer": "yes"},
        )
        assert resp.status_code == 401

    def test_job_status_no_auth_returns_401(self, client):
        resp = client.get("/api/research/jobs/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401


# ===========================================================================
# 2. Session endpoints — share/delete auth and ownership
# ===========================================================================

class TestSessionAuth:
    def test_share_no_auth_returns_401(self, client):
        resp = client.post("/api/sessions/some-id/share")
        assert resp.status_code == 401

    def test_unshare_no_auth_returns_401(self, client):
        resp = client.delete("/api/sessions/some-id/share")
        assert resp.status_code == 401

    def test_update_no_auth_returns_401(self, client):
        resp = client.patch("/api/sessions/some-id", json={"title": "new"})
        assert resp.status_code == 401

    def test_delete_no_auth_returns_401(self, client):
        resp = client.delete("/api/sessions/some-id")
        assert resp.status_code == 401

    def test_delete_non_owner_returns_403(self, client):
        """Non-owner attempting to delete a session gets 403."""
        fake_session = {
            "id": "sess-1",
            "owner_sid": "owner-user",
            "title": "Test",
            "visibility": "private",
        }
        with patch("app.routers.sessions.db_get_session", new_callable=AsyncMock, return_value=fake_session):
            resp = client.delete(
                "/api/sessions/sess-1",
                cookies=_auth_cookie("not-the-owner"),
            )
            assert resp.status_code == 403

    def test_patch_non_owner_returns_403(self, client):
        """Non-owner attempting to update a session gets 403."""
        fake_session = {
            "id": "sess-1",
            "owner_sid": "owner-user",
            "title": "Test",
            "visibility": "private",
        }
        with patch("app.routers.sessions.db_get_session", new_callable=AsyncMock, return_value=fake_session):
            resp = client.patch(
                "/api/sessions/sess-1",
                json={"title": "hijacked"},
                cookies=_auth_cookie("not-the-owner"),
            )
            assert resp.status_code == 403

    def test_share_non_owner_returns_403(self, client):
        """Non-owner attempting to share a session gets 403."""
        fake_session = {
            "id": "sess-1",
            "owner_sid": "owner-user",
            "title": "Test",
            "visibility": "private",
        }
        with patch("app.routers.sessions.db_get_session", new_callable=AsyncMock, return_value=fake_session):
            resp = client.post(
                "/api/sessions/sess-1/share",
                cookies=_auth_cookie("not-the-owner"),
            )
            assert resp.status_code == 403


# ===========================================================================
# 3. Document upload — unauthenticated returns 401
# ===========================================================================

class TestDocumentAuth:
    def test_upload_no_auth_returns_401(self, client):
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", b"fake-pdf-content", "application/pdf")},
        )
        assert resp.status_code == 401


# ===========================================================================
# 4. JWT secret validation at startup
# ===========================================================================

class TestJWTSecretValidation:
    def test_default_secret_in_prod_raises(self):
        """App startup with default jwt_secret and dev_auth_bypass=False raises."""
        with patch("app.main.settings") as mock_settings:
            mock_settings.jwt_secret = "change-me-in-prod"
            mock_settings.dev_auth_bypass = False
            mock_settings.database_url = ""
            mock_settings.aws_secret_name = ""
            mock_settings.aws_mode = False

            from app.main import startup
            with pytest.raises(RuntimeError, match="JWT_SECRET"):
                import asyncio
                asyncio.get_event_loop().run_until_complete(startup())

    def test_default_secret_with_dev_bypass_ok(self):
        """App startup with default jwt_secret but dev_auth_bypass=True is fine."""
        with patch("app.main.settings") as mock_settings:
            mock_settings.jwt_secret = "change-me-in-prod"
            mock_settings.dev_auth_bypass = True
            mock_settings.database_url = ""
            mock_settings.aws_secret_name = ""
            mock_settings.aws_mode = False

            from app.main import startup
            import asyncio
            with patch("app.main.scheduler"):
                # Should not raise
                asyncio.get_event_loop().run_until_complete(startup())

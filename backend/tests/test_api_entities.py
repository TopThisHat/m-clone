"""API-level tests for entity endpoint fixes.

Covers:
  - Library team membership checks (7pt.8)
  - Import-library body validation (7pt.10)
  - Structured import responses (7pt.7)

Uses httpx.AsyncClient with the FastAPI TestClient pattern.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers — build a minimal app with auth bypass
# ---------------------------------------------------------------------------

def _make_test_app(user_sid: str):
    """Create a FastAPI app with a patched auth dependency for testing."""
    from fastapi import FastAPI
    from app.routers.entities import router as entities_router
    from app.routers.library import router as library_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(entities_router)
    app.include_router(library_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


# ---------------------------------------------------------------------------
# 7pt.8: Library team membership checks
# ---------------------------------------------------------------------------

class TestLibraryTeamMembership:

    async def test_list_entities_forbidden_for_non_member(self, test_user_sid):
        """GET /api/library/entities?team_id=X returns 403 if not a member."""
        app = _make_test_app(test_user_sid)
        async with _acquire() as conn:
            # Create a team the user is NOT a member of
            other_sid = f"other-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
            row = await conn.fetchrow(
                "INSERT INTO playbook.teams (slug, display_name, description, created_by) VALUES ($1, $2, '', $3) RETURNING id",
                f"team-{uuid.uuid4().hex[:8]}", "Other Team", other_sid,
            )
            team_id = str(row["id"])
            await conn.execute(
                "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'owner')",
                team_id, other_sid,
            )

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/library/entities?team_id={team_id}")
                assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# 7pt.10: ImportLibraryBody.ids min_length=1
# ---------------------------------------------------------------------------

class TestImportLibraryBodyValidation:

    async def test_empty_ids_rejected(self, test_user_sid, test_campaign):
        """POST import-library with empty ids list returns 422."""
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/entities/import-library",
                json={"ids": []},
            )
            assert resp.status_code == 422

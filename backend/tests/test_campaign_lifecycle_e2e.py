"""End-to-end tests for campaign lifecycle status endpoint.

Tests full HTTP request/response via httpx.AsyncClient against the real
FastAPI router with mocked auth and a real PostgreSQL backend.

Requires a running PostgreSQL instance (docker compose up -d).
Run: cd backend && uv run python -m pytest tests/test_campaign_lifecycle_e2e.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire
from app.db.campaigns import db_create_campaign, db_transition_campaign_status
from app.models.campaign import CampaignStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_app(user_sid: str):
    """Create a minimal FastAPI app with patched auth for the campaigns router."""
    from fastapi import FastAPI
    from app.routers.campaigns import router as campaigns_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(campaigns_router)

    async def _mock_user():
        return {"sub": user_sid, "display_name": "Test User"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def e2e_user_sid():
    sid = f"e2e-lifecycle-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "E2E User", f"{sid}@test.local",
        )
    yield sid
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def e2e_campaign(e2e_user_sid):
    result = await db_create_campaign(
        owner_sid=e2e_user_sid,
        name=f"e2e-campaign-{uuid.uuid4().hex[:8]}",
        description="E2E test campaign",
        schedule=None,
    )
    campaign_id = result["id"]
    yield campaign_id
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id,
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestStatusEndpointHappyPath:

    async def test_patch_status_draft_to_active(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "active"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body["id"] == e2e_campaign

    async def test_full_lifecycle_via_endpoint(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # draft -> active
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "active"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "active"

            # active -> completed
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "completed"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "completed"

            # completed -> archived
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "archived"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# Invalid transitions return 400
# ---------------------------------------------------------------------------

class TestStatusEndpointInvalidTransitions:

    async def test_draft_to_completed_returns_400(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "completed"},
            )
        assert resp.status_code == 400
        assert "Invalid status transition" in resp.json()["detail"]

    async def test_archived_to_active_returns_400(self, e2e_user_sid, e2e_campaign):
        # Move to archived first
        await db_transition_campaign_status(e2e_campaign, CampaignStatus.active, e2e_user_sid)
        await db_transition_campaign_status(e2e_campaign, CampaignStatus.archived, e2e_user_sid)

        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "active"},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Invalid request body returns 422
# ---------------------------------------------------------------------------

class TestStatusEndpointValidation:

    async def test_invalid_status_value_returns_422(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "nonexistent"},
            )
        assert resp.status_code == 422

    async def test_missing_status_field_returns_422(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={},
            )
        assert resp.status_code == 422

    async def test_empty_body_returns_422(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                content=b"",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Campaign not found returns 404
# ---------------------------------------------------------------------------

class TestStatusEndpointNotFound:

    async def test_nonexistent_campaign_returns_404(self, e2e_user_sid):
        fake_id = "00000000-0000-0000-0000-000000000000"
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{fake_id}/status",
                json={"status": "active"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------

class TestStatusEndpointAuth:

    async def test_no_auth_returns_401(self, e2e_campaign):
        """Without auth override, the real get_current_user dependency requires a JWT cookie."""
        from fastapi import FastAPI
        from app.routers.campaigns import router as campaigns_router

        # Use the router WITHOUT dependency override
        app = FastAPI()
        app.include_router(campaigns_router)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "active"},
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Team membership check
# ---------------------------------------------------------------------------

class TestStatusEndpointTeamAccess:

    async def test_non_team_member_returns_403(self, e2e_user_sid):
        """A user who is not a team member cannot transition a team campaign."""
        # Create another user who owns a team
        other_sid = f"team-owner-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other Owner",
            )
            team_row = await conn.fetchrow(
                "INSERT INTO playbook.teams (slug, display_name, description, created_by) "
                "VALUES ($1, $2, '', $3) RETURNING id",
                f"team-{uuid.uuid4().hex[:8]}", "Test Team", other_sid,
            )
            team_id = str(team_row["id"])
            await conn.execute(
                "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'owner')",
                team_id, other_sid,
            )
            # Create a campaign owned by the team
            campaign_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid, team_id) "
                "VALUES ($1, $2, $3::uuid) RETURNING id",
                "Team Campaign", other_sid, team_id,
            )
            campaign_id = str(campaign_row["id"])

        try:
            # e2e_user_sid is NOT a member of this team
            app = _make_test_app(e2e_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/campaigns/{campaign_id}/status",
                    json={"status": "active"},
                )
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id)
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class TestStatusEndpointResponseShape:

    async def test_response_matches_campaign_out_model(self, e2e_user_sid, e2e_campaign):
        app = _make_test_app(e2e_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{e2e_campaign}/status",
                json={"status": "active"},
            )
        assert resp.status_code == 200
        body = resp.json()
        # Verify all required CampaignOut fields are present
        required_fields = {
            "id", "owner_sid", "name", "status",
            "created_at", "updated_at",
        }
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

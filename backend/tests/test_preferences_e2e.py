"""E2E tests for Preferences REST endpoints.

Tests the full HTTP request/response cycle using httpx AsyncClient
against the FastAPI application with mocked auth.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_app(user_sid: str):
    """Create a FastAPI app with a patched auth dependency for testing."""
    from fastapi import FastAPI
    from app.routers.preferences import router as preferences_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(preferences_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


@pytest_asyncio.fixture
async def cleanup_preferences(test_user_sid):
    """Clean up user_preferences rows after the test."""
    yield test_user_sid
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.user_preferences WHERE user_sid = $1",
            test_user_sid,
        )


# ---------------------------------------------------------------------------
# GET /api/preferences
# ---------------------------------------------------------------------------

class TestGetPreferencesEndpoint:

    async def test_get_empty_returns_default(self, cleanup_preferences):
        """GET with no saved preferences returns a default empty object."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"] == {}

    async def test_get_after_put(self, cleanup_preferences):
        """GET returns previously PUT preferences."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/preferences", json={
                "preferences": {"sort_order": "desc"},
            })
            resp = await client.get("/api/preferences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["sort_order"] == "desc"

    async def test_get_with_campaign_id(self, cleanup_preferences, test_campaign):
        """GET with campaign_id returns campaign-scoped preferences."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/preferences", json={
                "campaign_id": test_campaign,
                "preferences": {"view": "grid"},
            })
            resp = await client.get(
                f"/api/preferences?campaign_id={test_campaign}"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["view"] == "grid"
        assert data["campaign_id"] == test_campaign

    async def test_get_campaign_does_not_leak_global(
        self, cleanup_preferences, test_campaign
    ):
        """Campaign-scoped GET does not return global preferences."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put("/api/preferences", json={
                "preferences": {"global_key": True},
            })
            resp = await client.get(
                f"/api/preferences?campaign_id={test_campaign}"
            )
        assert resp.status_code == 200
        data = resp.json()
        # No saved campaign prefs -> default empty
        assert data["preferences"] == {}


# ---------------------------------------------------------------------------
# PUT /api/preferences
# ---------------------------------------------------------------------------

class TestUpsertPreferencesEndpoint:

    async def test_put_returns_created_prefs(self, cleanup_preferences):
        """PUT creates preferences and returns the full object."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/preferences", json={
                "preferences": {"columns": ["name", "score"]},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_sid"] == user_sid
        assert data["campaign_id"] is None
        assert data["preferences"]["columns"] == ["name", "score"]
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_put_updates_existing(self, cleanup_preferences):
        """Second PUT updates rather than creating a duplicate."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.put("/api/preferences", json={
                "preferences": {"sort": "asc"},
            })
            second = await client.put("/api/preferences", json={
                "preferences": {"sort": "desc", "view": "table"},
            })
        first_data = first.json()
        second_data = second.json()
        assert first_data["id"] == second_data["id"]
        assert second_data["preferences"]["sort"] == "desc"
        assert second_data["preferences"]["view"] == "table"

    async def test_put_with_campaign_id(self, cleanup_preferences, test_campaign):
        """PUT with campaign_id creates campaign-scoped preferences."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/preferences", json={
                "campaign_id": test_campaign,
                "preferences": {"columns": ["entity"]},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["campaign_id"] == test_campaign

    async def test_put_missing_preferences_returns_422(self, cleanup_preferences):
        """PUT without a preferences field returns 422."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/preferences", json={})
        assert resp.status_code == 422

    async def test_put_empty_preferences_is_valid(self, cleanup_preferences):
        """PUT with empty preferences dict is allowed."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/preferences", json={
                "preferences": {},
            })
        assert resp.status_code == 200
        assert resp.json()["preferences"] == {}

    async def test_put_complex_nested_preferences(self, cleanup_preferences):
        """PUT accepts complex nested JSON preferences."""
        user_sid = cleanup_preferences
        prefs = {
            "columns": {"visible": ["name", "score"], "widths": {"name": 200}},
            "filters": [{"field": "score", "op": ">=", "value": 0.5}],
            "sort": {"field": "name", "direction": "asc"},
        }
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/preferences", json={
                "preferences": prefs,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["preferences"]["columns"]["visible"] == ["name", "score"]
        assert data["preferences"]["filters"][0]["op"] == ">="


# ---------------------------------------------------------------------------
# Full Lifecycle
# ---------------------------------------------------------------------------

class TestPreferencesLifecycle:

    async def test_global_and_campaign_coexist(
        self, cleanup_preferences, test_campaign
    ):
        """Global and campaign-scoped preferences are independent."""
        user_sid = cleanup_preferences
        app = _make_test_app(user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Set global
            await client.put("/api/preferences", json={
                "preferences": {"theme": "dark"},
            })
            # Set campaign-specific
            await client.put("/api/preferences", json={
                "campaign_id": test_campaign,
                "preferences": {"view": "grid"},
            })

            # Read global
            global_resp = await client.get("/api/preferences")
            # Read campaign
            campaign_resp = await client.get(
                f"/api/preferences?campaign_id={test_campaign}"
            )

        global_data = global_resp.json()
        campaign_data = campaign_resp.json()

        assert global_data["preferences"]["theme"] == "dark"
        assert "view" not in global_data["preferences"]

        assert campaign_data["preferences"]["view"] == "grid"
        assert "theme" not in campaign_data["preferences"]

    async def test_update_does_not_affect_other_campaign(
        self, cleanup_preferences, test_campaign
    ):
        """Updating preferences for one campaign does not affect another."""
        user_sid = cleanup_preferences
        # Create a second campaign
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                f"second-{uuid.uuid4().hex[:8]}", user_sid,
            )
            second_campaign = str(row["id"])

        try:
            app = _make_test_app(user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.put("/api/preferences", json={
                    "campaign_id": test_campaign,
                    "preferences": {"sort": "asc"},
                })
                await client.put("/api/preferences", json={
                    "campaign_id": second_campaign,
                    "preferences": {"sort": "desc"},
                })

                r1 = await client.get(
                    f"/api/preferences?campaign_id={test_campaign}"
                )
                r2 = await client.get(
                    f"/api/preferences?campaign_id={second_campaign}"
                )

            assert r1.json()["preferences"]["sort"] == "asc"
            assert r2.json()["preferences"]["sort"] == "desc"
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.user_preferences WHERE campaign_id = $1::uuid",
                    second_campaign,
                )
                await conn.execute(
                    "DELETE FROM playbook.campaigns WHERE id = $1::uuid",
                    second_campaign,
                )

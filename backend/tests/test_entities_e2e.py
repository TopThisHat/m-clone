"""End-to-end tests for entity endpoints: full HTTP cycle.

Covers:
  - Metadata endpoints (GET, PUT, DELETE)
  - External ID endpoints (GET, PUT, DELETE)
  - Sorting query params on list endpoint
  - Label uniqueness (409 on duplicate)
  - Auth / ownership checks

Uses httpx.AsyncClient with FastAPI TestClient pattern.
Requires: docker compose up -d (PostgreSQL on port 5432)
Run: cd backend && uv run python -m pytest tests/test_entities_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire
from app.db.entities import db_create_entity, db_set_external_id


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_test_app(user_sid: str):
    """Create a FastAPI app with a patched auth dependency for testing."""
    from fastapi import FastAPI
    from app.routers.entities import router as entities_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(entities_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


@pytest_asyncio.fixture
async def client(test_user_sid: str) -> AsyncClient:
    """Yield an async HTTP client wired to the test app."""
    app = _make_test_app(test_user_sid)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def entity(test_campaign: str) -> dict[str, Any]:
    """Create a single entity and return it."""
    return await db_create_entity(
        campaign_id=test_campaign,
        label=f"E2E-Entity-{uuid.uuid4().hex[:6]}",
        description="E2E test entity",
        metadata={"initial": "data"},
    )


# ── List with sorting ────────────────────────────────────────────────────────

class TestListEntitiesSorting:

    async def test_sort_by_name_asc(self, client: AsyncClient, test_campaign: str):
        await db_create_entity(campaign_id=test_campaign, label="Zebra-E2E")
        await db_create_entity(campaign_id=test_campaign, label="Alpha-E2E")

        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities?sort_by=name&order=asc&limit=0",
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        labels = [i["label"] for i in items]
        assert labels == sorted(labels, key=str.lower)

    async def test_sort_by_name_desc(self, client: AsyncClient, test_campaign: str):
        await db_create_entity(campaign_id=test_campaign, label="Zebra-E2E-D")
        await db_create_entity(campaign_id=test_campaign, label="Alpha-E2E-D")

        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities?sort_by=name&order=desc&limit=0",
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        labels = [i["label"] for i in items]
        assert labels == sorted(labels, key=str.lower, reverse=True)

    async def test_invalid_sort_by_rejected(self, client: AsyncClient, test_campaign: str):
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities?sort_by=INVALID",
        )
        assert resp.status_code == 422

    async def test_invalid_order_rejected(self, client: AsyncClient, test_campaign: str):
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities?order=SIDEWAYS",
        )
        assert resp.status_code == 422


# ── Label uniqueness ────────────────────────────────────────────────────────

class TestLabelUniquenessE2E:

    async def test_create_duplicate_returns_409(self, client: AsyncClient, test_campaign: str):
        label = f"DupE2E-{uuid.uuid4().hex[:6]}"
        resp1 = await client.post(
            f"/api/campaigns/{test_campaign}/entities",
            json={"label": label},
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            f"/api/campaigns/{test_campaign}/entities",
            json={"label": label},
        )
        assert resp2.status_code == 409
        assert label in resp2.json()["detail"]

    async def test_update_to_duplicate_returns_409(self, client: AsyncClient, test_campaign: str):
        label_a = f"A-E2E-{uuid.uuid4().hex[:6]}"
        label_b = f"B-E2E-{uuid.uuid4().hex[:6]}"
        await client.post(f"/api/campaigns/{test_campaign}/entities", json={"label": label_a})
        resp_b = await client.post(f"/api/campaigns/{test_campaign}/entities", json={"label": label_b})
        entity_b_id = resp_b.json()["id"]

        resp = await client.patch(
            f"/api/campaigns/{test_campaign}/entities/{entity_b_id}",
            json={"label": label_a},
        )
        assert resp.status_code == 409


# ── Metadata endpoints ──────────────────────────────────────────────────────

class TestMetadataEndpoints:

    async def test_get_metadata(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/metadata",
        )
        assert resp.status_code == 200
        assert resp.json() == {"initial": "data"}

    async def test_put_metadata(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.put(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/metadata",
            json={"metadata": {"new_key": "new_value", "number": 42}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_key"] == "new_value"
        assert body["number"] == 42
        assert body["initial"] == "data"  # original preserved

    async def test_delete_metadata_key(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.delete(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/metadata/initial",
        )
        assert resp.status_code == 200
        assert "initial" not in resp.json()

    async def test_get_metadata_for_nonexistent_entity(self, client: AsyncClient, test_campaign: str):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{fake_id}/metadata",
        )
        assert resp.status_code == 404


# ── External ID endpoints ────────────────────────────────────────────────────

class TestExternalIdEndpoints:

    async def test_put_and_get_external_id(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.put(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/external-ids",
            json={"system": "GWM", "external_id": "GWM-E2E-001"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["system"] == "GWM"
        assert body["external_id"] == "GWM-E2E-001"

        resp2 = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/external-ids",
        )
        assert resp2.status_code == 200
        ids = resp2.json()
        assert len(ids) == 1
        assert ids[0]["system"] == "GWM"

    async def test_upsert_external_id(self, client: AsyncClient, test_campaign: str, entity: dict):
        eid = entity["id"]
        await client.put(
            f"/api/campaigns/{test_campaign}/entities/{eid}/external-ids",
            json={"system": "GWM", "external_id": "OLD-ID"},
        )
        resp = await client.put(
            f"/api/campaigns/{test_campaign}/entities/{eid}/external-ids",
            json={"system": "GWM", "external_id": "NEW-ID"},
        )
        assert resp.status_code == 200
        assert resp.json()["external_id"] == "NEW-ID"

        # Only one entry
        resp2 = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{eid}/external-ids",
        )
        assert len(resp2.json()) == 1

    async def test_delete_external_id(self, client: AsyncClient, test_campaign: str, entity: dict):
        eid = entity["id"]
        await db_set_external_id(eid, "GWM", "GWM-DEL")

        resp = await client.delete(
            f"/api/campaigns/{test_campaign}/entities/{eid}/external-ids/GWM",
        )
        assert resp.status_code == 204

        # Verify gone
        resp2 = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{eid}/external-ids",
        )
        assert len(resp2.json()) == 0

    async def test_delete_nonexistent_external_id_returns_404(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.delete(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/external-ids/NO_SUCH",
        )
        assert resp.status_code == 404

    async def test_get_external_ids_empty(self, client: AsyncClient, test_campaign: str, entity: dict):
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{entity['id']}/external-ids",
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_external_id_for_nonexistent_entity(self, client: AsyncClient, test_campaign: str):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/campaigns/{test_campaign}/entities/{fake_id}/external-ids",
        )
        assert resp.status_code == 404


# ── Auth checks ──────────────────────────────────────────────────────────────

class TestAuthChecks:

    async def test_metadata_requires_campaign_access(self, test_user_sid: str, entity: dict):
        """A user who doesn't own the campaign should get 403/404."""
        other_sid = f"other-{uuid.uuid4().hex[:6]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
        try:
            app = _make_test_app(other_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get(
                    f"/api/campaigns/{entity['campaign_id']}/entities/{entity['id']}/metadata",
                )
                # Should be 403 (not the owner)
                assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

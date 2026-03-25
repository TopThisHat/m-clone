"""E2E tests for Attribute REST endpoints.

Tests the full HTTP request/response cycle using httpx AsyncClient
against the FastAPI application with mocked auth.
"""
from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_app(user_sid: str):
    """Create a FastAPI app with a patched auth dependency for testing."""
    from fastapi import FastAPI
    from app.routers.attributes import router as attributes_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(attributes_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


# ---------------------------------------------------------------------------
# POST /{campaign_id}/attributes
# ---------------------------------------------------------------------------


class TestCreateAttributeEndpoint:

    async def test_create_minimal_returns_201(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Height"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Height"
        assert data["attribute_type"] == "text"
        assert data["category"] is None
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", data["id"])

    async def test_create_numeric_with_bounds(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={
                    "label": "Speed",
                    "attribute_type": "numeric",
                    "category": "Performance",
                    "numeric_min": 4.0,
                    "numeric_max": 6.0,
                    "weight": 2.0,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["attribute_type"] == "numeric"
        assert data["category"] == "Performance"
        assert data["numeric_min"] == 4.0
        assert data["numeric_max"] == 6.0
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", data["id"])

    async def test_create_select_with_options(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={
                    "label": "Position",
                    "attribute_type": "select",
                    "options": ["QB", "RB", "WR"],
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["attribute_type"] == "select"
        assert data["options"] == ["QB", "RB", "WR"]
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", data["id"])

    async def test_create_boolean(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Is Starter", "attribute_type": "boolean"},
            )
        assert resp.status_code == 201
        assert resp.json()["attribute_type"] == "boolean"
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", resp.json()["id"])

    async def test_create_missing_label_returns_422(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /{campaign_id}/attributes
# ---------------------------------------------------------------------------


class TestListAttributesEndpoint:

    async def test_list_returns_200(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/campaigns/{test_campaign}/attributes")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_with_category_filter(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Height", "category": "Physical"},
            )
            await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Speed", "category": "Performance"},
            )
            resp = await client.get(
                f"/api/campaigns/{test_campaign}/attributes?category=Physical",
            )
        data = resp.json()
        assert resp.status_code == 200
        assert all(item["category"] == "Physical" for item in data["items"])
        assert data["total"] == 1
        # Cleanup
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.attributes WHERE campaign_id = $1::uuid", test_campaign,
            )

    async def test_list_includes_created(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Listed Attr"},
            )
            attr_id = create_resp.json()["id"]
            list_resp = await client.get(f"/api/campaigns/{test_campaign}/attributes")
        try:
            ids = {item["id"] for item in list_resp.json()["items"]}
            assert attr_id in ids
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)


# ---------------------------------------------------------------------------
# GET /{campaign_id}/attributes/{id}
# ---------------------------------------------------------------------------


class TestGetAttributeEndpoint:

    async def test_get_existing(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Gettable", "category": "Physical"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.get(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["label"] == "Gettable"
            assert resp.json()["category"] == "Physical"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_get_nonexistent_returns_404(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/campaigns/{test_campaign}/attributes/{fake_id}",
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /{campaign_id}/attributes/{id}
# ---------------------------------------------------------------------------


class TestUpdateAttributeEndpoint:

    async def test_update_label(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Old Label"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"label": "New Label"},
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["label"] == "New Label"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_update_category(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "CatAttr"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"category": "Performance"},
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["category"] == "Performance"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_type_change_returns_400(self, test_user_sid, test_campaign):
        """Attempting to change attribute_type should return 400."""
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "TypeLocked", "attribute_type": "text"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"attribute_type": "numeric"},
            )
        try:
            assert resp.status_code == 400
            assert "type" in resp.json()["detail"].lower()
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_same_type_update_succeeds(self, test_user_sid, test_campaign):
        """Sending the same type should not be rejected."""
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "SameType", "attribute_type": "numeric"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"attribute_type": "numeric", "weight": 3.0},
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["weight"] == 3.0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_update_nonexistent_returns_404(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{fake_id}",
                json={"label": "Nope"},
            )
        assert resp.status_code == 404

    async def test_update_numeric_bounds(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "BoundsAttr", "attribute_type": "numeric"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"numeric_min": 0.0, "numeric_max": 100.0},
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["numeric_min"] == 0.0
            assert resp.json()["numeric_max"] == 100.0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)

    async def test_update_options(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "OptsAttr", "attribute_type": "select", "options": ["A"]},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"options": ["A", "B", "C"]},
            )
        try:
            assert resp.status_code == 200
            assert resp.json()["options"] == ["A", "B", "C"]
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr_id)


# ---------------------------------------------------------------------------
# DELETE /{campaign_id}/attributes/{id}
# ---------------------------------------------------------------------------


class TestDeleteAttributeEndpoint:

    async def test_delete_returns_204(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={"label": "Doomed"},
            )
            attr_id = create_resp.json()["id"]
            resp = await client.delete(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
            )
        assert resp.status_code == 204
        # Verify it is gone
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM playbook.attributes WHERE id = $1::uuid", attr_id,
            )
            assert row is None

    async def test_delete_nonexistent_returns_404(self, test_user_sid, test_campaign):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(
                f"/api/campaigns/{test_campaign}/attributes/{fake_id}",
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Full CRUD cycle
# ---------------------------------------------------------------------------


class TestFullCrudCycle:

    async def test_create_read_update_delete(self, test_user_sid, test_campaign):
        """Full lifecycle: create -> get -> update -> list -> delete."""
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create
            create_resp = await client.post(
                f"/api/campaigns/{test_campaign}/attributes",
                json={
                    "label": "Full Cycle Attr",
                    "attribute_type": "select",
                    "category": "Physical",
                    "options": ["A", "B"],
                },
            )
            assert create_resp.status_code == 201
            attr_id = create_resp.json()["id"]

            # Get
            get_resp = await client.get(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
            )
            assert get_resp.status_code == 200
            assert get_resp.json()["label"] == "Full Cycle Attr"
            assert get_resp.json()["attribute_type"] == "select"
            assert get_resp.json()["options"] == ["A", "B"]

            # Update
            update_resp = await client.patch(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
                json={"label": "Updated Cycle Attr", "category": "Performance"},
            )
            assert update_resp.status_code == 200
            assert update_resp.json()["label"] == "Updated Cycle Attr"
            assert update_resp.json()["category"] == "Performance"
            # Type unchanged
            assert update_resp.json()["attribute_type"] == "select"

            # List (filtered by category)
            list_resp = await client.get(
                f"/api/campaigns/{test_campaign}/attributes?category=Performance",
            )
            assert list_resp.status_code == 200
            ids = {item["id"] for item in list_resp.json()["items"]}
            assert attr_id in ids

            # Delete
            del_resp = await client.delete(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
            )
            assert del_resp.status_code == 204

            # Verify gone
            get_resp2 = await client.get(
                f"/api/campaigns/{test_campaign}/attributes/{attr_id}",
            )
            assert get_resp2.status_code == 404

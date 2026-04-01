"""Unit tests for KG team context scoping (m-clone-yog4).

Tests the router layer using mocked DB functions so no real DB is required.

Covers:
  - conflicts endpoint accepts team_id and validates membership
  - deal-partners endpoint accepts team_id and validates membership
  - relationships endpoint accepts team_id and validates membership
  - Cross-team relationship edit/delete requires admin role on owning team
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.routers.knowledge_graph import router as kg_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(user_sid: str) -> FastAPI:
    """FastAPI test app with mocked auth dependency."""
    app = FastAPI()
    app.include_router(kg_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test User"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


def _base_patches(team_id: str, is_member: bool = True, is_sa: bool = False):
    """Return a context manager that patches the three DB auth helpers."""
    return [
        patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=is_sa),
        patch("app.routers.knowledge_graph.db_is_team_member", new_callable=AsyncMock, return_value=is_member),
        patch("app.routers.knowledge_graph.db_list_user_teams", new_callable=AsyncMock, return_value=[{"id": team_id}]),
    ]


# ---------------------------------------------------------------------------
# Conflicts endpoint
# ---------------------------------------------------------------------------

class TestConflictsTeamIdParam:

    @pytest.mark.asyncio
    async def test_team_id_accepted_and_passed_through(self):
        """GET /api/kg/conflicts?team_id=X resolves team and calls db_list_kg_conflicts."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        mock_conflicts = AsyncMock(return_value=[])

        patches = _base_patches(team_id)
        with patches[0], patches[1], patches[2]:
            with patch("app.routers.knowledge_graph.db_list_kg_conflicts", mock_conflicts):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/conflicts?team_id={team_id}")

        assert resp.status_code == 200
        mock_conflicts.assert_called_once()
        call_kwargs = mock_conflicts.call_args.kwargs
        assert call_kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    async def test_non_member_team_id_returns_403(self):
        """GET /api/kg/conflicts?team_id=X returns 403 if user is not a team member."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
            with patch("app.routers.knowledge_graph.db_is_team_member", new_callable=AsyncMock, return_value=False):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/conflicts?team_id={team_id}")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_team_id_auto_resolves_for_member(self):
        """GET /api/kg/conflicts with no team_id auto-resolves to user's first team."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        mock_conflicts = AsyncMock(return_value=[])

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
            with patch("app.routers.knowledge_graph.db_list_user_teams", new_callable=AsyncMock, return_value=[{"id": team_id}]):
                with patch("app.routers.knowledge_graph.db_list_kg_conflicts", mock_conflicts):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        resp = await client.get("/api/kg/conflicts")

        assert resp.status_code == 200
        mock_conflicts.assert_called_once()
        call_kwargs = mock_conflicts.call_args.kwargs
        assert call_kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    async def test_no_team_no_membership_returns_403(self):
        """GET /api/kg/conflicts with no team_id and user has no teams returns 403."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        app = _make_app(user_sid)

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
            with patch("app.routers.knowledge_graph.db_list_user_teams", new_callable=AsyncMock, return_value=[]):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/kg/conflicts")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Deal-partners endpoint
# ---------------------------------------------------------------------------

class TestDealPartnersTeamIdParam:

    @pytest.mark.asyncio
    async def test_team_id_accepted_and_passed_through(self):
        """GET /api/kg/deal-partners?team_id=X resolves and calls db_get_deal_partners."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        mock_dp = AsyncMock(return_value=[])

        patches = _base_patches(team_id)
        with patches[0], patches[1], patches[2]:
            with patch("app.routers.knowledge_graph.db_get_deal_partners", mock_dp):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/deal-partners?team_id={team_id}")

        assert resp.status_code == 200
        mock_dp.assert_called_once()
        call_kwargs = mock_dp.call_args.kwargs
        assert call_kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    async def test_non_member_team_id_returns_403(self):
        """GET /api/kg/deal-partners?team_id=X returns 403 for non-members."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
            with patch("app.routers.knowledge_graph.db_is_team_member", new_callable=AsyncMock, return_value=False):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/deal-partners?team_id={team_id}")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_super_admin_can_access_any_team(self):
        """Super admin can view deal-partners for any team without membership."""
        user_sid = f"sa-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        mock_dp = AsyncMock(return_value=[])

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=True):
            with patch("app.routers.knowledge_graph.db_get_deal_partners", mock_dp):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/deal-partners?team_id={team_id}")

        assert resp.status_code == 200
        call_kwargs = mock_dp.call_args.kwargs
        assert call_kwargs["team_id"] == team_id
        # Super admin sees master too
        assert call_kwargs["include_master"] is True


# ---------------------------------------------------------------------------
# Entity relationships endpoint
# ---------------------------------------------------------------------------

class TestEntityRelationshipsTeamIdParam:

    @pytest.mark.asyncio
    async def test_team_id_accepted_and_passed_through(self):
        """GET /api/kg/entities/{id}/relationships?team_id=X passes team_id to DB."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        mock_rels = AsyncMock(return_value=[])

        patches = _base_patches(team_id)
        with patches[0], patches[1], patches[2]:
            with patch("app.routers.knowledge_graph.db_get_entity_relationships", mock_rels):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/entities/{entity_id}/relationships?team_id={team_id}")

        assert resp.status_code == 200
        mock_rels.assert_called_once()
        call_kwargs = mock_rels.call_args.kwargs
        assert call_kwargs["team_id"] == team_id

    @pytest.mark.asyncio
    async def test_non_member_team_id_returns_403(self):
        """GET /api/kg/entities/{id}/relationships?team_id=X returns 403 for non-members."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
            with patch("app.routers.knowledge_graph.db_is_team_member", new_callable=AsyncMock, return_value=False):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/kg/entities/{entity_id}/relationships?team_id={team_id}")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Cross-team relationship write auth
# ---------------------------------------------------------------------------

class TestRelationshipWriteAuth:

    @pytest.mark.asyncio
    async def test_edit_relationship_requires_team_admin(self):
        """PATCH /api/kg/relationships/{id} returns 403 if user lacks admin role."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        rel_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        fake_rel = {
            "id": rel_id,
            "team_id": team_id,
            "predicate": "works_at",
            "predicate_family": "employment",
            "subject_id": str(uuid.uuid4()),
            "object_id": str(uuid.uuid4()),
        }

        with patch("app.routers.knowledge_graph.db_get_kg_relationship", new_callable=AsyncMock, return_value=fake_rel):
            with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
                with patch("app.routers.knowledge_graph.db_get_member_role", new_callable=AsyncMock, return_value="member"):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        resp = await client.patch(
                            f"/api/kg/relationships/{rel_id}",
                            json={"predicate": "invested_in"},
                        )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_relationship_requires_team_admin(self):
        """DELETE /api/kg/relationships/{id} returns 403 if user lacks admin role."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        rel_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        fake_rel = {
            "id": rel_id,
            "team_id": team_id,
            "predicate": "works_at",
            "predicate_family": "employment",
            "subject_id": str(uuid.uuid4()),
            "object_id": str(uuid.uuid4()),
        }

        with patch("app.routers.knowledge_graph.db_get_kg_relationship", new_callable=AsyncMock, return_value=fake_rel):
            with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
                with patch("app.routers.knowledge_graph.db_get_member_role", new_callable=AsyncMock, return_value="viewer"):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        resp = await client.delete(f"/api/kg/relationships/{rel_id}")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_edit_team_relationship(self):
        """PATCH /api/kg/relationships/{id} succeeds for a team admin."""
        user_sid = f"user-{uuid.uuid4().hex[:8]}"
        rel_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        fake_rel = {
            "id": rel_id,
            "team_id": team_id,
            "predicate": "works_at",
            "predicate_family": "employment",
            "subject_id": str(uuid.uuid4()),
            "object_id": str(uuid.uuid4()),
        }
        updated_rel = {**fake_rel, "predicate": "invested_in"}

        with patch("app.routers.knowledge_graph.db_get_kg_relationship", new_callable=AsyncMock, return_value=fake_rel):
            with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=False):
                with patch("app.routers.knowledge_graph.db_get_member_role", new_callable=AsyncMock, return_value="admin"):
                    with patch("app.routers.knowledge_graph.db_update_kg_relationship", new_callable=AsyncMock, return_value=updated_rel):
                        transport = ASGITransport(app=app)
                        async with AsyncClient(transport=transport, base_url="http://test") as client:
                            resp = await client.patch(
                                f"/api/kg/relationships/{rel_id}",
                                json={"predicate": "invested_in"},
                            )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_super_admin_can_edit_any_relationship(self):
        """Super admin can edit relationships across any team."""
        user_sid = f"sa-{uuid.uuid4().hex[:8]}"
        rel_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        app = _make_app(user_sid)

        fake_rel = {
            "id": rel_id,
            "team_id": team_id,
            "predicate": "works_at",
            "predicate_family": "employment",
            "subject_id": str(uuid.uuid4()),
            "object_id": str(uuid.uuid4()),
        }
        updated_rel = {**fake_rel, "predicate": "invested_in"}

        with patch("app.routers.knowledge_graph.db_get_kg_relationship", new_callable=AsyncMock, return_value=fake_rel):
            with patch("app.routers.knowledge_graph.db_is_super_admin", new_callable=AsyncMock, return_value=True):
                with patch("app.routers.knowledge_graph.db_update_kg_relationship", new_callable=AsyncMock, return_value=updated_rel):
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        resp = await client.patch(
                            f"/api/kg/relationships/{rel_id}",
                            json={"predicate": "invested_in"},
                        )

        assert resp.status_code == 200

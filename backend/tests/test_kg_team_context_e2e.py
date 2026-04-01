"""E2E tests for KG team context scoping (m-clone-yog4).

Full-flow tests: create teams, seed entities and relationships, then exercise
the HTTP endpoints end-to-end to verify team_id filtering works correctly
across conflicts, deal-partners, and entity relationships.

Requires a running PostgreSQL (docker compose up -d).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.auth import get_current_user
from app.db._pool import _acquire
from app.db.knowledge_graph import (
    db_find_or_create_entity,
    db_list_kg_conflicts,
    db_upsert_relationship,
)
from app.routers.knowledge_graph import router as kg_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_team(conn, creator_sid: str, role: str = "admin") -> str:
    slug = f"team-{uuid.uuid4().hex[:8]}"
    row = await conn.fetchrow(
        "INSERT INTO playbook.teams (slug, display_name, description, created_by) VALUES ($1, $2, '', $3) RETURNING id",
        slug, slug, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, $3)",
        team_id, creator_sid, role,
    )
    return team_id


async def _cleanup_team(conn, team_id: str) -> None:
    await conn.execute(
        "DELETE FROM playbook.kg_relationship_conflicts WHERE new_relationship_id IN "
        "(SELECT id FROM playbook.kg_relationships WHERE team_id = $1::uuid)",
        team_id,
    )
    await conn.execute("DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


def _make_app(user_sid: str) -> FastAPI:
    app = FastAPI()
    app.include_router(kg_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test User"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


# ---------------------------------------------------------------------------
# Fixture: full E2E graph with two teams
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def e2e_teams(test_user_sid):
    """
    Full E2E setup:
      Team A (owned by test_user_sid):
        - PersonX and PersonY both invested_in DealZ (transaction)
        - PersonX works_at OrgA (employment)
      Team B (owned by stranger_sid):
        - PersonM invested_in DealN (transaction) — no deal partners
        - PersonM works_at OrgB
    """
    stranger_sid = f"stranger-{uuid.uuid4().hex[:8]}"

    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            stranger_sid, "Stranger",
        )
        team_a_id = await _make_team(conn, test_user_sid)
        team_b_id = await _make_team(conn, stranger_sid)

    # Team A entities
    person_x = await db_find_or_create_entity("PersonX", "person", [], team_id=team_a_id)
    person_y = await db_find_or_create_entity("PersonY", "person", [], team_id=team_a_id)
    org_a = await db_find_or_create_entity("OrgAlpha", "organization", [], team_id=team_a_id)
    deal_z = await db_find_or_create_entity("DealZulu", "company", [], team_id=team_a_id)

    await db_upsert_relationship(
        subject_id=person_x, predicate="invested_in", predicate_family="transaction",
        object_id=deal_z, confidence=0.9, evidence="e2e", source_session_id=None, team_id=team_a_id,
    )
    await db_upsert_relationship(
        subject_id=person_y, predicate="invested_in", predicate_family="transaction",
        object_id=deal_z, confidence=0.9, evidence="e2e", source_session_id=None, team_id=team_a_id,
    )
    await db_upsert_relationship(
        subject_id=person_x, predicate="works_at", predicate_family="employment",
        object_id=org_a, confidence=0.9, evidence="e2e", source_session_id=None, team_id=team_a_id,
    )

    # Team B entities (single investor — no deal partner pair)
    person_m = await db_find_or_create_entity("PersonM", "person", [], team_id=team_b_id)
    org_b = await db_find_or_create_entity("OrgBeta", "organization", [], team_id=team_b_id)
    deal_n = await db_find_or_create_entity("DealNovember", "company", [], team_id=team_b_id)

    await db_upsert_relationship(
        subject_id=person_m, predicate="invested_in", predicate_family="transaction",
        object_id=deal_n, confidence=0.9, evidence="e2e", source_session_id=None, team_id=team_b_id,
    )
    await db_upsert_relationship(
        subject_id=person_m, predicate="works_at", predicate_family="employment",
        object_id=org_b, confidence=0.9, evidence="e2e", source_session_id=None, team_id=team_b_id,
    )

    yield {
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "person_x_id": person_x,
        "person_y_id": person_y,
        "person_m_id": person_m,
        "org_a_id": org_a,
        "org_b_id": org_b,
        "deal_z_id": deal_z,
        "deal_n_id": deal_n,
        "user_sid": test_user_sid,
        "stranger_sid": stranger_sid,
    }

    async with _acquire() as conn:
        await _cleanup_team(conn, team_a_id)
        await _cleanup_team(conn, team_b_id)
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", stranger_sid)


# ---------------------------------------------------------------------------
# E2E: conflicts endpoint
# ---------------------------------------------------------------------------

class TestConflictsEndpointE2E:

    async def test_conflicts_endpoint_returns_200_with_team(self, e2e_teams):
        """GET /api/kg/conflicts?team_id=A returns 200 for team member."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/conflicts?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_conflicts_endpoint_blocked_for_non_member(self, e2e_teams):
        """GET /api/kg/conflicts?team_id=A returns 403 for a user not in team A."""
        app = _make_app(e2e_teams["stranger_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/conflicts?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 403

    async def test_conflicts_endpoint_auto_resolves_team(self, e2e_teams):
        """GET /api/kg/conflicts without team_id auto-resolves to user's first team."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/kg/conflicts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_db_conflicts_respects_team_filter(self, e2e_teams):
        """Direct DB call: conflicts for team A and team B are separately scoped."""
        result_a = await db_list_kg_conflicts(team_id=e2e_teams["team_a_id"])
        result_b = await db_list_kg_conflicts(team_id=e2e_teams["team_b_id"])
        # Both are lists; they don't cross-contaminate each other
        assert isinstance(result_a, list)
        assert isinstance(result_b, list)

        conflict_ids_a = {c["id"] for c in result_a}
        conflict_ids_b = {c["id"] for c in result_b}
        # No overlap between the two sets (scoping is exclusive)
        assert conflict_ids_a.isdisjoint(conflict_ids_b)


# ---------------------------------------------------------------------------
# E2E: deal-partners endpoint
# ---------------------------------------------------------------------------

class TestDealPartnersEndpointE2E:

    async def test_deal_partners_returns_200_with_team(self, e2e_teams):
        """GET /api/kg/deal-partners?team_id=A returns 200 for team A member."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/deal-partners?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 200

    async def test_deal_partners_team_a_has_pair(self, e2e_teams):
        """Team A has PersonX + PersonY both investing in DealZulu — expect 1 pair."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/deal-partners?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 200
        pairs = resp.json()
        assert len(pairs) >= 1
        all_ids = {
            p["id"]
            for pair in pairs
            for p in [pair["person1"], pair["person2"]]
        }
        assert e2e_teams["person_x_id"] in all_ids
        assert e2e_teams["person_y_id"] in all_ids

    async def test_deal_partners_team_a_excludes_team_b_persons(self, e2e_teams):
        """Team A deal-partners response does not include team B persons."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/deal-partners?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 200
        all_ids = {
            p["id"]
            for pair in resp.json()
            for p in [pair["person1"], pair["person2"]]
        }
        assert e2e_teams["person_m_id"] not in all_ids

    async def test_deal_partners_blocked_for_non_member(self, e2e_teams):
        """Stranger cannot view team A's deal-partners."""
        app = _make_app(e2e_teams["stranger_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/deal-partners?team_id={e2e_teams['team_a_id']}")
        assert resp.status_code == 403

    async def test_deal_partners_team_b_has_no_pairs(self, e2e_teams):
        """Team B has only one investor per deal — no deal-partner pairs expected."""
        app = _make_app(e2e_teams["stranger_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/kg/deal-partners?team_id={e2e_teams['team_b_id']}")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# E2E: entity relationships endpoint
# ---------------------------------------------------------------------------

class TestEntityRelationshipsEndpointE2E:

    async def test_relationships_returns_200_with_team(self, e2e_teams):
        """GET /api/kg/entities/{id}/relationships?team_id=A returns 200."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_x_id']}/relationships"
                f"?team_id={e2e_teams['team_a_id']}"
            )
        assert resp.status_code == 200
        rels = resp.json()
        assert isinstance(rels, list)
        assert len(rels) >= 1

    async def test_relationships_only_show_team_scope(self, e2e_teams):
        """All relationships returned for PersonX under team A belong to team A."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_x_id']}/relationships"
                f"?team_id={e2e_teams['team_a_id']}"
            )
        for rel in resp.json():
            assert rel["team_id"] == e2e_teams["team_a_id"]

    async def test_relationships_empty_for_wrong_team(self, e2e_teams):
        """PersonX has no relationships visible under team B's scope."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_x_id']}/relationships"
                f"?team_id={e2e_teams['team_b_id']}"
            )
        # user_sid is not a member of team_b → 403
        assert resp.status_code == 403

    async def test_relationships_non_member_blocked(self, e2e_teams):
        """Stranger cannot query PersonX's relationships under team A's scope."""
        app = _make_app(e2e_teams["stranger_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_x_id']}/relationships"
                f"?team_id={e2e_teams['team_a_id']}"
            )
        assert resp.status_code == 403

    async def test_stranger_can_see_own_team_entity(self, e2e_teams):
        """Stranger (member of team B) can view PersonM's relationships under team B."""
        app = _make_app(e2e_teams["stranger_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_m_id']}/relationships"
                f"?team_id={e2e_teams['team_b_id']}"
            )
        assert resp.status_code == 200
        rels = resp.json()
        assert len(rels) >= 1
        for rel in rels:
            assert rel["team_id"] == e2e_teams["team_b_id"]


# ---------------------------------------------------------------------------
# E2E: backward compatibility — endpoints without team_id
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    async def test_conflicts_without_team_id_works_for_member(self, e2e_teams):
        """Omitting team_id auto-resolves — must not break existing callers."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/kg/conflicts")
        assert resp.status_code == 200

    async def test_deal_partners_without_team_id_works_for_member(self, e2e_teams):
        """Omitting team_id for deal-partners auto-resolves for a team member."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/kg/deal-partners")
        assert resp.status_code == 200

    async def test_relationships_without_team_id_auto_resolves(self, e2e_teams):
        """Omitting team_id for relationships auto-resolves to user's first team."""
        app = _make_app(e2e_teams["user_sid"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/kg/entities/{e2e_teams['person_x_id']}/relationships"
            )
        assert resp.status_code == 200

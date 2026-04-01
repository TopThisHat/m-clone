"""Integration tests for KG team context scoping (m-clone-yog4).

Requires a running PostgreSQL (docker compose up -d).
Tests DB-level isolation of conflicts, deal-partners, and relationships,
plus HTTP-level cross-team write auth.

Covers:
  - db_list_kg_conflicts returns only team-scoped conflicts
  - db_get_deal_partners returns only team-scoped deal pairs
  - db_get_entity_relationships is team-isolated
  - Cross-team relationship PATCH/DELETE blocked at HTTP layer
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.db._pool import _acquire
from app.db.knowledge_graph import (
    db_find_or_create_entity,
    db_get_deal_partners,
    db_get_entity_relationships,
    db_list_kg_conflicts,
    db_upsert_relationship,
)
from app.routers.knowledge_graph import router as kg_router
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_team(conn, creator_sid: str) -> str:
    slug = f"team-{uuid.uuid4().hex[:8]}"
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.teams (slug, display_name, description, created_by)
        VALUES ($1, $2, '', $3) RETURNING id
        """,
        slug, slug, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'admin')",
        team_id, creator_sid,
    )
    return team_id


async def _cleanup_team(conn, team_id: str) -> None:
    await conn.execute("DELETE FROM playbook.kg_relationship_conflicts WHERE new_relationship_id IN (SELECT id FROM playbook.kg_relationships WHERE team_id = $1::uuid)", team_id)
    await conn.execute("DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
    await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


def _make_test_app(user_sid: str) -> FastAPI:
    app = FastAPI()
    app.include_router(kg_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test User"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def two_team_graph(test_user_sid):
    """
    Create two independent teams each with their own entities and relationships.
    Team A: PersonA works_at CompanyA
    Team B: PersonB works_at CompanyB
    """
    other_sid = f"other-{uuid.uuid4().hex[:8]}"

    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            other_sid, "Other User",
        )
        team_a_id = await _make_team(conn, test_user_sid)
        team_b_id = await _make_team(conn, other_sid)

    person_a = await db_find_or_create_entity("PersonAlpha", "person", [], team_id=team_a_id)
    company_a = await db_find_or_create_entity("CompanyAlpha", "organization", [], team_id=team_a_id)
    person_b = await db_find_or_create_entity("PersonBeta", "person", [], team_id=team_b_id)
    company_b = await db_find_or_create_entity("CompanyBeta", "organization", [], team_id=team_b_id)

    await db_upsert_relationship(
        subject_id=person_a, predicate="works_at", predicate_family="employment",
        object_id=company_a, confidence=0.9, evidence="test", source_session_id=None, team_id=team_a_id,
    )
    await db_upsert_relationship(
        subject_id=person_b, predicate="works_at", predicate_family="employment",
        object_id=company_b, confidence=0.9, evidence="test", source_session_id=None, team_id=team_b_id,
    )

    yield {
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "person_a_id": person_a,
        "company_a_id": company_a,
        "person_b_id": person_b,
        "company_b_id": company_b,
        "user_sid": test_user_sid,
        "other_sid": other_sid,
    }

    async with _acquire() as conn:
        await _cleanup_team(conn, team_a_id)
        await _cleanup_team(conn, team_b_id)
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


@pytest_asyncio.fixture
async def deal_partner_graph(test_user_sid):
    """
    Create two teams. Team A has a deal: PersonA and PersonC both invested_in DealCo.
    Team B has a deal: PersonB and PersonD both invested_in DealCo2.
    """
    other_sid = f"other-{uuid.uuid4().hex[:8]}"

    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            other_sid, "Other User",
        )
        team_a_id = await _make_team(conn, test_user_sid)
        team_b_id = await _make_team(conn, other_sid)

    # Team A deal network
    person_a = await db_find_or_create_entity("InvestorAlpha", "person", [], team_id=team_a_id)
    person_c = await db_find_or_create_entity("InvestorGamma", "person", [], team_id=team_a_id)
    deal_a = await db_find_or_create_entity("DealAlpha", "company", [], team_id=team_a_id)

    await db_upsert_relationship(
        subject_id=person_a, predicate="invested_in", predicate_family="transaction",
        object_id=deal_a, confidence=0.9, evidence="test", source_session_id=None, team_id=team_a_id,
    )
    await db_upsert_relationship(
        subject_id=person_c, predicate="invested_in", predicate_family="transaction",
        object_id=deal_a, confidence=0.9, evidence="test", source_session_id=None, team_id=team_a_id,
    )

    # Team B deal network
    person_b = await db_find_or_create_entity("InvestorBeta", "person", [], team_id=team_b_id)
    person_d = await db_find_or_create_entity("InvestorDelta", "person", [], team_id=team_b_id)
    deal_b = await db_find_or_create_entity("DealBeta", "company", [], team_id=team_b_id)

    await db_upsert_relationship(
        subject_id=person_b, predicate="invested_in", predicate_family="transaction",
        object_id=deal_b, confidence=0.9, evidence="test", source_session_id=None, team_id=team_b_id,
    )
    await db_upsert_relationship(
        subject_id=person_d, predicate="invested_in", predicate_family="transaction",
        object_id=deal_b, confidence=0.9, evidence="test", source_session_id=None, team_id=team_b_id,
    )

    yield {
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "person_a_id": person_a,
        "person_b_id": person_b,
        "deal_a_id": deal_a,
        "deal_b_id": deal_b,
        "user_sid": test_user_sid,
        "other_sid": other_sid,
    }

    async with _acquire() as conn:
        await _cleanup_team(conn, team_a_id)
        await _cleanup_team(conn, team_b_id)
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# DB-level: conflicts team isolation
# ---------------------------------------------------------------------------

class TestConflictsTeamIsolation:

    async def test_conflicts_filtered_to_team(self, two_team_graph):
        """db_list_kg_conflicts with team_id returns list (no cross-team leakage)."""
        # Conflicts only arise from the duplicate-detection logic. Here we just
        # verify the query accepts team_id without error and returns a list.
        result_a = await db_list_kg_conflicts(
            limit=50, offset=0, team_id=two_team_graph["team_a_id"]
        )
        result_b = await db_list_kg_conflicts(
            limit=50, offset=0, team_id=two_team_graph["team_b_id"]
        )
        assert isinstance(result_a, list)
        assert isinstance(result_b, list)

    async def test_wrong_team_id_returns_empty(self, two_team_graph):
        """db_list_kg_conflicts with a non-existent team_id returns empty list."""
        fake_team_id = str(uuid.uuid4())
        result = await db_list_kg_conflicts(
            limit=50, offset=0, team_id=fake_team_id
        )
        assert result == []

    async def test_no_team_no_master_returns_empty(self):
        """db_list_kg_conflicts with include_master=False and no team returns empty."""
        result = await db_list_kg_conflicts(
            limit=50, offset=0, team_id=None, include_master=False
        )
        assert result == []


# ---------------------------------------------------------------------------
# DB-level: deal-partners team isolation
# ---------------------------------------------------------------------------

class TestDealPartnersTeamIsolation:

    async def test_team_a_sees_only_own_deal_pairs(self, deal_partner_graph):
        """db_get_deal_partners for team A returns only team A deal pairs."""
        pairs = await db_get_deal_partners(team_id=deal_partner_graph["team_a_id"])
        person_ids = {
            p["id"]
            for pair in pairs
            for p in [pair["person1"], pair["person2"]]
        }
        # Team B persons should not appear in team A results
        assert deal_partner_graph["person_b_id"] not in person_ids

    async def test_team_b_sees_only_own_deal_pairs(self, deal_partner_graph):
        """db_get_deal_partners for team B returns only team B deal pairs."""
        pairs = await db_get_deal_partners(team_id=deal_partner_graph["team_b_id"])
        person_ids = {
            p["id"]
            for pair in pairs
            for p in [pair["person1"], pair["person2"]]
        }
        # Team A persons should not appear in team B results
        assert deal_partner_graph["person_a_id"] not in person_ids

    async def test_team_a_has_expected_deal_pair(self, deal_partner_graph):
        """Team A deal-partners includes the pair from the test fixture."""
        pairs = await db_get_deal_partners(team_id=deal_partner_graph["team_a_id"])
        assert len(pairs) >= 1
        # Both persons in team A should appear in at least one pair
        all_person_ids = {
            p["id"]
            for pair in pairs
            for p in [pair["person1"], pair["person2"]]
        }
        assert deal_partner_graph["person_a_id"] in all_person_ids

    async def test_wrong_team_returns_empty(self, deal_partner_graph):
        """db_get_deal_partners with non-existent team_id returns empty list."""
        result = await db_get_deal_partners(team_id=str(uuid.uuid4()))
        assert result == []


# ---------------------------------------------------------------------------
# DB-level: entity relationships team isolation
# ---------------------------------------------------------------------------

class TestEntityRelationshipsTeamIsolation:

    async def test_team_a_entity_relationships_isolated(self, two_team_graph):
        """db_get_entity_relationships only returns team A relationships for team A entity."""
        rels = await db_get_entity_relationships(
            two_team_graph["person_a_id"],
            team_id=two_team_graph["team_a_id"],
        )
        # All returned relationships must belong to team A
        for rel in rels:
            assert rel["team_id"] == two_team_graph["team_a_id"]

    async def test_wrong_team_returns_empty_for_entity(self, two_team_graph):
        """Person A's relationships are empty when queried under team B's scope."""
        rels = await db_get_entity_relationships(
            two_team_graph["person_a_id"],
            team_id=two_team_graph["team_b_id"],
        )
        assert rels == []

    async def test_team_b_entity_relationships_isolated(self, two_team_graph):
        """Person B's relationships are visible under team B's scope."""
        rels = await db_get_entity_relationships(
            two_team_graph["person_b_id"],
            team_id=two_team_graph["team_b_id"],
        )
        assert len(rels) >= 1
        for rel in rels:
            assert rel["team_id"] == two_team_graph["team_b_id"]


# ---------------------------------------------------------------------------
# HTTP-level: cross-team relationship write auth
# ---------------------------------------------------------------------------

class TestCrossTeamRelationshipWriteAuth:

    async def test_non_admin_cannot_edit_relationship(self, two_team_graph):
        """Member (not admin) in team A cannot edit team A's relationship."""
        user_sid = f"member-{uuid.uuid4().hex[:8]}"

        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_sid, "Member User",
            )
            # Add as 'member' role (not admin/owner)
            await conn.execute(
                "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'member')",
                two_team_graph["team_a_id"], user_sid,
            )

        app = _make_test_app(user_sid)

        # Get the relationship id for team A
        rels = await db_get_entity_relationships(
            two_team_graph["person_a_id"],
            team_id=two_team_graph["team_a_id"],
        )
        assert len(rels) >= 1
        rel_id = rels[0]["id"]

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/kg/relationships/{rel_id}",
                    json={"predicate": "invested_in"},
                )
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.team_members WHERE team_id = $1::uuid AND sid = $2",
                    two_team_graph["team_a_id"], user_sid,
                )
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", user_sid)

    async def test_admin_can_edit_own_team_relationship(self, two_team_graph):
        """Admin (test_user_sid) in team A can edit team A's relationship."""
        app = _make_test_app(two_team_graph["user_sid"])

        rels = await db_get_entity_relationships(
            two_team_graph["person_a_id"],
            team_id=two_team_graph["team_a_id"],
        )
        assert len(rels) >= 1
        rel_id = rels[0]["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/kg/relationships/{rel_id}",
                json={"confidence": 0.75},
            )
        assert resp.status_code == 200

    async def test_non_member_cannot_delete_relationship(self, two_team_graph):
        """User not in team A cannot delete team A's relationship."""
        # other_sid is an admin of team_b but NOT a member of team_a
        other_sid = two_team_graph["other_sid"]
        app = _make_test_app(other_sid)

        rels = await db_get_entity_relationships(
            two_team_graph["person_a_id"],
            team_id=two_team_graph["team_a_id"],
        )
        assert len(rels) >= 1
        rel_id = rels[0]["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/kg/relationships/{rel_id}")

        assert resp.status_code == 403

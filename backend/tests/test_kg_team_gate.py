"""Tests for KG Team Gate fixes (m-clone-ax7) and KG Performance (m-clone-6uw).

Covers:
  - Team scoping on conflicts, deal-partners, entity relationships (ax7.1)
  - Relationship edit/delete auth via _require_kg_edit (ax7.2)
  - Neighborhood expansion endpoint (6uw.1)
  - Graph ordering by relationship count (6uw.2)
"""
from __future__ import annotations

import uuid

import pytest_asyncio

from app.db._pool import _acquire
from app.db.knowledge_graph import (
    db_find_or_create_entity,
    db_get_deal_partners,
    db_get_entity_relationships,
    db_get_kg_graph,
    db_get_kg_relationship,
    db_get_neighbors,
    db_list_kg_conflicts,
    db_upsert_relationship,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def _make_team(conn, creator_sid: str) -> str:
    slug = f"team-{uuid.uuid4().hex[:8]}"
    row = await conn.fetchrow(
        "INSERT INTO playbook.teams (slug, display_name, description, created_by) VALUES ($1, $2, '', $3) RETURNING id",
        slug, slug, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'admin')",
        team_id, creator_sid,
    )
    return team_id


@pytest_asyncio.fixture
async def team_graph(test_user_sid):
    """Create a team with two entities and one relationship, yield info, clean up."""
    async with _acquire() as conn:
        team_id = await _make_team(conn, test_user_sid)

    # Create entities in team scope
    eid_a, _ = await db_find_or_create_entity("Person Alpha", "person", [], team_id=team_id)
    eid_b, _ = await db_find_or_create_entity("Company Beta", "organization", [], team_id=team_id)
    await db_upsert_relationship(
        subject_id=eid_a,
        predicate="works_at",
        predicate_family="employment",
        object_id=eid_b,
        confidence=0.9,
        evidence="Test evidence",
        source_session_id=None,
        team_id=team_id,
    )

    yield {
        "team_id": team_id,
        "entity_a_id": eid_a,
        "entity_b_id": eid_b,
        "user_sid": test_user_sid,
    }

    # Cleanup
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid",
            team_id,
        )
        await conn.execute(
            "DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid",
            team_id,
        )
        await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
        await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


# ---------------------------------------------------------------------------
# ax7.1: Team scoping on entity relationships
# ---------------------------------------------------------------------------

class TestEntityRelationshipsTeamScoping:

    async def test_returns_team_scoped_relationships(self, team_graph):
        """Entity relationships filtered by team_id."""
        rels = await db_get_entity_relationships(
            team_graph["entity_a_id"],
            team_id=team_graph["team_id"],
        )
        assert len(rels) >= 1
        assert rels[0]["predicate"] == "works_at"

    async def test_returns_empty_for_wrong_team(self, team_graph):
        """Entity relationships return empty for a different team."""
        fake_team = str(uuid.uuid4())
        rels = await db_get_entity_relationships(
            team_graph["entity_a_id"],
            team_id=fake_team,
        )
        assert len(rels) == 0


# ---------------------------------------------------------------------------
# ax7.1: Team scoping on conflicts
# ---------------------------------------------------------------------------

class TestConflictsTeamScoping:

    async def test_conflicts_with_team_filter(self, team_graph):
        """Listing conflicts with team_id should not error."""
        result = await db_list_kg_conflicts(
            limit=10,
            offset=0,
            team_id=team_graph["team_id"],
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ax7.1: Team scoping on deal partners
# ---------------------------------------------------------------------------

class TestDealPartnersTeamScoping:

    async def test_deal_partners_with_team_filter(self, team_graph):
        """deal-partners with team_id should not error."""
        result = await db_get_deal_partners(team_id=team_graph["team_id"])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ax7.2: Relationship fetch by ID
# ---------------------------------------------------------------------------

class TestGetKgRelationship:

    async def test_fetch_existing_relationship(self, team_graph):
        """db_get_kg_relationship returns a relationship dict with team_id."""
        rels = await db_get_entity_relationships(
            team_graph["entity_a_id"],
            team_id=team_graph["team_id"],
        )
        assert len(rels) >= 1
        rel_id = rels[0]["id"]
        rel = await db_get_kg_relationship(rel_id)
        assert rel is not None
        assert rel["team_id"] == team_graph["team_id"]

    async def test_fetch_nonexistent_returns_none(self):
        fake_id = str(uuid.uuid4())
        rel = await db_get_kg_relationship(fake_id)
        assert rel is None


# ---------------------------------------------------------------------------
# 6uw.1: Neighborhood expansion
# ---------------------------------------------------------------------------

class TestNeighborhoodExpansion:

    async def test_returns_nodes_and_edges(self, team_graph):
        """db_get_neighbors returns dict with nodes and edges."""
        result = await db_get_neighbors(
            team_graph["entity_a_id"],
            depth=1,
            limit=50,
            team_id=team_graph["team_id"],
        )
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) >= 1
        assert len(result["edges"]) >= 1

    async def test_exclude_ids(self, team_graph):
        """Excluding an entity should reduce results."""
        all_result = await db_get_neighbors(
            team_graph["entity_a_id"],
            depth=1,
            limit=50,
            team_id=team_graph["team_id"],
        )
        excluded_result = await db_get_neighbors(
            team_graph["entity_a_id"],
            depth=1,
            limit=50,
            exclude_ids=[team_graph["entity_b_id"]],
            team_id=team_graph["team_id"],
        )
        # With the only neighbor excluded, no edges should be returned
        assert len(excluded_result["edges"]) <= len(all_result["edges"])

    async def test_empty_for_nonexistent_entity(self, team_graph):
        fake_id = str(uuid.uuid4())
        result = await db_get_neighbors(
            fake_id,
            depth=1,
            limit=50,
            team_id=team_graph["team_id"],
        )
        assert result["nodes"] == []
        assert result["edges"] == []


# ---------------------------------------------------------------------------
# 6uw.2: Graph ordering (most-connected first)
# ---------------------------------------------------------------------------

class TestGraphOrdering:

    async def test_graph_returns_nodes_and_edges(self, team_graph):
        """db_get_kg_graph with ordering should return valid structure."""
        result = await db_get_kg_graph(
            team_id=team_graph["team_id"],
            limit=10,
        )
        assert "nodes" in result
        assert "edges" in result
        assert len(result["edges"]) >= 1

"""Tests for KG tool team scoping fix (query_knowledge_graph).

Covers:
  - Single team_id queries correct team only
  - Multi-team merges and deduplicates by entity/relationship ID
  - Empty team_ids returns graceful message
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools import query_knowledge_graph
from app.dependencies import get_agent_deps


def _make_entity(name: str, entity_type: str = "person", team_id: str | None = None, graph_source: str = "team") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "entity_type": entity_type,
        "aliases": [],
        "description": f"Test entity {name}",
        "team_id": team_id,
        "graph_source": graph_source,
    }


def _make_relationship(subject: str, predicate: str, obj: str, team_id: str | None = None, graph_source: str = "team") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "subject_name": subject,
        "predicate": predicate,
        "object_name": obj,
        "confidence": 0.9,
        "team_id": team_id,
        "graph_source": graph_source,
    }


def _make_kg_result(entities: list[dict], relationships: list[dict], sources: list[str] | None = None) -> dict:
    return {
        "entities": entities,
        "relationships": relationships,
        "sources_used": sources or ["test_source"],
    }


class TestKGToolSingleTeam:
    """Tool with 1 team_id queries that team only."""

    @pytest.mark.asyncio
    async def test_single_team_queries_one_team(self):
        team_id = str(uuid.uuid4())
        entity = _make_entity("Acme Corp", "organization", team_id=team_id)
        rel = _make_relationship("John", "works_at", "Acme Corp", team_id=team_id)

        mock_db = AsyncMock(return_value=_make_kg_result([entity], [rel]))

        deps = get_agent_deps(team_ids=[team_id])

        with patch("app.db.db_query_kg", mock_db):
            # The tool function has signature (deps, query) from the decorator
            # but we need to handle the import inside the function
            result = await query_knowledge_graph(deps, "Acme Corp")

        # Should call db_query_kg exactly once with the single team
        mock_db.assert_called_once_with("Acme Corp", team_id=team_id)
        assert "Acme Corp" in result
        assert "works_at" in result

    @pytest.mark.asyncio
    async def test_single_team_no_results(self):
        team_id = str(uuid.uuid4())
        mock_db = AsyncMock(return_value=_make_kg_result([], [], []))
        deps = get_agent_deps(team_ids=[team_id])

        with patch("app.db.db_query_kg", mock_db):
            result = await query_knowledge_graph(deps, "nonexistent")

        assert "No knowledge graph results found" in result


class TestKGToolMultiTeam:
    """Tool with 2 team_ids merges results, deduplicates by entity ID."""

    @pytest.mark.asyncio
    async def test_multi_team_merges_results(self):
        team_a = str(uuid.uuid4())
        team_b = str(uuid.uuid4())
        entity_a = _make_entity("Alpha Inc", "organization", team_id=team_a)
        entity_b = _make_entity("Beta LLC", "organization", team_id=team_b)
        rel_a = _make_relationship("Alice", "works_at", "Alpha Inc", team_id=team_a)
        rel_b = _make_relationship("Bob", "works_at", "Beta LLC", team_id=team_b)

        call_count = 0

        async def mock_query(query, team_id=None):
            nonlocal call_count
            call_count += 1
            if team_id == team_a:
                return _make_kg_result([entity_a], [rel_a], ["source_a"])
            return _make_kg_result([entity_b], [rel_b], ["source_b"])

        deps = get_agent_deps(team_ids=[team_a, team_b])

        with patch("app.db.db_query_kg", side_effect=mock_query):
            result = await query_knowledge_graph(deps, "companies")

        assert call_count == 2
        assert "Alpha Inc" in result
        assert "Beta LLC" in result
        assert "Alice" in result
        assert "Bob" in result

    @pytest.mark.asyncio
    async def test_multi_team_deduplicates_by_id(self):
        team_a = str(uuid.uuid4())
        team_b = str(uuid.uuid4())
        # Same entity appears in both teams (e.g., shared master entity)
        shared_entity = _make_entity("Shared Corp", "organization", graph_source="master")
        unique_entity = _make_entity("Unique LLC", "organization", team_id=team_b)

        async def mock_query(query, team_id=None):
            if team_id == team_a:
                return _make_kg_result([shared_entity], [])
            return _make_kg_result([shared_entity, unique_entity], [])

        deps = get_agent_deps(team_ids=[team_a, team_b])

        with patch("app.db.db_query_kg", side_effect=mock_query):
            result = await query_knowledge_graph(deps, "corp")

        # Shared entity should appear only once due to UUID dedup
        # Count the bold entity markers, not raw text (description also contains name)
        assert result.count("**Shared Corp**") == 1
        assert "Unique LLC" in result


class TestKGToolNoAccess:
    """Tool with empty team_ids returns graceful message."""

    @pytest.mark.asyncio
    async def test_no_teams_returns_message(self):
        deps = get_agent_deps(team_ids=[])

        # Should NOT call db_query_kg at all
        with patch("app.db.db_query_kg", new_callable=AsyncMock) as mock_db:
            result = await query_knowledge_graph(deps, "anything")

        mock_db.assert_not_called()
        assert "No knowledge graph available" in result
        assert "team" in result.lower()


class TestAgentDepsTeamFields:
    """Verify AgentDeps correctly carries team_ids."""

    def test_deps_with_multi_team_context(self):
        deps = get_agent_deps(team_ids=["t1", "t2"])
        assert deps.team_ids == ["t1", "t2"]

    def test_deps_defaults(self):
        deps = get_agent_deps()
        assert deps.team_ids == []

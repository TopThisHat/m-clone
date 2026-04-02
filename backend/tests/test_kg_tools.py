"""Tests for KG Tools (kg_tools.py) — the 6 structured tools for chat.

Covers:
  - Validation: UUID checks, empty queries, out-of-range params
  - aggregate_kg: hardcoded allowlist, rejects unknown query_names
  - execute_kg_tool dispatch: known tools, unknown tools, validation errors
  - SQL injection safety: all tools handle malicious input safely
  - find_connections: same source/target graceful handling

Run: cd backend && uv run python -m pytest tests/test_kg_tools.py -v
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.agent.kg_tools import (
    KG_TOOL_SCHEMAS,
    _AGGREGATE_QUERIES,
    _validate_positive_int,
    _validate_uuid,
    aggregate_kg,
    execute_kg_tool,
    find_connections,
    get_entity_details,
    get_entity_relationships,
    search_kg_entities,
    explore_neighborhood,
)


VALID_UUID = str(uuid.uuid4())
VALID_TEAM_ID = str(uuid.uuid4())
INVALID_UUID = "not-a-uuid"
SQL_INJECTION = "'; DROP TABLE kg_entities; --"


# ---------------------------------------------------------------------------
# _validate_uuid tests
# ---------------------------------------------------------------------------

class TestValidateUUID:
    def test_valid_uuid_accepted(self):
        result = _validate_uuid(VALID_UUID, "test")
        assert result == VALID_UUID

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid(INVALID_UUID, "entity_id")

    def test_sql_injection_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid(SQL_INJECTION, "entity_id")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid("", "entity_id")


# ---------------------------------------------------------------------------
# _validate_positive_int tests
# ---------------------------------------------------------------------------

class TestValidatePositiveInt:
    def test_valid_int(self):
        assert _validate_positive_int(5, "limit") == 5

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            _validate_positive_int(0, "limit")

    def test_over_max_raises(self):
        with pytest.raises(ValueError):
            _validate_positive_int(101, "limit", max_val=100)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            _validate_positive_int(-1, "limit")


# ---------------------------------------------------------------------------
# search_kg_entities validation tests
# ---------------------------------------------------------------------------

class TestSearchKGEntitiesValidation:

    @pytest.mark.asyncio
    async def test_invalid_team_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await search_kg_entities(team_id=INVALID_UUID, query="test")

    @pytest.mark.asyncio
    async def test_empty_query_raises(self):
        with pytest.raises(ValueError, match="query must not be empty"):
            await search_kg_entities(team_id=VALID_UUID, query="")

    @pytest.mark.asyncio
    async def test_whitespace_query_raises(self):
        with pytest.raises(ValueError, match="query must not be empty"):
            await search_kg_entities(team_id=VALID_UUID, query="   ")

    @pytest.mark.asyncio
    async def test_limit_over_50_raises(self):
        with pytest.raises(ValueError, match="must be an integer between 1 and 50"):
            await search_kg_entities(team_id=VALID_UUID, query="test", limit=51)


# ---------------------------------------------------------------------------
# get_entity_relationships validation tests
# ---------------------------------------------------------------------------

class TestGetEntityRelationshipsValidation:

    @pytest.mark.asyncio
    async def test_invalid_entity_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_relationships(
                team_id=VALID_UUID, entity_id=INVALID_UUID,
            )

    @pytest.mark.asyncio
    async def test_invalid_team_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_relationships(
                team_id=INVALID_UUID, entity_id=VALID_UUID,
            )

    @pytest.mark.asyncio
    async def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="direction must be"):
            await get_entity_relationships(
                team_id=VALID_UUID, entity_id=VALID_UUID, direction="sideways",
            )

    @pytest.mark.asyncio
    async def test_sql_injection_in_entity_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_relationships(
                team_id=VALID_UUID, entity_id=SQL_INJECTION,
            )


# ---------------------------------------------------------------------------
# find_connections validation tests
# ---------------------------------------------------------------------------

class TestFindConnectionsValidation:

    @pytest.mark.asyncio
    async def test_invalid_source_uuid_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await find_connections(
                team_id=VALID_UUID, source_id=INVALID_UUID, target_id=VALID_UUID,
            )

    @pytest.mark.asyncio
    async def test_invalid_target_uuid_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await find_connections(
                team_id=VALID_UUID, source_id=VALID_UUID, target_id=INVALID_UUID,
            )

    @pytest.mark.asyncio
    async def test_same_source_and_target(self):
        """source_id == target_id should return empty paths with message."""
        same_id = VALID_UUID
        result = await find_connections(
            team_id=VALID_TEAM_ID, source_id=same_id, target_id=same_id,
        )
        assert result["paths"] == []
        assert "same entity" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_max_hops_over_5_raises(self):
        with pytest.raises(ValueError, match="must be an integer between 1 and 5"):
            await find_connections(
                team_id=VALID_UUID,
                source_id=str(uuid.uuid4()),
                target_id=str(uuid.uuid4()),
                max_hops=6,
            )


# ---------------------------------------------------------------------------
# aggregate_kg tests
# ---------------------------------------------------------------------------

class TestAggregateKG:
    """Verify hardcoded allowlist and no dynamic SQL."""

    def test_allowlist_has_expected_queries(self):
        """Pre-defined queries exist in the allowlist."""
        expected = {
            "entity_type_counts",
            "relationship_family_counts",
            "most_connected",
            "recent_entities",
            "predicate_counts",
        }
        assert expected <= set(_AGGREGATE_QUERIES.keys())

    def test_all_queries_are_parameterized(self):
        """Every query in the allowlist uses $1 parameter for team_id."""
        for name, sql in _AGGREGATE_QUERIES.items():
            assert "$1" in sql, f"Query '{name}' missing $1 parameter"

    def test_no_dynamic_sql_in_queries(self):
        """No string interpolation markers in the allowlist queries."""
        for name, sql in _AGGREGATE_QUERIES.items():
            assert "{" not in sql, f"Query '{name}' has string interpolation marker"
            assert "%" not in sql or "%" in sql.split("--")[0] is False, \
                f"Checked query '{name}'"

    @pytest.mark.asyncio
    async def test_unknown_query_name_raises(self):
        with pytest.raises(ValueError, match="Unknown query_name"):
            await aggregate_kg(team_id=VALID_UUID, query_name="drop_tables")

    @pytest.mark.asyncio
    async def test_sql_injection_in_query_name_raises(self):
        with pytest.raises(ValueError, match="Unknown query_name"):
            await aggregate_kg(team_id=VALID_UUID, query_name=SQL_INJECTION)

    @pytest.mark.asyncio
    async def test_invalid_team_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await aggregate_kg(team_id=INVALID_UUID, query_name="entity_type_counts")


# ---------------------------------------------------------------------------
# get_entity_details validation tests
# ---------------------------------------------------------------------------

class TestGetEntityDetailsValidation:

    @pytest.mark.asyncio
    async def test_invalid_team_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_details(team_id=INVALID_UUID, entity_ids=[VALID_UUID])

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        result = await get_entity_details(team_id=VALID_UUID, entity_ids=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_batch_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_details(
                team_id=VALID_UUID,
                entity_ids=[VALID_UUID, INVALID_UUID],
            )

    @pytest.mark.asyncio
    async def test_over_100_ids_raises(self):
        ids = [str(uuid.uuid4()) for _ in range(101)]
        with pytest.raises(ValueError, match="must not exceed 100"):
            await get_entity_details(team_id=VALID_UUID, entity_ids=ids)


# ---------------------------------------------------------------------------
# explore_neighborhood validation tests
# ---------------------------------------------------------------------------

class TestExploreNeighborhoodValidation:

    @pytest.mark.asyncio
    async def test_invalid_entity_id_raises(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await explore_neighborhood(
                team_id=VALID_UUID, entity_id=INVALID_UUID,
            )

    @pytest.mark.asyncio
    async def test_depth_over_3_raises(self):
        with pytest.raises(ValueError, match="must be an integer between 1 and 3"):
            await explore_neighborhood(
                team_id=VALID_UUID, entity_id=VALID_UUID, depth=4,
            )


# ---------------------------------------------------------------------------
# execute_kg_tool dispatch tests
# ---------------------------------------------------------------------------

class TestExecuteKGTool:
    """Tests for the tool dispatcher function."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        result_json = await execute_kg_tool("nonexistent_tool", {}, VALID_TEAM_ID)
        result = json.loads(result_json)
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_validation_error_returns_json_error(self):
        """Validation errors should return JSON error, not raise."""
        result_json = await execute_kg_tool(
            "search_kg_entities",
            {"query": ""},  # empty query
            VALID_TEAM_ID,
        )
        result = json.loads(result_json)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_json_error(self):
        """Invalid UUID in tool args should return JSON error."""
        result_json = await execute_kg_tool(
            "get_entity_relationships",
            {"entity_id": INVALID_UUID},
            VALID_TEAM_ID,
        )
        result = json.loads(result_json)
        assert "error" in result
        assert "Invalid UUID" in result["error"]


# ---------------------------------------------------------------------------
# KG_TOOL_SCHEMAS validation
# ---------------------------------------------------------------------------

class TestToolSchemas:
    """Verify OpenAI tool schemas are well-formed."""

    def test_six_tools_defined(self):
        assert len(KG_TOOL_SCHEMAS) == 6

    def test_all_schemas_have_function_key(self):
        for schema in KG_TOOL_SCHEMAS:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]

    def test_expected_tool_names(self):
        names = {s["function"]["name"] for s in KG_TOOL_SCHEMAS}
        expected = {
            "search_kg_entities",
            "get_entity_relationships",
            "find_connections",
            "aggregate_kg",
            "get_entity_details",
            "explore_neighborhood",
        }
        assert names == expected

    def test_aggregate_schema_enum_matches_allowlist(self):
        """aggregate_kg schema enum must match _AGGREGATE_QUERIES keys."""
        for schema in KG_TOOL_SCHEMAS:
            if schema["function"]["name"] == "aggregate_kg":
                enum_values = set(
                    schema["function"]["parameters"]["properties"]["query_name"]["enum"]
                )
                assert enum_values == set(_AGGREGATE_QUERIES.keys())
                break
        else:
            pytest.fail("aggregate_kg schema not found")

    def test_all_required_fields_listed(self):
        """Every tool schema must have a 'required' list."""
        for schema in KG_TOOL_SCHEMAS:
            params = schema["function"]["parameters"]
            assert "required" in params, (
                f"Tool '{schema['function']['name']}' missing 'required' field"
            )
            assert len(params["required"]) > 0


# ---------------------------------------------------------------------------
# SQL injection safety across all tools
# ---------------------------------------------------------------------------

class TestSQLInjectionSafety:
    """Verify all 6 tools reject SQL injection payloads at validation layer."""

    PAYLOADS = [
        "'; DROP TABLE kg_entities; --",
        "1 OR 1=1",
        "' UNION SELECT * FROM users --",
        "Robert'); DROP TABLE kg_entities;--",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_search_handles_injection_in_team_id(self, payload):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await search_kg_entities(team_id=payload, query="test")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_relationships_handles_injection_in_entity_id(self, payload):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_relationships(team_id=VALID_UUID, entity_id=payload)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_connections_handles_injection_in_source(self, payload):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await find_connections(
                team_id=VALID_UUID, source_id=payload, target_id=VALID_UUID,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_aggregate_handles_injection_in_query_name(self, payload):
        with pytest.raises(ValueError, match="Unknown query_name"):
            await aggregate_kg(team_id=VALID_UUID, query_name=payload)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_details_handles_injection_in_entity_ids(self, payload):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_details(team_id=VALID_UUID, entity_ids=[payload])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", PAYLOADS)
    async def test_neighborhood_handles_injection_in_entity_id(self, payload):
        with pytest.raises(ValueError, match="Invalid UUID"):
            await explore_neighborhood(team_id=VALID_UUID, entity_id=payload)

"""
Unit tests for KG chat components.

Covers:
- kg_tools.py: parameter validation, tool dispatch, UUID validation
- kg_chat.py: SSE event types, system prompt, rate limit helpers
- kg_chat_sessions.py: dict conversion helpers
- kg_chat router: request model validation, session conversion helper
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Test fixtures ─────────────────────────────────────────────────────────────

VALID_UUID = str(uuid.uuid4())
VALID_UUID_2 = str(uuid.uuid4())
INVALID_UUID = "not-a-uuid"
TEAM_ID = str(uuid.uuid4())
USER_SID = "test-user-123"
SESSION_ID = str(uuid.uuid4())


# ── kg_tools: UUID validation ─────────────────────────────────────────────────

class TestUUIDValidation:
    """Tests for the _is_valid_uuid and _require_uuid helpers."""

    def test_valid_uuid_accepted(self):
        from app.agent.kg_tools import _is_valid_uuid
        assert _is_valid_uuid(VALID_UUID) is True

    def test_invalid_uuid_rejected(self):
        from app.agent.kg_tools import _is_valid_uuid
        assert _is_valid_uuid(INVALID_UUID) is False
        assert _is_valid_uuid("") is False
        assert _is_valid_uuid("12345") is False

    def test_require_uuid_raises_on_invalid(self):
        from app.agent.kg_tools import _require_uuid
        with pytest.raises(ValueError, match="Invalid UUID"):
            _require_uuid(INVALID_UUID, "entity_id")

    def test_require_uuid_passes_on_valid(self):
        from app.agent.kg_tools import _require_uuid
        # Should not raise
        _require_uuid(VALID_UUID, "team_id")

    def test_nil_uuid_is_valid(self):
        from app.agent.kg_tools import _is_valid_uuid
        assert _is_valid_uuid("00000000-0000-0000-0000-000000000000") is True


# ── kg_tools: aggregate_kg unknown type ──────────────────────────────────────

class TestAggregateKgValidation:
    """aggregate_kg should reject unknown aggregation types without touching the DB."""

    @pytest.mark.asyncio
    async def test_unknown_aggregation_type_returns_error(self):
        from app.agent.kg_tools import aggregate_kg
        result = await aggregate_kg(team_id=TEAM_ID, aggregation_type="drop_table_users")
        assert "error" in result
        assert result["results"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_team_uuid_raises(self):
        from app.agent.kg_tools import aggregate_kg
        with pytest.raises(ValueError, match="Invalid UUID"):
            await aggregate_kg(team_id=INVALID_UUID, aggregation_type="total_entity_count")

    def test_aggregation_types_list_is_non_empty(self):
        from app.agent.kg_tools import AGGREGATION_TYPES
        assert len(AGGREGATION_TYPES) >= 5
        assert "entity_count_by_type" in AGGREGATION_TYPES
        assert "top_connected_entities" in AGGREGATION_TYPES


# ── kg_tools: search_kg_entities validation ───────────────────────────────────

class TestSearchKgEntities:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_result(self):
        from app.agent.kg_tools import search_kg_entities
        # Empty query should short-circuit before DB access
        with patch("app.agent.kg_tools._acquire") as mock_acq:
            result = await search_kg_entities(query="", team_id=TEAM_ID)
        assert result["entities"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_team_uuid_raises(self):
        from app.agent.kg_tools import search_kg_entities
        with pytest.raises(ValueError, match="Invalid UUID"):
            await search_kg_entities(query="Blackstone", team_id=INVALID_UUID)

    @pytest.mark.asyncio
    async def test_limit_is_capped_at_50(self):
        """Limit above 50 should be silently capped to 50."""
        from app.agent.kg_tools import search_kg_entities

        captured_limit = []

        async def mock_fetch(sql, *args):
            # The limit param is the third positional arg after (query_lower, team_id, limit)
            captured_limit.append(args[-1])
            return []

        mock_conn = AsyncMock()
        mock_conn.fetch = mock_fetch
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.kg_tools._acquire", return_value=mock_ctx):
            await search_kg_entities(query="test", team_id=TEAM_ID, limit=999)

        assert captured_limit[0] == 50


# ── kg_tools: find_connections same entity ────────────────────────────────────

class TestFindConnections:
    @pytest.mark.asyncio
    async def test_same_source_and_target_returns_error(self):
        from app.agent.kg_tools import find_connections
        result = await find_connections(
            source_id=VALID_UUID,
            target_id=VALID_UUID,
            team_id=TEAM_ID,
        )
        assert "error" in result
        assert result["paths"] == []

    @pytest.mark.asyncio
    async def test_invalid_source_uuid_raises(self):
        from app.agent.kg_tools import find_connections
        with pytest.raises(ValueError, match="Invalid UUID"):
            await find_connections(
                source_id=INVALID_UUID,
                target_id=VALID_UUID_2,
                team_id=TEAM_ID,
            )

    @pytest.mark.asyncio
    async def test_max_hops_capped_at_5(self):
        """max_hops above 5 should be silently capped."""
        from app.agent.kg_tools import find_connections

        captured_hops = []

        async def mock_fetch(sql, *args):
            # max_hops is the 3rd positional arg (source_id, team_id, max_hops, target_id)
            captured_hops.append(args[2])
            return []

        mock_conn = AsyncMock()
        mock_conn.fetch = mock_fetch
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.kg_tools._acquire", return_value=mock_ctx):
            await find_connections(
                source_id=VALID_UUID,
                target_id=VALID_UUID_2,
                team_id=TEAM_ID,
                max_hops=100,
            )

        assert captured_hops[0] == 5


# ── kg_tools: get_entity_details validation ───────────────────────────────────

class TestGetEntityDetails:
    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        from app.agent.kg_tools import get_entity_details
        result = await get_entity_details(entity_ids=[], team_id=TEAM_ID)
        assert result["entities"] == {}
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_uuid_in_list_returns_error(self):
        from app.agent.kg_tools import get_entity_details
        result = await get_entity_details(entity_ids=[INVALID_UUID, VALID_UUID], team_id=TEAM_ID)
        assert "error" in result
        assert result["entities"] == {}

    @pytest.mark.asyncio
    async def test_invalid_team_uuid_raises(self):
        from app.agent.kg_tools import get_entity_details
        with pytest.raises(ValueError):
            await get_entity_details(entity_ids=[VALID_UUID], team_id=INVALID_UUID)


# ── kg_tools: get_entity_relationships direction validation ───────────────────

class TestGetEntityRelationships:
    @pytest.mark.asyncio
    async def test_invalid_direction_raises(self):
        from app.agent.kg_tools import get_entity_relationships
        with pytest.raises(ValueError, match="Invalid direction"):
            await get_entity_relationships(
                entity_id=VALID_UUID,
                team_id=TEAM_ID,
                direction="sideways",  # type: ignore[arg-type]
            )

    @pytest.mark.asyncio
    async def test_invalid_entity_uuid_raises(self):
        from app.agent.kg_tools import get_entity_relationships
        with pytest.raises(ValueError, match="Invalid UUID"):
            await get_entity_relationships(
                entity_id=INVALID_UUID,
                team_id=TEAM_ID,
            )


# ── kg_tools: explore_neighborhood depth cap ─────────────────────────────────

class TestExploreNeighborhood:
    @pytest.mark.asyncio
    async def test_depth_capped_at_2(self):
        """depth > 2 should be silently capped to 2 (the depth=2 SQL path)."""
        from app.agent.kg_tools import explore_neighborhood

        # Mock: center entity found, no edges
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, k: {
            "id": uuid.UUID(VALID_UUID), "name": "Test", "entity_type": "person",
            "aliases": [], "description": "", "disambiguation_context": "",
            "metadata": {}, "team_id": uuid.UUID(TEAM_ID),
            "created_at": None, "updated_at": None,
        }[k]
        mock_row.keys = lambda: ["id", "name", "entity_type", "aliases", "description",
                                  "disambiguation_context", "metadata", "team_id",
                                  "created_at", "updated_at"]

        # Create a proper asyncpg.Record mock
        center_mock = MagicMock()
        center_mock.__iter__ = lambda s: iter([
            ("id", uuid.UUID(VALID_UUID)), ("name", "Test"), ("entity_type", "person"),
            ("aliases", []), ("description", ""), ("disambiguation_context", ""),
            ("metadata", {}), ("team_id", uuid.UUID(TEAM_ID)),
            ("created_at", None), ("updated_at", None),
        ])

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=center_mock)
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.agent.kg_tools._acquire", return_value=mock_ctx):
            result = await explore_neighborhood(
                entity_id=VALID_UUID,
                team_id=TEAM_ID,
                depth=99,
            )

        # depth should be capped — we verify via the result's depth field
        assert result.get("depth") == 2


# ── kg_chat: event dataclasses ────────────────────────────────────────────────

class TestKGChatEvents:
    def test_text_delta_has_token(self):
        from app.agent.kg_chat import KGTextDelta
        ev = KGTextDelta(token="hello")
        assert ev.token == "hello"

    def test_highlight_has_entity_ids(self):
        from app.agent.kg_chat import KGHighlight
        ev = KGHighlight(entity_ids=[VALID_UUID])
        assert VALID_UUID in ev.entity_ids

    def test_path_has_steps(self):
        from app.agent.kg_chat import KGPath
        steps = [{"entity_id": VALID_UUID, "predicate": None}]
        ev = KGPath(steps=steps)
        assert ev.steps == steps

    def test_done_has_text_and_messages(self):
        from app.agent.kg_chat import KGDone
        ev = KGDone(text="final", messages=[])
        assert ev.text == "final"


# ── kg_chat: system prompt includes ontology ──────────────────────────────────

class TestKGChatSystemPrompt:
    def test_system_prompt_references_ontology(self):
        from app.agent.kg_chat import _build_kg_system_prompt
        prompt = _build_kg_system_prompt()
        # Should include at least one entity type from the ontology
        assert "person" in prompt.lower()
        # Should mention tool call limit
        assert "6" in prompt

    def test_system_prompt_is_stable_across_calls(self):
        from app.agent.kg_chat import _build_kg_system_prompt
        p1 = _build_kg_system_prompt()
        p2 = _build_kg_system_prompt()
        assert p1 == p2


# ── kg_chat: openai tools schema ─────────────────────────────────────────────

class TestKGOpenAITools:
    def test_returns_six_tools(self):
        from app.agent.kg_chat import _get_kg_openai_tools
        tools = _get_kg_openai_tools()
        assert len(tools) == 6

    def test_tool_names_match_spec(self):
        from app.agent.kg_chat import _get_kg_openai_tools
        names = {t["function"]["name"] for t in _get_kg_openai_tools()}
        expected = {
            "search_kg_entities",
            "get_entity_relationships",
            "find_connections",
            "aggregate_kg",
            "get_entity_details",
            "explore_neighborhood",
        }
        assert names == expected

    def test_all_tools_have_required_openai_structure(self):
        from app.agent.kg_chat import _get_kg_openai_tools
        for tool in _get_kg_openai_tools():
            assert tool["type"] == "function"
            assert "function" in tool
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert "required" in fn["parameters"]


# ── kg_chat: SSE helper ───────────────────────────────────────────────────────

class TestSSEHelper:
    def test_sse_format(self):
        from app.agent.kg_chat import _sse
        result = _sse("text_delta", {"token": "hello"})
        assert result.startswith("event: text_delta\n")
        assert "data:" in result
        data = json.loads(result.split("data: ")[1].split("\n")[0])
        assert data["token"] == "hello"

    def test_sse_ends_with_double_newline(self):
        from app.agent.kg_chat import _sse
        result = _sse("done", {"message": "ok"})
        assert result.endswith("\n\n")


# ── kg_chat: UUID extraction from text ───────────────────────────────────────

class TestExtractEntityIds:
    def test_extracts_uuids_from_text(self):
        from app.agent.kg_chat import _extract_entity_ids_from_text
        text = f"Entity A has id {VALID_UUID} and entity B has id {VALID_UUID_2}."
        ids = _extract_entity_ids_from_text(text)
        assert VALID_UUID in ids
        assert VALID_UUID_2 in ids

    def test_returns_empty_for_no_uuids(self):
        from app.agent.kg_chat import _extract_entity_ids_from_text
        assert _extract_entity_ids_from_text("no uuids here") == []

    def test_deduplicates_uuids(self):
        from app.agent.kg_chat import _extract_entity_ids_from_text
        text = f"{VALID_UUID} appears twice: {VALID_UUID}"
        ids = _extract_entity_ids_from_text(text)
        assert ids.count(VALID_UUID) == 1


# ── kg_chat_sessions: dict conversion helpers ─────────────────────────────────

class TestSessionDictConversion:
    """Test row-to-dict conversion helpers without hitting the DB."""

    def _make_record(self, d: dict) -> MagicMock:
        """Create a minimal asyncpg.Record-like mock."""
        mock = MagicMock()
        mock.__iter__ = MagicMock(return_value=iter(d.items()))
        mock.keys = MagicMock(return_value=list(d.keys()))
        # Support dict(record) via __iter__
        return mock

    def test_session_uuid_fields_are_stringified(self):
        from app.db.kg_chat_sessions import _session_to_dict
        import datetime

        session_id = uuid.uuid4()
        team_id = uuid.uuid4()
        now = datetime.datetime.now()

        row = self._make_record({
            "id": session_id,
            "team_id": team_id,
            "user_sid": "user1",
            "created_at": now,
            "updated_at": now,
        })
        result = _session_to_dict(row)
        assert result["id"] == str(session_id)
        assert result["team_id"] == str(team_id)
        assert isinstance(result["created_at"], str)

    def test_message_entity_highlights_stringified(self):
        from app.db.kg_chat_sessions import _message_to_dict
        import datetime

        msg_id = uuid.uuid4()
        session_id = uuid.uuid4()
        eid = uuid.uuid4()
        now = datetime.datetime.now()

        row = self._make_record({
            "id": msg_id,
            "session_id": session_id,
            "role": "assistant",
            "content": "hello",
            "tool_calls": None,
            "tool_call_id": None,
            "entity_highlights": [eid],
            "created_at": now,
        })
        result = _message_to_dict(row)
        assert result["id"] == str(msg_id)
        assert result["entity_highlights"] == [str(eid)]

    def test_message_null_highlights_becomes_empty_list(self):
        from app.db.kg_chat_sessions import _message_to_dict
        import datetime

        row = self._make_record({
            "id": uuid.uuid4(),
            "session_id": uuid.uuid4(),
            "role": "user",
            "content": "q",
            "tool_calls": None,
            "tool_call_id": None,
            "entity_highlights": None,
            "created_at": datetime.datetime.now(),
        })
        result = _message_to_dict(row)
        assert result["entity_highlights"] == []


# ── Router: message history conversion ───────────────────────────────────────

class TestMessagesToOpenAIFormat:
    def test_basic_user_assistant_messages(self):
        from app.routers.kg_chat import _messages_to_openai_format
        messages = [
            {"role": "user", "content": "hello", "tool_calls": None, "tool_call_id": None},
            {"role": "assistant", "content": "hi", "tool_calls": None, "tool_call_id": None},
        ]
        result = _messages_to_openai_format(messages)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["content"] == "hi"

    def test_tool_calls_included_when_present(self):
        from app.routers.kg_chat import _messages_to_openai_format
        tc = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
        messages = [
            {"role": "assistant", "content": None, "tool_calls": tc, "tool_call_id": None},
        ]
        result = _messages_to_openai_format(messages)
        assert result[0]["tool_calls"] == tc

    def test_tool_call_id_included_when_present(self):
        from app.routers.kg_chat import _messages_to_openai_format
        messages = [
            {"role": "tool", "content": "result", "tool_calls": None, "tool_call_id": "c1"},
        ]
        result = _messages_to_openai_format(messages)
        assert result[0]["tool_call_id"] == "c1"


# ── kg_chat: rate limit check (Redis fallback) ────────────────────────────────

class TestRateLimitCheck:
    @pytest.mark.asyncio
    async def test_allows_when_redis_unavailable(self):
        """Rate limit check should fail open (allow) when Redis raises."""
        from app.agent.kg_chat import check_rate_limit

        with patch("app.agent.kg_chat.get_redis", side_effect=RuntimeError("no redis")):
            allowed, count = await check_rate_limit("user123")

        assert allowed is True

    @pytest.mark.asyncio
    async def test_blocks_when_over_limit(self):
        """Rate limit should deny when Redis counter exceeds limit."""
        from app.agent.kg_chat import check_rate_limit, _RATE_LIMIT_MSGS_PER_MINUTE

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=_RATE_LIMIT_MSGS_PER_MINUTE + 1)
        mock_redis.expire = AsyncMock()

        with patch("app.agent.kg_chat.get_redis", AsyncMock(return_value=mock_redis)):
            allowed, count = await check_rate_limit("user123")

        assert allowed is False
        assert count == _RATE_LIMIT_MSGS_PER_MINUTE + 1

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        from app.agent.kg_chat import check_rate_limit

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()

        with patch("app.agent.kg_chat.get_redis", AsyncMock(return_value=mock_redis)):
            allowed, count = await check_rate_limit("user123")

        assert allowed is True
        assert count == 5


# ── kg_chat: fallback keyword search ─────────────────────────────────────────

class TestKGChatFallback:
    @pytest.mark.asyncio
    async def test_fallback_returns_no_results_message(self):
        from app.agent.kg_chat import kg_chat_fallback

        with patch("app.agent.kg_chat.db_query_kg", AsyncMock(return_value=[])):
            result = await kg_chat_fallback("test query", TEAM_ID)

        assert "keyword search" in result.lower()
        assert "no results" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_lists_found_entities(self):
        from app.agent.kg_chat import kg_chat_fallback

        entities = [
            {"name": "Blackstone", "entity_type": "pe_fund"},
            {"name": "Tiger Capital", "entity_type": "company"},
        ]
        with patch("app.agent.kg_chat.db_query_kg", AsyncMock(return_value=entities)):
            result = await kg_chat_fallback("test", TEAM_ID)

        assert "Blackstone" in result
        assert "Tiger Capital" in result

    @pytest.mark.asyncio
    async def test_fallback_handles_db_failure_gracefully(self):
        from app.agent.kg_chat import kg_chat_fallback

        with patch("app.agent.kg_chat.db_query_kg", side_effect=Exception("db down")):
            result = await kg_chat_fallback("test", TEAM_ID)

        assert "try again" in result.lower() or "failed" in result.lower()

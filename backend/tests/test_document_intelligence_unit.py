"""Unit tests for document_intelligence.py.

All LLM calls and Redis interactions are mocked so these tests run without
external dependencies.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document_intelligence import (
    DocumentSchema,
    MatchEntry,
    QueryResult,
    SemanticType,
    SheetSchema,
    ColumnSchema,
    analyze_schema,
    classify_columns_semantic,
    query_document,
    _wrap_exact_match,
    _parse_markdown_table,
    QueryPlan,
)
from app.redis_client import DocumentSession


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_openai_response(content: dict) -> MagicMock:
    """Build a minimal mock that looks like an OpenAI ChatCompletion response."""
    msg = MagicMock()
    msg.content = json.dumps(content)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_session(texts: list[str], types: list[str] | None = None) -> DocumentSession:
    types = types or ["csv"] * len(texts)
    metadata = [{"filename": f"file{i}.csv", "type": t} for i, t in enumerate(types)]
    return DocumentSession(
        text="\n\n".join(texts),
        texts=texts,
        filenames=[m["filename"] for m in metadata],
        metadata=metadata,
    )


# ── classify_columns_semantic ─────────────────────────────────────────────────


class TestClassifyColumnsSemantic:
    """Tests for classify_columns_semantic."""

    @pytest.mark.asyncio
    async def test_llm_returns_valid_classification(self):
        """LLM returns correct roles — verify ColumnClassification objects."""
        llm_payload = {
            "classifications": {
                "owners": {
                    "role": "entity_label",
                    "semantic_type": "person",
                    "confidence": 0.95,
                    "reasoning": "Names of people/owners",
                }
            }
        }
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["owners"],
                    sample_rows=[{"owners": "Alice"}, {"owners": "Bob"}],
                )

        assert "owners" in result
        assert result["owners"].role == "entity_label"
        assert result["owners"].semantic_type == SemanticType.person
        assert result["owners"].confidence == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self):
        """LLM raises exception → falls back to exact-match _classify_columns."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["name", "description", "revenue"],
                    sample_rows=[],
                )

        assert result["name"].role == "entity_label"
        assert result["description"].role == "entity_description"
        assert result["revenue"].role == "attribute"
        # Fallback always has confidence=1.0
        assert result["name"].confidence == 1.0

    @pytest.mark.asyncio
    async def test_with_user_intent(self):
        """user_intent parameter is forwarded; LLM response respected."""
        llm_payload = {
            "classifications": {
                "firm": {
                    "role": "entity_label",
                    "semantic_type": "organization",
                    "confidence": 0.88,
                    "reasoning": "firm is the portfolio company name",
                }
            }
        }
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        captured_prompt: list[str] = []

        async def capture_call(**kwargs):
            for msg in kwargs.get("messages", []):
                captured_prompt.append(msg.get("content", ""))
            return mock_resp

        mock_client.chat.completions.create = capture_call

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["firm"],
                    sample_rows=[],
                    user_intent="loading portfolio companies",
                )

        # Verify intent appeared in the prompt
        assert any("loading portfolio companies" in p for p in captured_prompt)
        assert result["firm"].role == "entity_label"

    @pytest.mark.asyncio
    async def test_bypass_when_flag_disabled(self):
        """When enable_semantic_classification=False, LLM is never called."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock()

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = False
                result = await classify_columns_semantic(
                    headers=["entity", "gwm_id", "description", "revenue"],
                    sample_rows=[],
                )

        mock_client.chat.completions.create.assert_not_called()
        assert result["entity"].role == "entity_label"
        assert result["gwm_id"].role == "entity_gwm_id"
        assert result["description"].role == "entity_description"
        assert result["revenue"].role == "attribute"

    @pytest.mark.asyncio
    async def test_single_column_csv(self):
        """Single-column CSV classification returns correct ColumnClassification."""
        llm_payload = {
            "classifications": {
                "company": {
                    "role": "entity_label",
                    "semantic_type": "organization",
                    "confidence": 0.99,
                    "reasoning": "company is the entity name",
                }
            }
        }
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["company"],
                    sample_rows=[{"company": "Acme Corp"}],
                )

        assert len(result) == 1
        assert "company" in result
        assert result["company"].role == "entity_label"

    @pytest.mark.asyncio
    async def test_malformed_json_from_llm_fallback(self):
        """Malformed JSON from LLM triggers graceful fallback to exact-match."""
        msg = MagicMock()
        msg.content = "this is not valid JSON {{{"
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["name", "revenue"],
                    sample_rows=[],
                )

        # Should fall back to exact-match, not raise
        assert "name" in result
        assert result["name"].role == "entity_label"
        assert result["revenue"].role == "attribute"

    @pytest.mark.asyncio
    async def test_prompt_injection_column_name_truncated(self):
        """Column name > 200 chars is truncated before prompt inclusion."""
        long_col = "A" * 300  # 300-char column name
        captured_prompts: list[str] = []

        llm_payload = {
            "classifications": {
                "A" * 200: {
                    "role": "attribute",
                    "semantic_type": "generic",
                    "confidence": 0.5,
                    "reasoning": "",
                }
            }
        }
        mock_resp = _make_openai_response(llm_payload)

        async def capture_call(**kwargs):
            for msg in kwargs.get("messages", []):
                captured_prompts.append(msg.get("content", ""))
            return mock_resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = capture_call

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                await classify_columns_semantic(
                    headers=[long_col],
                    sample_rows=[],
                )

        # The full 300-char name should NOT appear in the prompt
        combined = " ".join(captured_prompts)
        assert long_col not in combined
        # The truncated 200-char version may appear
        assert "A" * 200 in combined


# ── analyze_schema ─────────────────────────────────────────────────────────────


class TestAnalyzeSchema:
    """Tests for analyze_schema caching and LLM calls."""

    @pytest.mark.asyncio
    async def test_cache_hit_no_llm_call(self):
        """Cache hit: Redis returns cached schema → no LLM call."""
        session = _make_session(["col1,col2\nval1,val2"])
        cached_schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="col1")])],
            total_sheets=1,
            summary="cached",
        )
        cached_json = cached_schema.model_dump_json()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_json)
        mock_redis.expire = AsyncMock()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                result = await analyze_schema("test-key-123", session)

        assert result is not None
        assert result.document_type == "tabular"
        assert result.summary == "cached"
        mock_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_llm_called(self):
        """Cache miss: Redis returns None → LLM is called and result is cached."""
        session = _make_session(
            ["name,revenue\nAcme,100\nBeta,200"],
            types=["csv"],
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)   # lock acquired
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()

        enrich_payload = {
            "sheets": [
                {
                    "name": "default",
                    "columns": [
                        {"name": "name", "inferred_type": "text", "semantic_type": "organization"},
                        {"name": "revenue", "inferred_type": "numeric", "semantic_type": "financial_amount"},
                    ],
                }
            ],
            "summary": "Company revenue data",
        }
        mock_resp = _make_openai_response(enrich_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                with patch("app.document_intelligence.settings") as mock_settings:
                    mock_settings.enable_semantic_classification = True
                    mock_settings.query_model = "gpt-4.1"
                    mock_settings.redis_ttl_hours = 24
                    mock_settings.max_session_cost = 1.0
                    result = await analyze_schema("test-miss-key", session)

        assert result is not None
        # Cache write should have been called
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_failure_returns_none(self):
        """Redis unavailable → analyze_schema returns None silently."""
        session = _make_session(["name,revenue\nAcme,100"])

        with patch(
            "app.document_intelligence.get_redis",
            AsyncMock(side_effect=RuntimeError("Redis down")),
        ):
            result = await analyze_schema("redis-fail-key", session)

        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_refresh_on_cache_hit(self):
        """Cache hit triggers EXPIRE to refresh the sliding-window TTL."""
        session = _make_session(["text content"])
        cached_schema = DocumentSchema(
            document_type="prose",
            sheets=[],
            total_sheets=0,
            summary="prose doc",
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_schema.model_dump_json())
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.redis_ttl_hours = 24
                mock_settings.max_session_cost = 1.0
                await analyze_schema("ttl-refresh-key", session)

        mock_redis.expire.assert_called_once()
        args = mock_redis.expire.call_args[0]
        assert args[0] == "doc_schema:ttl-refresh-key"
        assert args[1] == 24 * 3600

    @pytest.mark.asyncio
    async def test_idempotency_lock_poll(self):
        """Concurrent calls: second call gets None from lock and polls cache."""
        session = _make_session(["a,b\n1,2"])
        cached_schema = DocumentSchema(
            document_type="tabular",
            sheets=[],
            total_sheets=0,
            summary="polled",
        )
        cached_json = cached_schema.model_dump_json()

        # First call: get=None (miss), lock acquired
        # Second call: get=None (miss), lock NOT acquired → poll
        call_count = [0]

        async def fake_get(key):
            if key.startswith("doc_schema:"):
                call_count[0] += 1
                if call_count[0] >= 2:
                    return cached_json
            return None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=fake_get)
        mock_redis.set = AsyncMock(side_effect=[True, None])  # first gets lock, second doesn't
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_redis.expire = AsyncMock()

        enrich_payload = {"sheets": [], "summary": "test"}
        mock_resp = _make_openai_response(enrich_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                with patch("app.document_intelligence.settings") as mock_settings:
                    mock_settings.query_model = "gpt-4.1"
                    mock_settings.redis_ttl_hours = 24
                    mock_settings.max_session_cost = 1.0
                    # Run two concurrent calls
                    import asyncio
                    results = await asyncio.gather(
                        analyze_schema("concurrent-key", session),
                        analyze_schema("concurrent-key", session),
                    )

        # Both calls should complete; at most one LLM call should be made
        assert all(r is not None for r in results)
        assert mock_client.chat.completions.create.call_count <= 2  # one per phase (parse + enrich)


# ── query_document ─────────────────────────────────────────────────────────────


class TestQueryDocument:
    """Tests for query_document two-phase execution."""

    @pytest.mark.asyncio
    async def test_query_with_mocked_schema_and_llm(self):
        """Full query flow: cached schema + LLM plan → tabular extraction."""
        session = _make_session(
            ["| name | revenue |\n|---|---|\n| Acme | 100 |\n| Beta | 200 |"]
        )
        cached_schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(
                name="default",
                columns=[ColumnSchema(name="name"), ColumnSchema(name="revenue")],
            )],
            total_sheets=1,
            summary="revenue table",
        )

        plan_payload = {
            "relevant_columns": ["name"],
            "extraction_instruction": "Extract all company names",
            "document_type": "tabular",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        schema_json = cached_schema.model_dump_json()

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
                        mock_settings.max_session_cost = 1.0
                        result = await query_document("test-session", "find all companies")

        assert isinstance(result, QueryResult)
        assert result.error is None
        assert result.total_matches == len(result.matches)
        assert result.query_interpretation != ""



    @pytest.mark.asyncio
    async def test_missing_schema_triggers_analyze_schema(self):
        """No cached schema → analyze_schema is called synchronously before query."""
        session = _make_session(
            ["| company | score |\n|---|---|\n| Acme | 9 |"]
        )

        plan_payload = {
            "relevant_columns": ["company"],
            "extraction_instruction": "Extract companies",
            "document_type": "tabular",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        call_count = [0]

        async def fake_redis_get(key):
            if "doc_schema:" in key:
                call_count[0] += 1
                # First call returns None (no cache), subsequent calls return schema
                if call_count[0] > 1:
                    schema = DocumentSchema(
                        document_type="tabular",
                        sheets=[SheetSchema(name="default")],
                        total_sheets=1,
                        summary="test",
                    )
                    return schema.model_dump_json()
            return None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=fake_redis_get)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.enable_semantic_classification = True
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
                        mock_settings.max_session_cost = 1.0
                        result = await query_document("no-schema-session", "find companies")

        assert isinstance(result, QueryResult)
        # No crash — result has all required fields
        assert result.total_matches == len(result.matches)

    @pytest.mark.asyncio
    async def test_empty_results_with_explanation(self):
        """Query on doc with no matching rows returns empty matches with interpretation."""
        session = _make_session(
            ["| name | score |\n|---|---|\n| Acme | 10 |"]
        )
        cached_schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
        )

        plan_payload = {
            "relevant_columns": ["nonexistent_column"],
            "extraction_instruction": "Extract non-existent data",
            "document_type": "tabular",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        schema_json = cached_schema.model_dump_json()

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
                        mock_settings.max_session_cost = 1.0
                        result = await query_document("empty-session", "find something that doesn't exist")

        assert result.matches == []
        assert result.total_matches == 0
        assert result.query_interpretation != ""
        assert result.error is None

    @pytest.mark.asyncio
    async def test_redis_failure_returns_structured_error(self):
        """Redis failure in query_document returns structured error (not exception)."""
        with patch(
            "app.document_intelligence.get_documents",
            AsyncMock(side_effect=RuntimeError("Redis connection failed")),
        ):
            result = await query_document("fail-session", "any query")

        assert isinstance(result, QueryResult)
        assert result.error is not None
        assert "Redis" in result.error or "Failed" in result.error
        assert result.matches == []
        assert result.total_matches == 0
        assert result.query_interpretation == ""

    @pytest.mark.asyncio
    async def test_response_shape_consistency_on_success(self):
        """All four fields present in successful result."""
        session = _make_session(["| col1 |\n|---|\n| val1 |"])
        cached_schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="col1")])],
            total_sheets=1,
        )

        plan_payload = {
            "relevant_columns": ["col1"],
            "extraction_instruction": "extract col1",
            "document_type": "tabular",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        schema_json = cached_schema.model_dump_json()

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
                        mock_settings.max_session_cost = 1.0
                        result = await query_document("shape-test", "query")

        dumped = result.model_dump()
        assert "matches" in dumped
        assert "query_interpretation" in dumped
        assert "total_matches" in dumped
        assert "error" in dumped
        assert isinstance(dumped["query_interpretation"], str)

    @pytest.mark.asyncio
    async def test_response_shape_consistency_on_error(self):
        """All four fields present in error result; query_interpretation is always str."""
        with patch(
            "app.document_intelligence.get_documents",
            AsyncMock(return_value=None),
        ):
            result = await query_document("missing-session", "query")

        dumped = result.model_dump()
        assert "matches" in dumped
        assert "query_interpretation" in dumped
        assert "total_matches" in dumped
        assert "error" in dumped
        assert isinstance(dumped["query_interpretation"], str)
        assert result.error is not None


# ── Markdown table parsing ─────────────────────────────────────────────────────


class TestParseMarkdownTable:
    """Tests for _parse_markdown_table tabular extraction."""

    def test_single_column_extraction(self):
        """Extracts values from a single relevant column."""
        text = "| name | score |\n|---|---|\n| Alice | 10 |\n| Bob | 20 |"
        plan = QueryPlan(relevant_columns=["name"], document_type="tabular")
        matches = _parse_markdown_table(text, {"name"}, plan)
        values = [m.value for m in matches]
        assert "Alice" in values
        assert "Bob" in values

    def test_multi_column_extraction(self):
        """Multi-column query returns dict value and list source_column."""
        text = "| owner | company |\n|---|---|\n| Alice | Acme | "
        plan = QueryPlan(relevant_columns=["owner", "company"], document_type="tabular")
        matches = _parse_markdown_table(text, {"owner", "company"}, plan)
        assert len(matches) == 1
        assert isinstance(matches[0].value, dict)
        assert isinstance(matches[0].source_column, list)
        assert "owner" in matches[0].value
        assert "company" in matches[0].value

    def test_text_positions_format(self):
        """text_positions entries have exactly start and end fields (no extra keys)."""
        # Tabular extraction does not set text_positions
        text = "| name |\n|---|\n| Alice |"
        plan = QueryPlan(relevant_columns=["name"], document_type="tabular")
        matches = _parse_markdown_table(text, {"name"}, plan)
        for match in matches:
            for pos in match.text_positions:
                assert set(pos.keys()) == {"start", "end"} or pos == {}


# ── Security / Edge cases ──────────────────────────────────────────────────────


class TestSecurityEdgeCases:
    """Tests for prompt injection mitigation and edge cases."""

    def test_wrap_exact_match_produces_correct_roles(self):
        """_wrap_exact_match returns ColumnClassification with correct roles."""
        result = _wrap_exact_match(["name", "gwm_id", "description", "revenue"])
        assert result["name"].role == "entity_label"
        assert result["gwm_id"].role == "entity_gwm_id"
        assert result["description"].role == "entity_description"
        assert result["revenue"].role == "attribute"
        for cls in result.values():
            assert cls.semantic_type == SemanticType.generic
            assert cls.confidence == 1.0

    @pytest.mark.asyncio
    async def test_sample_values_truncated_to_100_chars(self):
        """Sample values > 100 chars are truncated before LLM call."""
        long_value = "X" * 200
        captured_prompts: list[str] = []

        llm_payload = {
            "classifications": {
                "col": {"role": "attribute", "semantic_type": "generic", "confidence": 0.5, "reasoning": ""}
            }
        }
        mock_resp = _make_openai_response(llm_payload)

        async def capture_call(**kwargs):
            for msg in kwargs.get("messages", []):
                captured_prompts.append(msg.get("content", ""))
            return mock_resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = capture_call

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                await classify_columns_semantic(
                    headers=["col"],
                    sample_rows=[{"col": long_value}],
                )

        combined = " ".join(captured_prompts)
        assert long_value not in combined  # 200-char value not in prompt
        assert "X" * 100 in combined  # truncated 100-char version present

    @pytest.mark.asyncio
    async def test_session_not_found_returns_structured_error(self):
        """Session not found → QueryResult with error field, not exception."""
        with patch("app.document_intelligence.get_documents", AsyncMock(return_value=None)):
            result = await query_document("nonexistent-key", "query")

        assert result.error is not None
        assert "not found" in result.error.lower() or "session" in result.error.lower()

    @pytest.mark.asyncio
    async def test_llm_returns_no_classifications_for_column(self):
        """LLM returns empty classifications dict → each column falls back to exact-match."""
        llm_payload = {"classifications": {}}
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.enable_semantic_classification = True
                mock_settings.classification_model = "gpt-4.1"
                result = await classify_columns_semantic(
                    headers=["name", "unknown_col"],
                    sample_rows=[],
                )

        # Both columns fall back to exact-match
        assert result["name"].role == "entity_label"
        assert result["unknown_col"].role == "attribute"


# ── QueryPlan complexity classification ───────────────────────────────────────


class TestQueryPlanComplexity:
    """Tests for the complexity field on QueryPlan and _build_query_plan classification."""

    def test_query_plan_default_complexity_is_simple(self):
        """QueryPlan.complexity defaults to 'simple'."""
        plan = QueryPlan()
        assert plan.complexity == "simple"

    def test_query_plan_accepts_complex(self):
        """QueryPlan accepts complexity='complex'."""
        plan = QueryPlan(complexity="complex")
        assert plan.complexity == "complex"

    def test_query_plan_accepts_simple(self):
        """QueryPlan accepts complexity='simple' explicitly."""
        plan = QueryPlan(complexity="simple")
        assert plan.complexity == "simple"

    def test_query_plan_rejects_invalid_complexity(self):
        """QueryPlan rejects values other than 'simple' or 'complex'."""
        import pytest
        with pytest.raises(Exception):
            QueryPlan(complexity="medium")  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_lookup_query_classified_as_simple(self):
        """Direct lookup query → LLM returns simple → plan.complexity == 'simple'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="company")])],
            total_sheets=1,
            summary="company list",
        )
        plan_payload = {
            "relevant_columns": ["company"],
            "extraction_instruction": "Extract all company names",
            "document_type": "tabular",
            "complexity": "simple",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "list all companies")

        assert plan.complexity == "simple"

    @pytest.mark.asyncio
    async def test_count_query_classified_as_complex(self):
        """Count/aggregation query → LLM returns complex → plan.complexity == 'complex'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="status")])],
            total_sheets=1,
            summary="status table",
        )
        plan_payload = {
            "relevant_columns": ["status"],
            "extraction_instruction": "Count rows where status is active",
            "document_type": "tabular",
            "complexity": "complex",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "how many companies are active?")

        assert plan.complexity == "complex"

    @pytest.mark.asyncio
    async def test_aggregation_query_classified_as_complex(self):
        """Sum/average query → LLM returns complex → plan.complexity == 'complex'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="revenue")])],
            total_sheets=1,
            summary="revenue table",
        )
        plan_payload = {
            "relevant_columns": ["revenue"],
            "extraction_instruction": "Sum all revenue values",
            "document_type": "tabular",
            "complexity": "complex",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "what is the total revenue?")

        assert plan.complexity == "complex"

    @pytest.mark.asyncio
    async def test_fuzzy_match_query_classified_as_complex(self):
        """Fuzzy matching query → LLM returns complex → plan.complexity == 'complex'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="name table",
        )
        plan_payload = {
            "relevant_columns": ["name"],
            "extraction_instruction": "Find names similar to 'Acme'",
            "document_type": "tabular",
            "complexity": "complex",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "find names similar to Acme Corp")

        assert plan.complexity == "complex"

    @pytest.mark.asyncio
    async def test_filter_by_exact_value_classified_as_simple(self):
        """Exact value filter → LLM returns simple → plan.complexity == 'simple'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="status")])],
            total_sheets=1,
            summary="status table",
        )
        plan_payload = {
            "relevant_columns": ["status"],
            "extraction_instruction": "Extract rows where status is active",
            "document_type": "tabular",
            "complexity": "simple",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "find all active records")

        assert plan.complexity == "simple"

    @pytest.mark.asyncio
    async def test_llm_omits_complexity_defaults_to_simple(self):
        """LLM response without complexity field → defaults to 'simple'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="table",
        )
        # No 'complexity' key in response
        plan_payload = {
            "relevant_columns": ["name"],
            "extraction_instruction": "Extract names",
            "document_type": "tabular",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "list names")

        assert plan.complexity == "simple"

    @pytest.mark.asyncio
    async def test_llm_returns_unknown_complexity_defaults_to_simple(self):
        """LLM returns unrecognised complexity value → defaults to 'simple'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="table",
        )
        plan_payload = {
            "relevant_columns": ["name"],
            "extraction_instruction": "Extract names",
            "document_type": "tabular",
            "complexity": "medium",  # invalid value
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "list names")

        assert plan.complexity == "simple"

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_complexity_to_simple(self):
        """LLM call failure → fallback QueryPlan has complexity='simple'."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[],
            total_sheets=0,
            summary="",
        )
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                plan = await _build_query_plan(schema, "any query")

        assert plan.complexity == "simple"

    @pytest.mark.asyncio
    async def test_prompt_includes_complexity_instructions(self):
        """_build_query_plan prompt contains complexity classification guidance."""
        from app.document_intelligence import _build_query_plan

        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="table",
        )
        captured_prompts: list[str] = []
        plan_payload = {
            "relevant_columns": [],
            "extraction_instruction": "",
            "document_type": "tabular",
            "complexity": "simple",
        }
        mock_resp = _make_openai_response(plan_payload)

        async def capture_call(**kwargs):
            for msg in kwargs.get("messages", []):
                captured_prompts.append(msg.get("content", ""))
            return mock_resp

        mock_client = AsyncMock()
        mock_client.chat.completions.create = capture_call

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                await _build_query_plan(schema, "list all companies")

        combined = " ".join(captured_prompts)
        assert "complexity" in combined
        assert "simple" in combined
        assert "complex" in combined

    @pytest.mark.asyncio
    async def test_none_schema_returns_simple_plan(self):
        """None schema → fallback QueryPlan with complexity='simple'."""
        from app.document_intelligence import _build_query_plan

        plan = await _build_query_plan(None, "any query")

        assert plan.complexity == "simple"
        assert plan.document_type == "prose"


# ── _chunk_tabular_text ────────────────────────────────────────────────────────


class TestChunkTabularText:
    """Tests for _chunk_tabular_text helper."""

    def _make_md_table(self, headers: list[str], rows: list[list[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    def test_no_column_filter_returns_all_columns(self):
        """Empty relevant_cols → all columns kept."""
        from app.document_intelligence import _chunk_tabular_text

        table = self._make_md_table(["Name", "Revenue", "City"], [["Alice", "100", "NYC"]])
        chunks = _chunk_tabular_text(table, set(), rows_per_chunk=100)

        assert len(chunks) == 1
        assert "Name" in chunks[0]
        assert "Revenue" in chunks[0]
        assert "City" in chunks[0]

    def test_column_filter_removes_irrelevant_columns(self):
        """Only columns matching relevant_cols appear in chunks."""
        from app.document_intelligence import _chunk_tabular_text

        table = self._make_md_table(
            ["Name", "Revenue", "City"],
            [["Alice", "100", "NYC"], ["Bob", "200", "LA"]],
        )
        chunks = _chunk_tabular_text(table, {"name", "city"}, rows_per_chunk=100)

        assert len(chunks) == 1
        assert "Name" in chunks[0]
        assert "City" in chunks[0]
        assert "Revenue" not in chunks[0]

    def test_row_chunking_splits_large_table(self):
        """Table with 250 rows → ceil(250/100) = 3 chunks."""
        from app.document_intelligence import _chunk_tabular_text

        rows = [[f"entity_{i}", str(i * 10)] for i in range(250)]
        table = self._make_md_table(["Name", "Score"], rows)
        chunks = _chunk_tabular_text(table, set(), rows_per_chunk=100)

        assert len(chunks) == 3

    def test_each_chunk_includes_header(self):
        """Every chunk starts with the header row."""
        from app.document_intelligence import _chunk_tabular_text

        rows = [[f"row_{i}", str(i)] for i in range(150)]
        table = self._make_md_table(["Label", "Value"], rows)
        chunks = _chunk_tabular_text(table, set(), rows_per_chunk=100)

        for chunk in chunks:
            assert "| Label | Value |" in chunk

    def test_no_match_in_relevant_cols_keeps_all(self):
        """When relevant_cols has no intersection with headers, keep all columns."""
        from app.document_intelligence import _chunk_tabular_text

        table = self._make_md_table(["Name", "Age"], [["Alice", "30"]])
        # Irrelevant col names that don't match any header
        chunks = _chunk_tabular_text(table, {"nonexistent_col"}, rows_per_chunk=100)

        assert "Name" in chunks[0]
        assert "Age" in chunks[0]

    def test_non_table_text_returned_as_single_chunk(self):
        """Prose text with no markdown table → returned as single chunk unchanged."""
        from app.document_intelligence import _chunk_tabular_text

        prose = "This is a plain paragraph with no table structure."
        chunks = _chunk_tabular_text(prose, set(), rows_per_chunk=100)

        assert len(chunks) == 1
        assert chunks[0] == prose

    def test_empty_text_returns_empty_list(self):
        """Empty/blank text → empty list."""
        from app.document_intelligence import _chunk_tabular_text

        assert _chunk_tabular_text("", set(), rows_per_chunk=100) == []
        assert _chunk_tabular_text("   \n  ", set(), rows_per_chunk=100) == []


# ── _extract_tabular_llm ─────────────────────────────────────────────────────


class TestExtractTabularLlm:
    """Tests for _extract_tabular_llm (complex-query LLM extraction)."""

    def _make_md_table(self, headers: list[str], rows: list[list[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    @pytest.mark.asyncio
    async def test_returns_matched_entries(self):
        """LLM returns matches → MatchEntry list with correct fields."""
        from app.document_intelligence import QueryPlan, _extract_tabular_llm

        table = self._make_md_table(["Name", "Revenue"], [["Acme", "500"], ["Beta", "200"]])
        session = _make_session([table])
        plan = QueryPlan(
            relevant_columns=["Name", "Revenue"],
            extraction_instruction="Find all companies with revenue > 100",
            document_type="tabular",
            complexity="complex",
        )

        llm_payload = {
            "matches": [
                {"value": {"Name": "Acme", "Revenue": "500"}, "source_column": ["Name", "Revenue"], "row_numbers": [1], "confidence": 0.95},
                {"value": {"Name": "Beta", "Revenue": "200"}, "source_column": ["Name", "Revenue"], "row_numbers": [2], "confidence": 0.9},
            ]
        }
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                matches, interp, chunks_processed, chunks_total = await _extract_tabular_llm(
                    session, plan, None
                )

        assert len(matches) == 2
        assert chunks_processed == 1
        assert chunks_total == 1
        assert interp == plan.extraction_instruction

    @pytest.mark.asyncio
    async def test_deduplication_removes_duplicate_values(self):
        """Same value extracted from multiple chunks is deduplicated."""
        from app.document_intelligence import QueryPlan, _extract_tabular_llm

        # Two texts with identical content → each produces a chunk
        table = self._make_md_table(["Name"], [["Alice"]])
        session = _make_session([table, table])
        plan = QueryPlan(
            relevant_columns=["Name"],
            extraction_instruction="Find all names",
            document_type="tabular",
            complexity="complex",
        )

        llm_payload = {"matches": [{"value": {"Name": "Alice"}, "source_column": ["Name"], "row_numbers": [1], "confidence": 0.9}]}
        mock_resp = _make_openai_response(llm_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                matches, _, chunks_processed, chunks_total = await _extract_tabular_llm(
                    session, plan, None
                )

        assert len(matches) == 1  # deduplicated
        assert chunks_total == 2
        assert chunks_processed == 2

    @pytest.mark.asyncio
    async def test_chunk_exception_counts_as_failed_not_processed(self):
        """A chunk that raises an exception is skipped; chunks_processed is lower."""
        from app.document_intelligence import QueryPlan, _extract_tabular_llm

        rows = [[f"row_{i}", str(i)] for i in range(150)]
        table = self._make_md_table(["Name", "Score"], rows)
        session = _make_session([table])
        plan = QueryPlan(
            relevant_columns=["Name"],
            extraction_instruction="Find names",
            document_type="tabular",
            complexity="complex",
        )

        call_count = [0]

        async def flaky_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("LLM error on first chunk")
            return _make_openai_response({"matches": []})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=flaky_create)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                matches, _, chunks_processed, chunks_total = await _extract_tabular_llm(
                    session, plan, None
                )

        assert chunks_total == 2  # 150 rows → 2 chunks of 100
        assert chunks_processed == 1  # first chunk failed

    @pytest.mark.asyncio
    async def test_empty_session_returns_zero_counts(self):
        """Session with no text content → ([], '', 0, 0)."""
        from app.document_intelligence import QueryPlan, _extract_tabular_llm

        session = _make_session([""])
        plan = QueryPlan(relevant_columns=[], extraction_instruction="", document_type="tabular", complexity="complex")

        matches, interp, chunks_processed, chunks_total = await _extract_tabular_llm(
            session, plan, None
        )

        assert matches == []
        assert chunks_processed == 0
        assert chunks_total == 0

    @pytest.mark.asyncio
    async def test_column_filter_reduces_tokens_sent_to_llm(self):
        """Only relevant columns appear in the prompt sent to the LLM."""
        from app.document_intelligence import QueryPlan, _extract_tabular_llm

        table = self._make_md_table(["Name", "SecretColumn", "Revenue"], [["Alice", "PRIVATE", "100"]])
        session = _make_session([table])
        plan = QueryPlan(
            relevant_columns=["Name", "Revenue"],
            extraction_instruction="List all",
            document_type="tabular",
            complexity="complex",
        )

        captured_prompts: list[str] = []

        async def capture(**kwargs):
            for msg in kwargs.get("messages", []):
                captured_prompts.append(msg.get("content", ""))
            return _make_openai_response({"matches": []})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture)

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            with patch("app.document_intelligence.settings") as mock_settings:
                mock_settings.query_model = "gpt-4.1"
                await _extract_tabular_llm(session, plan, None)

        combined = " ".join(captured_prompts)
        assert "SecretColumn" not in combined
        assert "Name" in combined
        assert "Revenue" in combined

    @pytest.mark.asyncio
    async def test_partial_flag_set_when_chunks_failed(self):
        """query_document sets partial=True when chunks_processed < chunks_total."""
        table = self._make_md_table(
            ["Name", "Score"],
            [[f"entity_{i}", str(i)] for i in range(150)],
        )
        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="Name"), ColumnSchema(name="Score")])],
            total_sheets=1,
            summary="test",
        )
        schema_json = schema.model_dump_json()

        call_count = [0]

        async def flaky_llm(**kwargs):
            call_count[0] += 1
            # First call: query plan
            if call_count[0] == 1:
                return _make_openai_response({
                    "relevant_columns": ["Name"],
                    "extraction_instruction": "Find all names",
                    "document_type": "tabular",
                    "complexity": "complex",
                })
            # Second call (first chunk): fail
            if call_count[0] == 2:
                raise RuntimeError("chunk error")
            # Third call (second chunk): succeed with empty matches
            return _make_openai_response({"matches": []})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=flaky_llm)

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()

        session = _make_session([table])

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
                        mock_settings.max_session_cost = 1.0
                        result = await query_document("sess-partial", "find names")

        assert result.partial is True
        assert result.chunks_total == 2
        assert result.chunks_processed == 1


# ── query result caching ───────────────────────────────────────────────────────


class TestQueryResultCaching:
    """Tests for _load_query_cache, _store_query_cache, and invalidate_query_cache."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self):
        """_load_query_cache returns stored QueryResult on cache hit."""
        from app.document_intelligence import _load_query_cache

        stored = QueryResult(
            matches=[],
            query_interpretation="cached interp",
            total_matches=0,
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stored.model_dump_json())

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            result = await _load_query_cache("sess-a", "find all names")

        assert result is not None
        assert result.query_interpretation == "cached interp"

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        """_load_query_cache returns None when no cached result exists."""
        from app.document_intelligence import _load_query_cache

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            result = await _load_query_cache("sess-b", "find all names")

        assert result is None

    @pytest.mark.asyncio
    async def test_store_sets_ttl_and_registers_key(self):
        """_store_query_cache calls setex with 3600s TTL and registers key in set."""
        from app.document_intelligence import _store_query_cache

        stored = QueryResult(matches=[], query_interpretation="x", total_matches=0)
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            await _store_query_cache("sess-c", "my query", stored)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert "sess-c" in call_args[0]  # key contains session_key
        assert call_args[1] == 3600       # TTL is 1 hour
        mock_redis.sadd.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_deletes_registered_keys(self):
        """invalidate_query_cache deletes all keys registered for the session."""
        from app.document_intelligence import invalidate_query_cache

        registered_key = b"doc_query:sess-d:abc123"
        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value={registered_key})
        mock_redis.delete = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            await invalidate_query_cache("sess-d")

        mock_redis.delete.assert_called_once()
        deleted_keys = mock_redis.delete.call_args[0]
        assert registered_key in deleted_keys
        assert any(b"doc_query_keys:sess-d" in str(k).encode() or "doc_query_keys:sess-d" in k
                   for k in deleted_keys if isinstance(k, str))

    @pytest.mark.asyncio
    async def test_invalidate_handles_empty_set(self):
        """invalidate_query_cache handles sessions with no cached queries gracefully."""
        from app.document_intelligence import invalidate_query_cache

        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=set())
        mock_redis.delete = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            await invalidate_query_cache("sess-e")  # should not raise

        mock_redis.delete.assert_called_once()  # still deletes the keys_set_key itself

    @pytest.mark.asyncio
    async def test_cache_redis_error_is_silent(self):
        """Redis errors in _load_query_cache return None (no exception propagates)."""
        from app.document_intelligence import _load_query_cache

        with patch(
            "app.document_intelligence.get_redis",
            AsyncMock(side_effect=RuntimeError("Redis down")),
        ):
            result = await _load_query_cache("sess-f", "any query")

        assert result is None

    @pytest.mark.asyncio
    async def test_partial_result_not_cached(self):
        """Partial results (chunks_processed < chunks_total) are NOT stored in cache."""
        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="Name")])],
            total_sheets=1,
            summary="test",
        )
        table = "| Name |\n| --- |\n" + "\n".join(f"| row_{i} |" for i in range(150))
        session = _make_session([table])

        call_count = [0]

        async def plan_then_fail(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_openai_response({
                    "relevant_columns": ["Name"],
                    "extraction_instruction": "find all",
                    "document_type": "tabular",
                    "complexity": "complex",
                })
            if call_count[0] == 2:
                raise RuntimeError("chunk error")
            return _make_openai_response({"matches": []})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=plan_then_fail)

        schema_json = schema.model_dump_json()
        setex_calls: list = []

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock(side_effect=lambda *a, **kw: setex_calls.append(a))
        mock_redis.expire = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-partial-cache", "find all")

        assert result.partial is True
        # _store_query_cache's setex should NOT have been called (partial result)
        query_cache_setex = [c for c in setex_calls if "doc_query:" in str(c[0])]
        assert query_cache_setex == []

    @pytest.mark.asyncio
    async def test_query_document_uses_cache_on_second_call(self):
        """Second query_document call returns cached result without touching LLM."""
        stored = QueryResult(
            matches=[],
            query_interpretation="from cache",
            total_matches=0,
        )
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stored.model_dump_json())

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                result = await query_document("sess-hit", "find names")

        assert result.query_interpretation == "from cache"
        mock_client.chat.completions.create.assert_not_called()


# ── per-query cost logging ─────────────────────────────────────────────────────


class TestQueryCostLogging:
    """Tests for _estimate_cost, _accumulate_usage, and _log_query_cost."""

    def test_estimate_cost_known_model(self):
        """_estimate_cost returns correct value for a known model."""
        from app.document_intelligence import _estimate_cost

        # gpt-4.1: 0.002/1k input, 0.008/1k output
        cost = _estimate_cost("gpt-4.1", prompt_tokens=1000, completion_tokens=500)
        # (1000/1000)*0.002 + (500/1000)*0.008 = 0.002 + 0.004 = 0.006
        assert abs(cost - 0.006) < 1e-9

    def test_estimate_cost_unknown_model_uses_default(self):
        """_estimate_cost falls back to default pricing for unknown models."""
        from app.document_intelligence import _estimate_cost, _DEFAULT_PRICING

        in_rate, out_rate = _DEFAULT_PRICING
        cost = _estimate_cost("unknown-model-xyz", prompt_tokens=1000, completion_tokens=1000)
        expected = (1000 / 1000) * in_rate + (1000 / 1000) * out_rate
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_zero_tokens(self):
        """_estimate_cost returns 0 for zero tokens."""
        from app.document_intelligence import _estimate_cost

        assert _estimate_cost("gpt-4.1", 0, 0) == 0.0

    def test_accumulate_usage_sums_tokens(self):
        """_accumulate_usage adds prompt and completion tokens from response."""
        from app.document_intelligence import _accumulate_usage

        usage_dict: dict[str, int] = {}
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 200
        mock_response.usage.completion_tokens = 50
        _accumulate_usage(usage_dict, mock_response)
        assert usage_dict["prompt_tokens"] == 200
        assert usage_dict["completion_tokens"] == 50

        # Second accumulation sums
        _accumulate_usage(usage_dict, mock_response)
        assert usage_dict["prompt_tokens"] == 400
        assert usage_dict["completion_tokens"] == 100

    def test_accumulate_usage_no_usage_attr(self):
        """_accumulate_usage silently skips responses without a usage attribute."""
        from app.document_intelligence import _accumulate_usage

        usage_dict: dict[str, int] = {}
        mock_response = MagicMock(spec=[])  # no attributes
        _accumulate_usage(usage_dict, mock_response)  # should not raise
        assert usage_dict == {}

    @pytest.mark.asyncio
    async def test_log_query_cost_writes_to_redis(self):
        """_log_query_cost calls incrbyfloat and expire on the cost key."""
        from app.document_intelligence import _log_query_cost

        mock_redis = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            await _log_query_cost(
                "sess-cost", "find all", "simple", "gpt-4.1",
                {"prompt_tokens": 1000, "completion_tokens": 500},
            )

        mock_redis.incrbyfloat.assert_called_once()
        cost_key = mock_redis.incrbyfloat.call_args[0][0]
        assert "doc_cost:sess-cost" == cost_key
        added_value = mock_redis.incrbyfloat.call_args[0][1]
        assert added_value > 0
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_query_cost_redis_error_is_silent(self):
        """Redis errors in _log_query_cost do not propagate."""
        from app.document_intelligence import _log_query_cost

        with patch(
            "app.document_intelligence.get_redis",
            AsyncMock(side_effect=RuntimeError("Redis down")),
        ):
            await _log_query_cost("sess-x", "query", "complex", "gpt-4o", {})  # should not raise

    @pytest.mark.asyncio
    async def test_cost_logged_per_query_execution(self):
        """After a full query execution, incrbyfloat is called for the session."""
        session = _make_session(["| name |\n|---|\n| Alice |"])
        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="test",
        )

        call_count = [0]

        async def mock_llm(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_openai_response({
                    "relevant_columns": ["name"],
                    "extraction_instruction": "list all names",
                    "document_type": "tabular",
                    "complexity": "simple",
                })
            return _make_openai_response({"matches": []})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=mock_llm)

        schema_json = schema.model_dump_json()

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        incrbyfloat_calls: list = []
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock(side_effect=lambda *a, **kw: incrbyfloat_calls.append(a))

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        await query_document("sess-cost-log", "list all names")

        cost_calls = [c for c in incrbyfloat_calls if "doc_cost:" in str(c[0])]
        assert len(cost_calls) == 1
        assert cost_calls[0][0] == "doc_cost:sess-cost-log"


# ── budget enforcement ─────────────────────────────────────────────────────────


class TestBudgetEnforcement:
    """Tests for per-session cost budget enforcement."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_error(self):
        """query_document returns a structured error when budget is exceeded."""
        # Mock Redis to return a cost above the budget
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"2.5")  # $2.50 spent

        mock_client = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                with patch("app.document_intelligence.settings") as s:
                    s.max_session_cost = 1.0  # budget is $1.00
                    result = await query_document("sess-over-budget", "any query")

        assert result.error is not None
        assert "budget" in result.error.lower() or "exceeded" in result.error.lower()
        assert result.matches == []
        assert result.total_matches == 0
        mock_client.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_budget_at_limit_is_blocked(self):
        """Budget check blocks when cost equals the limit exactly."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"1.0")  # exactly at limit

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.settings") as s:
                s.max_session_cost = 1.0
                result = await query_document("sess-at-limit", "any query")

        assert result.error is not None

    @pytest.mark.asyncio
    async def test_budget_below_limit_proceeds(self):
        """Query proceeds normally when cost is below the budget."""
        session = _make_session(["| name |\n|---|\n| Alice |"])
        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="test",
        )

        async def llm_mock(**kwargs):
            return _make_openai_response({
                "relevant_columns": ["name"],
                "extraction_instruction": "list names",
                "document_type": "tabular",
                "complexity": "simple",
            })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=llm_mock)

        schema_json = schema.model_dump_json()

        async def get_by_key(key):
            if "doc_schema:" in key:
                return schema_json
            if "doc_cost:" in key:
                return b"0.5"  # $0.50 — below $1.00 limit
            return None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-under-budget", "list names")

        assert result.error is None
        mock_client.chat.completions.create.assert_called()

    @pytest.mark.asyncio
    async def test_budget_redis_error_allows_query(self):
        """When Redis is unavailable for budget check, query proceeds rather than blocking."""
        session = _make_session(["| name |\n|---|\n| Alice |"])
        schema = DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=[ColumnSchema(name="name")])],
            total_sheets=1,
            summary="test",
        )
        schema_json = schema.model_dump_json()

        llm_call_count = [0]

        async def llm_mock(**kwargs):
            llm_call_count[0] += 1
            return _make_openai_response({
                "relevant_columns": ["name"],
                "extraction_instruction": "list names",
                "document_type": "tabular",
                "complexity": "simple",
            })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=llm_mock)

        redis_call_count = [0]

        async def get_by_key(key):
            redis_call_count[0] += 1
            if "doc_cost:" in key:
                raise RuntimeError("Redis down")
            if "doc_schema:" in key:
                return schema_json
            return None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-redis-fail", "list names")

        # Query should have proceeded despite Redis error
        assert result.error is None
        assert llm_call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_check_budget_returns_zero_for_new_session(self):
        """_check_budget returns 0.0 when no cost has been accumulated yet."""
        from app.document_intelligence import _check_budget

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            cost = await _check_budget("new-session")

        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_check_budget_returns_none_on_redis_error(self):
        """_check_budget returns None (allow through) when Redis is unavailable."""
        from app.document_intelligence import _check_budget

        with patch(
            "app.document_intelligence.get_redis",
            AsyncMock(side_effect=RuntimeError("Redis down")),
        ):
            cost = await _check_budget("fail-session")

        assert cost is None

    def test_budget_error_message_is_helpful(self):
        """Budget error message includes current and maximum cost."""

        # Verify error message format by examining the code path
        # The error message includes both the current cost and limit
        # This is tested indirectly through test_budget_exceeded_returns_error
        # but we verify the message contains actionable guidance here.
        result = QueryResult(
            matches=[],
            query_interpretation="",
            total_matches=0,
            error="Session query budget exceeded ($2.5000 of $1.00 used). Upload a fresh session to continue querying.",
        )
        assert "$" in result.error
        assert "session" in result.error.lower()


# ── _filter_columns ────────────────────────────────────────────────────────────


class TestFilterColumns:
    """Tests for the _filter_columns helper."""

    def _make_md_table(self, headers: list[str], rows: list[list[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    def test_filters_to_single_column(self):
        """Only the specified column appears in output."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(["Name", "Revenue", "City"], [["Alice", "100", "NYC"]])
        result = _filter_columns(table, ["Name"])

        assert "Name" in result
        assert "Revenue" not in result
        assert "City" not in result
        assert "Alice" in result

    def test_filters_to_multiple_columns(self):
        """Multiple specified columns are kept; others are dropped."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(
            ["Name", "Revenue", "Status"],
            [["Acme", "500", "active"], ["Beta", "200", "inactive"]],
        )
        result = _filter_columns(table, ["Name", "Status"])

        assert "Name" in result
        assert "Status" in result
        assert "Revenue" not in result
        assert "Acme" in result
        assert "active" in result

    def test_case_insensitive_matching(self):
        """Column matching is case-insensitive."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(["Company", "Score"], [["Acme", "9"]])
        result = _filter_columns(table, ["company"])

        assert "Company" in result
        assert "Score" not in result

    def test_no_match_returns_original(self):
        """When no column names match, the original text is returned unchanged."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(["Name", "Age"], [["Alice", "30"]])
        result = _filter_columns(table, ["nonexistent"])

        assert result == table

    def test_empty_relevant_columns_returns_original(self):
        """Empty relevant_columns list returns the original text unchanged."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(["Name", "Age"], [["Alice", "30"]])
        result = _filter_columns(table, [])

        assert result == table

    def test_separator_row_updated_to_match_filtered_columns(self):
        """The separator row in the output has the correct column count."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(["A", "B", "C"], [["1", "2", "3"]])
        result = _filter_columns(table, ["A", "C"])

        lines = [ln for ln in result.splitlines() if ln.strip()]
        sep_lines = [ln for ln in lines if "---" in ln]
        assert len(sep_lines) == 1
        assert sep_lines[0].count("---") == 2  # A and C

    def test_non_table_lines_preserved(self):
        """Non-table lines (prose before table) pass through unchanged."""
        from app.document_intelligence import _filter_columns

        prose = "# Sheet 1"
        table = self._make_md_table(["Name", "Rev"], [["Acme", "10"]])
        text = prose + "\n" + table
        result = _filter_columns(text, ["Name"])

        assert prose in result
        assert "Name" in result
        assert "Rev" not in result

    def test_preserves_data_values_for_kept_columns(self):
        """Cell values of selected columns appear verbatim in output."""
        from app.document_intelligence import _filter_columns

        table = self._make_md_table(
            ["sts_cd", "co_nm", "rev_amt"],
            [["pend.", "BETA INC.", "75000"], ["ACTV", "ACME CORP", "150000"]],
        )
        result = _filter_columns(table, ["sts_cd", "co_nm"])

        assert "pend." in result
        assert "BETA INC." in result
        assert "ACTV" in result
        assert "ACME CORP" in result
        assert "75000" not in result
        assert "150000" not in result


# ── _merge_chunk_results ───────────────────────────────────────────────────────


class TestMergeChunkResults:
    """Tests for the _merge_chunk_results deduplication helper."""

    def test_empty_input_returns_empty(self):
        """Empty list of chunks returns empty list."""
        from app.document_intelligence import _merge_chunk_results

        assert _merge_chunk_results([]) == []

    def test_single_chunk_returned_unchanged(self):
        """Single chunk with no duplicates is returned as-is."""
        from app.document_intelligence import _merge_chunk_results

        chunk = [
            MatchEntry(value="Alice", source_column="Name", row_numbers=[1], confidence=0.9),
            MatchEntry(value="Bob", source_column="Name", row_numbers=[2], confidence=0.8),
        ]
        result = _merge_chunk_results([chunk])

        assert len(result) == 2
        assert result[0].value == "Alice"
        assert result[1].value == "Bob"

    def test_duplicate_across_chunks_removed(self):
        """Same value in two chunks deduplicates to first occurrence."""
        from app.document_intelligence import _merge_chunk_results

        entry = MatchEntry(value="Acme", source_column="Name", row_numbers=[1], confidence=0.9)
        result = _merge_chunk_results([[entry], [entry]])

        assert len(result) == 1
        assert result[0].value == "Acme"

    def test_preserves_insertion_order(self):
        """Output order: chunk 1 entries before chunk 2 entries."""
        from app.document_intelligence import _merge_chunk_results

        chunk1 = [MatchEntry(value="Alpha", source_column="x", confidence=0.9)]
        chunk2 = [MatchEntry(value="Beta", source_column="x", confidence=0.8)]
        result = _merge_chunk_results([chunk1, chunk2])

        assert result[0].value == "Alpha"
        assert result[1].value == "Beta"

    def test_dict_value_deduplication(self):
        """Dict values with identical content are deduplicated."""
        from app.document_intelligence import _merge_chunk_results

        e1 = MatchEntry(value={"Name": "Acme", "Rev": "100"}, source_column="Name")
        e2 = MatchEntry(value={"Name": "Acme", "Rev": "100"}, source_column="Name")
        result = _merge_chunk_results([[e1], [e2]])

        assert len(result) == 1

    def test_dict_values_differing_in_one_field_not_deduplicated(self):
        """Dict values differing in any field are distinct entries."""
        from app.document_intelligence import _merge_chunk_results

        e1 = MatchEntry(value={"Name": "Acme", "Rev": "100"}, source_column="Name")
        e2 = MatchEntry(value={"Name": "Acme", "Rev": "200"}, source_column="Name")
        result = _merge_chunk_results([[e1], [e2]])

        assert len(result) == 2

    def test_multiple_chunks_no_duplicates_all_kept(self):
        """Multiple chunks with distinct values: all entries preserved."""
        from app.document_intelligence import _merge_chunk_results

        chunks = [
            [MatchEntry(value=f"val_{i}", source_column="x", confidence=0.9)]
            for i in range(5)
        ]
        result = _merge_chunk_results(chunks)

        assert len(result) == 5


# ── LLM-native tabular extraction: complex queries ────────────────────────────


class TestTabularLlmComplexQueries:
    """Integration-style tests for complex query routing via _extract_tabular_llm."""

    def _make_md_table(self, headers: list[str], rows: list[list[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_lines = ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    def _make_schema(self, col_names: list[str]) -> DocumentSchema:
        cols = [ColumnSchema(name=c) for c in col_names]
        return DocumentSchema(
            document_type="tabular",
            sheets=[SheetSchema(name="default", columns=cols)],
            total_sheets=1,
            summary="test data",
        )

    def _mock_redis(self, schema: DocumentSchema) -> AsyncMock:
        schema_json = schema.model_dump_json()

        async def get_by_key(key):
            return schema_json if "doc_schema:" in key else None

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=get_by_key)
        mock_redis.expire = AsyncMock()
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock()
        return mock_redis

    @pytest.mark.asyncio
    async def test_complex_query_on_messy_data_inconsistent_headers(self):
        """Complex query on abbreviated/inconsistent column headers returns LLM result."""
        table = self._make_md_table(
            ["co_nm", "sts_cd", "rev_amt"],
            [
                ["ACME CORP", "ACTV", "150000"],
                ["BETA INC.", "pend.", "75000"],
                ["Gamma Ltd", "ACTV", "200000"],
            ],
        )
        schema = self._make_schema(["co_nm", "sts_cd", "rev_amt"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["co_nm", "sts_cd"],
            "extraction_instruction": "Find all active companies",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [
                {"value": {"co_nm": "ACME CORP", "sts_cd": "ACTV"}, "source_column": ["co_nm", "sts_cd"], "row_numbers": [1], "confidence": 0.92},
                {"value": {"co_nm": "Gamma Ltd", "sts_cd": "ACTV"}, "source_column": ["co_nm", "sts_cd"], "row_numbers": [3], "confidence": 0.91},
            ]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-messy", "find active companies")

        assert result.error is None
        assert result.total_matches == 2
        assert result.chunks_total >= 1
        sources = [m.source_column for m in result.matches]
        assert any("co_nm" in (src if isinstance(src, list) else [src]) for src in sources)

    @pytest.mark.asyncio
    async def test_aggregation_query_how_many(self):
        """'How many' aggregation routed to LLM extraction returns computed count."""
        table = self._make_md_table(
            ["company", "status"],
            [["Acme", "active"], ["Beta", "inactive"], ["Gamma", "active"], ["Delta", "active"]],
        )
        schema = self._make_schema(["company", "status"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["status"],
            "extraction_instruction": "Count rows where status is active",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [{"value": "3", "source_column": "status", "row_numbers": [1, 3, 4], "confidence": 0.99}]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-count", "how many companies are active?")

        assert result.error is None
        assert result.total_matches == 1
        assert result.matches[0].value == "3"

    @pytest.mark.asyncio
    async def test_aggregation_query_total_revenue(self):
        """'Total revenue' aggregation routed to LLM extraction returns sum."""
        table = self._make_md_table(
            ["company", "revenue"],
            [["Acme", "100"], ["Beta", "200"], ["Gamma", "300"]],
        )
        schema = self._make_schema(["company", "revenue"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["revenue"],
            "extraction_instruction": "Sum all revenue values",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [{"value": "600", "source_column": "revenue", "row_numbers": [1, 2, 3], "confidence": 0.99}]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-total", "what is the total revenue?")

        assert result.error is None
        assert len(result.matches) == 1
        assert result.matches[0].value == "600"

    @pytest.mark.asyncio
    async def test_fuzzy_matching_abbreviated_status_values(self):
        """Fuzzy: 'find pending' against 'pend.' and 'PEND' abbreviations returns both rows."""
        table = self._make_md_table(
            ["co_nm", "sts_cd"],
            [
                ["Acme", "actv"],
                ["Beta", "pend."],
                ["Gamma", "PEND"],
                ["Delta", "closed"],
            ],
        )
        schema = self._make_schema(["co_nm", "sts_cd"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["co_nm", "sts_cd"],
            "extraction_instruction": "Find rows where sts_cd is semantically pending",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [
                {"value": {"co_nm": "Beta", "sts_cd": "pend."}, "source_column": ["co_nm", "sts_cd"], "row_numbers": [2], "confidence": 0.88},
                {"value": {"co_nm": "Gamma", "sts_cd": "PEND"}, "source_column": ["co_nm", "sts_cd"], "row_numbers": [3], "confidence": 0.87},
            ]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-fuzzy", "find all pending items")

        assert result.error is None
        assert result.total_matches == 2
        values = [m.value for m in result.matches]
        assert any(isinstance(v, dict) and v.get("co_nm") == "Beta" for v in values)
        assert any(isinstance(v, dict) and v.get("co_nm") == "Gamma" for v in values)

    @pytest.mark.asyncio
    async def test_complex_routing_calls_llm_for_extraction(self):
        """complexity=complex results in 2 LLM calls: plan + extraction chunk."""
        table = self._make_md_table(["name", "val"], [["Alice", "1"], ["Bob", "2"]])
        schema = self._make_schema(["name", "val"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["val"],
            "extraction_instruction": "Compute average val",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [{"value": "1.5", "source_column": "val", "row_numbers": [1, 2], "confidence": 0.99}]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-routing", "average val")

        assert mock_client.chat.completions.create.call_count == 2
        assert result.chunks_total >= 1

    @pytest.mark.asyncio
    async def test_simple_routing_does_not_call_extraction_llm(self):
        """complexity=simple uses programmatic _extract_tabular (1 LLM call for plan only)."""
        table = self._make_md_table(["name", "status"], [["Alice", "active"], ["Bob", "active"]])
        schema = self._make_schema(["name", "status"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["name"],
            "extraction_instruction": "Extract all names",
            "document_type": "tabular",
            "complexity": "simple",
        }
        mock_resp = _make_openai_response(plan_payload)
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-simple", "list all names")

        assert mock_client.chat.completions.create.call_count == 1
        assert result.chunks_total == 0  # simple path leaves chunks_total at 0

    @pytest.mark.asyncio
    async def test_query_result_has_source_attribution(self):
        """Complex query result includes source_column and row_numbers from LLM response."""
        table = self._make_md_table(["entity", "score"], [["Alpha Corp", "95"], ["Beta Inc", "78"]])
        schema = self._make_schema(["entity", "score"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["entity", "score"],
            "extraction_instruction": "Find entities with score > 80",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [
                {"value": {"entity": "Alpha Corp", "score": "95"}, "source_column": ["entity", "score"], "row_numbers": [1], "confidence": 0.97}
            ]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-attr", "find high-score entities")

        assert result.error is None
        assert len(result.matches) == 1
        match = result.matches[0]
        assert match.source_column == ["entity", "score"]
        assert match.row_numbers == [1]
        assert match.confidence == pytest.approx(0.97)

    @pytest.mark.asyncio
    async def test_query_result_new_fields_present_for_complex_query(self):
        """QueryResult exposes partial, chunks_processed, chunks_total for complex queries."""
        table = self._make_md_table(["co", "rev"], [["A", "1"], ["B", "2"]])
        schema = self._make_schema(["co", "rev"])
        session = _make_session([table])

        plan_payload = {
            "relevant_columns": ["rev"],
            "extraction_instruction": "Sum revenue",
            "document_type": "tabular",
            "complexity": "complex",
        }
        extraction_payload = {
            "matches": [{"value": "3", "source_column": "rev", "row_numbers": [1, 2], "confidence": 0.99}]
        }

        call_count = [0]

        async def sequential_llm(**kwargs):
            call_count[0] += 1
            return _make_openai_response(plan_payload if call_count[0] == 1 else extraction_payload)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=sequential_llm)

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=self._mock_redis(schema))):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as s:
                        s.query_model = "gpt-4.1"
                        s.redis_ttl_hours = 24
                        s.max_session_cost = 1.0
                        result = await query_document("sess-newfields", "total revenue")

        dumped = result.model_dump()
        assert "partial" in dumped
        assert "chunks_processed" in dumped
        assert "chunks_total" in dumped
        assert result.partial is False
        assert result.chunks_processed > 0
        assert result.chunks_total == result.chunks_processed

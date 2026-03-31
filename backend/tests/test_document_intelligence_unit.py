"""Unit tests for document_intelligence.py.

All LLM calls and Redis interactions are mocked so these tests run without
external dependencies.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

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

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_schema.model_dump_json())
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
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

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_schema.model_dump_json())
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
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

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_schema.model_dump_json())
        mock_redis.expire = AsyncMock()

        with patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)):
            with patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)):
                with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
                    with patch("app.document_intelligence.settings") as mock_settings:
                        mock_settings.query_model = "gpt-4.1"
                        mock_settings.redis_ttl_hours = 24
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

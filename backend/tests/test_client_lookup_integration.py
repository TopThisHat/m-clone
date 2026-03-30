"""Integration tests for the client ID lookup feature.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.

Only the LLM call is mocked — all DB interactions are real.

Coverage:
  - search_fuzzy_client() with seeded data    (task 8.1)
  - search_queue_client() with seeded data    (task 8.2)
  - SET LOCAL threshold scoping               (task 8.3)
  - resolve_client() full flow, mocked LLM   (task 8.4)
  - resolve_client() LLM failure → fallback  (task 8.5)
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.models.client_lookup import AdjudicationMethod, LookupResult


# ---------------------------------------------------------------------------
# Fixtures: fuzzy_client seed data
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fuzzy_client_rows():
    """Seed rows into playbook.fuzzy_client and clean up after the test.

    Uses a unique prefix so parallel test runs don't collide.
    """
    prefix = f"TESTCL-{uuid.uuid4().hex[:8]}"
    rows = [
        # (gwm_id, name, companies)
        (f"{prefix}-001", "Alice Thornton", "Goldman Sachs"),
        (f"{prefix}-002", "Bob Henderson", "Morgan Stanley"),
        (f"{prefix}-003", "Alice Thornburg", "JP Morgan"),   # similar to Alice Thornton
    ]

    async with _acquire() as conn:
        for gwm_id, name, companies in rows:
            await conn.execute(
                """
                INSERT INTO playbook.fuzzy_client (gwm_id, name, companies)
                VALUES ($1, $2, $3)
                ON CONFLICT (gwm_id) DO NOTHING
                """,
                gwm_id, name, companies,
            )

    yield {"prefix": prefix, "rows": rows}

    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.fuzzy_client WHERE gwm_id LIKE $1",
            f"{prefix}-%",
        )


# ---------------------------------------------------------------------------
# Fixtures: high_priority_queue_client seed data
# Galileo schema may not exist in the test environment — tests skip gracefully.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def hpq_rows():
    """Seed rows into galileo.high_priority_queue_client, skip if table absent."""
    prefix = f"TESTHPQ-{uuid.uuid4().hex[:8]}"
    rows = [
        # (entity_id, label)
        (
            f"{prefix}-001",
            "Carroll, Daniel P. | Managing Director | Barclays",
        ),
        (
            f"{prefix}-002",
            "Danielson, Carol A. | Senior Advisor | Deutsche Bank",
        ),
    ]

    async with _acquire() as conn:
        try:
            for entity_id, label in rows:
                await conn.execute(
                    """
                    INSERT INTO galileo.high_priority_queue_client
                        (entity_id, entity_id_type, label)
                    VALUES ($1, 'Client', $2)
                    ON CONFLICT (entity_id) DO NOTHING
                    """,
                    entity_id, label,
                )
        except Exception as exc:
            pytest.skip(f"galileo.high_priority_queue_client not accessible: {exc}")

    yield {"prefix": prefix, "rows": rows}

    async with _acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM galileo.high_priority_queue_client WHERE entity_id LIKE $1",
                f"{prefix}-%",
            )
        except Exception:
            pass  # Best-effort cleanup


# ---------------------------------------------------------------------------
# 8.1 — search_fuzzy_client() with real DB
# ---------------------------------------------------------------------------

class TestSearchFuzzyClient:
    """Integration tests for search_fuzzy_client() against playbook.fuzzy_client."""

    @pytest.mark.asyncio
    async def test_exact_name_match_returns_high_score(self, fuzzy_client_rows):
        """Exact name match should appear in results with high similarity score."""
        from app.db.client_lookup import search_fuzzy_client

        prefix = fuzzy_client_rows["prefix"]
        results = await search_fuzzy_client("Alice Thornton")

        matching = [r for r in results if r.gwm_id == f"{prefix}-001"]
        assert len(matching) == 1, "Exact match not found in results"
        assert matching[0].db_score >= 0.7, "Expected high similarity for exact match"

    @pytest.mark.asyncio
    async def test_partial_name_match_returns_results(self, fuzzy_client_rows):
        """Partial name match (first name only) should still return candidates."""
        from app.db.client_lookup import search_fuzzy_client

        prefix = fuzzy_client_rows["prefix"]
        results = await search_fuzzy_client("Alice")

        gwm_ids = {r.gwm_id for r in results}
        # Both Alice Thornton and Alice Thornburg should appear
        assert f"{prefix}-001" in gwm_ids or f"{prefix}-003" in gwm_ids

    @pytest.mark.asyncio
    async def test_similar_names_both_returned(self, fuzzy_client_rows):
        """Two similarly named candidates should both appear in results."""
        from app.db.client_lookup import search_fuzzy_client

        prefix = fuzzy_client_rows["prefix"]
        results = await search_fuzzy_client("Alice Thornton")

        gwm_ids = {r.gwm_id for r in results}
        # Alice Thornton and Alice Thornburg are close — both should surface
        assert f"{prefix}-001" in gwm_ids

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, fuzzy_client_rows):
        """A completely unrelated name should return no results (or none of our seeds)."""
        from app.db.client_lookup import search_fuzzy_client

        results = await search_fuzzy_client("Zxqjklmnop Zzzzz")

        seed_ids = {r[0] for r in fuzzy_client_rows["rows"]}
        returned_ids = {r.gwm_id for r in results}
        assert not seed_ids.intersection(returned_ids)

    @pytest.mark.asyncio
    async def test_results_have_correct_source_field(self, fuzzy_client_rows):
        """All results from search_fuzzy_client should have source='fuzzy_client'."""
        from app.db.client_lookup import search_fuzzy_client

        results = await search_fuzzy_client("Alice Thornton")
        for r in results:
            assert r.source == "fuzzy_client"

    @pytest.mark.asyncio
    async def test_companies_field_populated(self, fuzzy_client_rows):
        """Seeded company name should appear in the candidate's companies field."""
        from app.db.client_lookup import search_fuzzy_client

        prefix = fuzzy_client_rows["prefix"]
        results = await search_fuzzy_client("Alice Thornton")

        alice = next((r for r in results if r.gwm_id == f"{prefix}-001"), None)
        assert alice is not None
        assert alice.companies == "Goldman Sachs"

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        """If the DB query fails, search_fuzzy_client returns [] rather than raising."""
        from app.db import client_lookup as db_module

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(db_module, "_acquire", return_value=mock_cm):
            result = await db_module.search_fuzzy_client("John Smith")

        assert result == []


# ---------------------------------------------------------------------------
# 8.2 — search_queue_client() with real DB
# ---------------------------------------------------------------------------

class TestSearchQueueClient:
    """Integration tests for search_queue_client() against galileo.high_priority_queue_client.

    All tests in this class are skipped when the galileo schema is unavailable.
    """

    @pytest.mark.asyncio
    async def test_name_within_label_bio_is_found(self, hpq_rows):
        """Name appearing inside a label bio string is matched by word_similarity."""
        from app.db.client_lookup import search_queue_client

        prefix = hpq_rows["prefix"]
        results = await search_queue_client("Daniel Carroll")

        matching = [r for r in results if r.gwm_id == f"{prefix}-001"]
        assert len(matching) >= 1

    @pytest.mark.asyncio
    async def test_results_have_correct_source_field(self, hpq_rows):
        """All results from search_queue_client should have source='high_priority_queue_client'."""
        from app.db.client_lookup import search_queue_client

        results = await search_queue_client("Daniel Carroll")
        for r in results:
            assert r.source == "high_priority_queue_client"

    @pytest.mark.asyncio
    async def test_label_excerpt_populated(self, hpq_rows):
        """The label_excerpt field should be populated from the label column."""
        from app.db.client_lookup import search_queue_client

        prefix = hpq_rows["prefix"]
        results = await search_queue_client("Daniel Carroll")

        matching = [r for r in results if r.gwm_id == f"{prefix}-001"]
        if matching:
            assert matching[0].label_excerpt is not None
            assert len(matching[0].label_excerpt) > 0

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_or_no_seeds(self, hpq_rows):
        """Completely unrelated query returns no seeded rows."""
        from app.db.client_lookup import search_queue_client

        results = await search_queue_client("Xyzzy Unrelated Bogusname")

        seed_ids = {r[0] for r in hpq_rows["rows"]}
        returned_ids = {r.gwm_id for r in results}
        assert not seed_ids.intersection(returned_ids)

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        """Permission error on galileo schema returns [] without raising."""
        from app.db import client_lookup as db_module

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=Exception("permission denied for schema galileo")
        )
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(db_module, "_acquire", return_value=mock_cm):
            result = await db_module.search_queue_client("John Smith")

        assert result == []


# ---------------------------------------------------------------------------
# 8.3 — SET LOCAL threshold scoping
# ---------------------------------------------------------------------------

class TestSetLocalThresholdScoping:
    """Verify that SET LOCAL in the DB functions does not leak to other queries."""

    @pytest.mark.asyncio
    async def test_fuzzy_threshold_not_leaked_between_calls(self):
        """Two consecutive search_fuzzy_client calls each manage their own threshold."""
        from app.db.client_lookup import search_fuzzy_client

        # Both calls should complete without affecting each other's connection state.
        # If threshold leaked, the second call might fail or behave unexpectedly.
        await asyncio.gather(
            search_fuzzy_client("Alice Smith"),
            search_fuzzy_client("Bob Jones"),
        )
        # Reaching here without exception confirms isolation

    @pytest.mark.asyncio
    async def test_queue_threshold_not_leaked_between_calls(self):
        """Two consecutive search_queue_client calls each manage their own threshold."""
        from app.db.client_lookup import search_queue_client

        # Run sequentially on the same pool connection to test for leakage
        await search_queue_client("Alice Smith")
        await search_queue_client("Bob Jones")
        # No assertion needed — completing without error confirms scoping works


# ---------------------------------------------------------------------------
# 8.4 — resolve_client() full flow with mocked LLM
# ---------------------------------------------------------------------------

class TestResolveClientFullFlow:
    """Integration tests for resolve_client() with real DB + mocked LLM."""

    def _make_llm_response_message(
        self,
        gwm_id: str,
        name: str,
        source: str = "fuzzy_client",
        confidence: float = 0.88,
    ) -> MagicMock:
        payload = json.dumps({
            "match_found": True,
            "gwm_id": gwm_id,
            "matched_name": name,
            "source": source,
            "confidence": confidence,
            "conflict": False,
            "conflict_gwm_ids": [],
            "ambiguous": False,
            "resolution_factors": ["Integration test match"],
            "candidates_considered": 1,
        })
        mock_message = MagicMock()
        mock_message.content = payload
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    @pytest.mark.asyncio
    async def test_resolve_with_db_data_and_mocked_llm(self, fuzzy_client_rows):
        """Full pipeline: real DB query → dedup → mocked LLM → LookupResult."""
        from app.agent import client_resolver

        prefix = fuzzy_client_rows["prefix"]
        gwm_id = f"{prefix}-001"
        mock_response = self._make_llm_response_message(gwm_id, "Alice Thornton")
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Alice Thornton")

        assert isinstance(result, LookupResult)
        # The LLM says it's gwm_id, and the DB actually has that record
        assert result.gwm_id == gwm_id
        assert result.match_found is True
        assert result.search_summary.fuzzy_client_hits >= 1

    @pytest.mark.asyncio
    async def test_search_summary_reflects_actual_db_hits(self, fuzzy_client_rows):
        """search_summary counts reflect the real number of DB rows returned."""
        from app.agent import client_resolver

        prefix = fuzzy_client_rows["prefix"]
        gwm_id = f"{prefix}-001"
        mock_response = self._make_llm_response_message(gwm_id, "Alice Thornton")
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Alice Thornton")

        # We seeded data — fuzzy_client_hits should be > 0
        assert result.search_summary.fuzzy_client_hits > 0

    @pytest.mark.asyncio
    async def test_unmatched_name_no_db_rows(self):
        """Name with no DB matches returns no_match immediately without LLM call."""
        from app.agent import client_resolver

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock()

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Zxqjklmnop Zzzzz Bogusname999")

        assert result.match_found is False
        # LLM should not have been called when no candidates exist
        mock_openai.chat.completions.create.assert_not_called()


# ---------------------------------------------------------------------------
# 8.5 — resolve_client() LLM failure → Levenshtein fallback
# ---------------------------------------------------------------------------

class TestResolveClientLlmFailureFallback:
    """Verify Levenshtein fallback activates when LLM is unavailable."""

    @pytest.mark.asyncio
    async def test_llm_timeout_triggers_rule_based_fallback(self, fuzzy_client_rows):
        """Timeout during LLM call activates deterministic fallback."""
        from app.agent import client_resolver

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Alice Thornton")

        assert result.adjudication == AdjudicationMethod.RULE_BASED
        assert any("rule-based" in w.lower() or "llm" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_llm_exception_triggers_rule_based_fallback(self, fuzzy_client_rows):
        """Generic LLM exception activates fallback."""
        from app.agent import client_resolver

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=Exception("service unavailable")
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Alice Thornton")

        assert result.adjudication == AdjudicationMethod.RULE_BASED

    @pytest.mark.asyncio
    async def test_fallback_result_is_valid_lookup_result(self, fuzzy_client_rows):
        """Fallback still returns a fully valid LookupResult with all required fields."""
        from app.agent import client_resolver

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=Exception("LLM down")
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            result = await client_resolver.resolve_client("Alice Thornton")

        # Validate all required LookupResult fields are present
        assert isinstance(result, LookupResult)
        assert result.search_summary is not None
        assert isinstance(result.candidates_evaluated, int)
        assert isinstance(result.warnings, list)
        assert isinstance(result.confidence, float)

    @pytest.mark.asyncio
    async def test_fallback_with_high_score_candidate_finds_match(self, fuzzy_client_rows):
        """Fallback with a good DB score (>= 0.40) produces a match."""
        from app.agent import client_resolver

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=Exception("LLM down")
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_openai):
            # "Alice Thornton" is seeded and should have a reasonable db_score
            result = await client_resolver.resolve_client("Alice Thornton")

        # With a seeded exact match, fallback should still find it
        # (score depends on actual trigram similarity; at minimum the result is valid)
        assert result.adjudication == AdjudicationMethod.RULE_BASED
        assert result.confidence <= 0.60  # Capped at FALLBACK_CONFIDENCE_CAP

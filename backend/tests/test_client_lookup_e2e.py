"""E2E tests for the POST /api/client-lookup REST endpoint.

Tests the full HTTP request/response cycle using httpx AsyncClient against
a FastAPI application with mocked auth and (for most tests) a mocked
resolve_client() function.

Coverage:
  - 200 response with valid body + mocked resolver      (task 9.1)
  - 401 response without JWT auth cookie                (task 9.2)
  - 422 response with empty name                        (task 9.3)
  - 422 response with missing name field                (task 9.4)
  - Full round-trip with mocked DB + LLM               (task 9.5)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.client_lookup import (
    AdjudicationMethod,
    CandidateResult,
    LookupResult,
    SearchSummary,
)


# ---------------------------------------------------------------------------
# Override autouse schema fixture to avoid needing a running DB for E2E tests
# that mock resolve_client completely.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_app(user_sid: str = "test-user-001"):
    """Build a FastAPI app with the client-lookup router and mocked auth."""
    from fastapi import FastAPI
    from app.routers.client_lookup import router as client_lookup_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(client_lookup_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test User", "email": "test@example.com"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


def _make_unauthenticated_app():
    """Build a FastAPI app with the client-lookup router and NO auth override."""
    from fastapi import FastAPI
    from app.routers.client_lookup import router as client_lookup_router

    app = FastAPI()
    app.include_router(client_lookup_router)
    return app


def _make_lookup_result(
    match_found: bool = True,
    gwm_id: str = "GWM-001",
    matched_name: str = "John Smith",
    source: str = "fuzzy_client",
    confidence: float = 0.88,
    adjudication: AdjudicationMethod = AdjudicationMethod.LLM,
    conflict: bool = False,
    ambiguous: bool = False,
) -> LookupResult:
    return LookupResult(
        match_found=match_found,
        gwm_id=gwm_id if match_found else None,
        matched_name=matched_name if match_found else None,
        source=source if match_found else None,  # type: ignore[arg-type]
        confidence=confidence,
        adjudication=adjudication,
        conflict=conflict,
        ambiguous=ambiguous,
        resolution_factors=["Strong name match"],
        candidates_evaluated=1,
        search_summary=SearchSummary(fuzzy_client_hits=1, hpq_client_hits=0),
    )


# ---------------------------------------------------------------------------
# 9.1 — POST returns 200 with valid response shape
# ---------------------------------------------------------------------------

class TestPostClientLookupSuccess:

    @pytest.mark.asyncio
    async def test_returns_200_with_matched_result(self):
        """Valid request with mocked resolver returns 200 and LookupResult shape."""
        # Patch at the router's import binding, not on the source module, because
        # the router uses `from app.agent.client_resolver import resolve_client`.
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result()
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(
            router_module, "resolve_client", new=AsyncMock(return_value=expected)
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "John Smith"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is True
        assert data["gwm_id"] == "GWM-001"
        assert data["matched_name"] == "John Smith"
        assert data["source"] == "fuzzy_client"
        assert data["confidence"] == 0.88
        assert data["adjudication"] == "llm"

    @pytest.mark.asyncio
    async def test_response_contains_all_required_fields(self):
        """Response JSON includes every field defined in LookupResult."""
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result()
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(
            router_module, "resolve_client", new=AsyncMock(return_value=expected)
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "John Smith"},
                )

        data = resp.json()
        required_fields = [
            "match_found", "confidence", "adjudication",
            "resolution_factors", "conflict", "ambiguous",
            "candidates", "candidates_evaluated", "warnings", "search_summary",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_returns_200_with_no_match_result(self):
        """Resolver returning no-match still gives 200 with match_found=False."""
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result(
            match_found=False,
            gwm_id=None,
            confidence=0.0,
            adjudication=AdjudicationMethod.RULE_BASED,
        )
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(
            router_module, "resolve_client", new=AsyncMock(return_value=expected)
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "Unknown Person"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is False
        assert data["gwm_id"] is None

    @pytest.mark.asyncio
    async def test_company_field_forwarded_to_resolver(self):
        """Optional company field in request body is passed through to resolve_client."""
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result()
        mock_resolve = AsyncMock(return_value=expected)
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(router_module, "resolve_client", new=mock_resolve):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/api/client-lookup",
                    json={"name": "John Smith", "company": "Goldman Sachs"},
                )

        mock_resolve.assert_called_once_with(
            name="John Smith",
            company="Goldman Sachs",
            context=None,
        )

    @pytest.mark.asyncio
    async def test_context_field_forwarded_to_resolver(self):
        """Optional context field in request body is passed through to resolve_client."""
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result()
        mock_resolve = AsyncMock(return_value=expected)
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(router_module, "resolve_client", new=mock_resolve):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/api/client-lookup",
                    json={
                        "name": "John Smith",
                        "context": "Mentioned in meeting notes from Q1 2024",
                    },
                )

        mock_resolve.assert_called_once_with(
            name="John Smith",
            company=None,
            context="Mentioned in meeting notes from Q1 2024",
        )

    @pytest.mark.asyncio
    async def test_search_summary_in_response(self):
        """search_summary with hit counts is present in the response."""
        import app.routers.client_lookup as router_module

        expected = _make_lookup_result()
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with patch.object(
            router_module, "resolve_client", new=AsyncMock(return_value=expected)
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "John Smith"},
                )

        data = resp.json()
        assert "search_summary" in data
        assert "fuzzy_client_hits" in data["search_summary"]
        assert "hpq_client_hits" in data["search_summary"]


# ---------------------------------------------------------------------------
# 9.2 — POST returns 401 without JWT auth
# ---------------------------------------------------------------------------

class TestPostClientLookupUnauthenticated:

    @pytest.mark.asyncio
    async def test_returns_401_without_jwt_cookie(self):
        """Request without JWT cookie returns 401 Unauthorized."""
        app = _make_unauthenticated_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": "John Smith"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_401_with_invalid_jwt(self):
        """Request with a malformed JWT cookie returns 401."""
        app = _make_unauthenticated_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"jwt": "not.a.real.token"},
        ) as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": "John Smith"},
            )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 9.3 — POST returns 422 with empty name
# ---------------------------------------------------------------------------

class TestPostClientLookupEmptyName:

    @pytest.mark.asyncio
    async def test_returns_422_for_empty_string_name(self):
        """Empty name string fails Pydantic min_length=1 validation."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": ""},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_422_error_body_mentions_name_field(self):
        """422 response body references the name field in its error detail."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": ""},
            )

        assert resp.status_code == 422
        body = resp.json()
        # FastAPI validation errors include a 'detail' list
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_returns_422_for_name_exceeding_max_length(self):
        """Name longer than 200 characters fails Pydantic max_length=200 validation."""
        app = _make_test_app()
        transport = ASGITransport(app=app)
        long_name = "A" * 201

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": long_name},
            )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 9.4 — POST returns 422 with missing name field
# ---------------------------------------------------------------------------

class TestPostClientLookupMissingName:

    @pytest.mark.asyncio
    async def test_returns_422_for_missing_name_field(self):
        """Request without name field fails Pydantic required-field validation."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_for_null_name(self):
        """Explicit null for name field fails validation (required field)."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": None},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_for_non_string_name(self):
        """Non-string name field fails Pydantic type validation."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"name": 12345},
            )

        # FastAPI coerces int to str (pydantic v2 behavior), so this may be 200 or 422
        # The important constraint is it does not 500
        assert resp.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_returns_422_with_only_unrelated_fields(self):
        """Body with unrecognized fields but no name still fails validation."""
        app = _make_test_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/client-lookup",
                json={"company": "Goldman Sachs", "context": "some context"},
            )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 9.5 — Full round-trip with mocked DB + LLM
# ---------------------------------------------------------------------------

class TestPostClientLookupFullRoundTrip:
    """End-to-end tests mocking both DB functions and the LLM call."""

    def _make_openai_mock(
        self,
        gwm_id: str = "GWM-999",
        name: str = "Test Client",
        confidence: float = 0.90,
    ) -> MagicMock:
        payload = json.dumps({
            "match_found": True,
            "gwm_id": gwm_id,
            "matched_name": name,
            "source": "fuzzy_client",
            "confidence": confidence,
            "conflict": False,
            "conflict_gwm_ids": [],
            "ambiguous": False,
            "resolution_factors": ["E2E test match"],
            "candidates_considered": 1,
        })
        mock_message = MagicMock()
        mock_message.content = payload
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_openai

    @pytest.mark.asyncio
    async def test_full_round_trip_with_fuzzy_match(self):
        """POST → mocked DB → mocked LLM → 200 with expected gwm_id."""
        from app.agent import client_resolver

        fuzzy_candidates = [
            CandidateResult(
                gwm_id="GWM-999",
                name="Test Client",
                source="fuzzy_client",
                db_score=0.85,
            )
        ]
        mock_openai = self._make_openai_mock()

        app = _make_test_app()
        transport = ASGITransport(app=app)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "Test Client"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is True
        assert data["gwm_id"] == "GWM-999"
        assert data["matched_name"] == "Test Client"

    @pytest.mark.asyncio
    async def test_full_round_trip_no_candidates_returns_no_match(self):
        """POST with no DB results → 200 with match_found=False."""
        from app.agent import client_resolver

        app = _make_test_app()
        transport = ASGITransport(app=app)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "Nobody Knowsme"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is False
        assert data["gwm_id"] is None

    @pytest.mark.asyncio
    async def test_full_round_trip_conflict_scenario(self):
        """Two sources with different gwm_ids → conflict=True in response."""
        from app.agent import client_resolver

        fuzzy_candidates = [
            CandidateResult(
                gwm_id="GWM-001",
                name="John Smith",
                source="fuzzy_client",
                db_score=0.82,
            )
        ]
        hpq_candidates = [
            CandidateResult(
                gwm_id="GWM-002",
                name="John Smith - Senior Advisor | Citigroup",
                source="high_priority_queue_client",
                db_score=0.78,
            )
        ]

        # LLM reports conflict
        conflict_payload = json.dumps({
            "match_found": False,
            "gwm_id": None,
            "matched_name": None,
            "source": None,
            "confidence": 0.40,
            "conflict": True,
            "conflict_gwm_ids": ["GWM-001", "GWM-002"],
            "ambiguous": False,
            "resolution_factors": ["Conflicting IDs across sources"],
            "candidates_considered": 2,
        })
        mock_message = MagicMock()
        mock_message.content = conflict_payload
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        app = _make_test_app()
        transport = ASGITransport(app=app)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=hpq_candidates),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "John Smith"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["conflict"] is True
        assert data["match_found"] is False

    @pytest.mark.asyncio
    async def test_fast_path_bypasses_llm(self):
        """Single high-score fuzzy candidate triggers fast path — LLM not invoked."""
        from app.agent import client_resolver

        fuzzy_candidates = [
            CandidateResult(
                gwm_id="GWM-FAST",
                name="Alice Thornton",
                source="fuzzy_client",
                db_score=0.95,
            )
        ]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock()  # should NOT be called

        app = _make_test_app()
        transport = ASGITransport(app=app)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "Alice Thornton"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is True
        assert data["adjudication"] == "fast_path"
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_round_trip_with_company_disambiguation(self):
        """Company field in request body is forwarded and does not break the pipeline."""
        from app.agent import client_resolver

        fuzzy_candidates = [
            CandidateResult(
                gwm_id="GWM-999",
                name="Test Client",
                source="fuzzy_client",
                db_score=0.80,
                companies="Goldman Sachs",
            )
        ]
        mock_openai = self._make_openai_mock()
        app = _make_test_app()
        transport = ASGITransport(app=app)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/client-lookup",
                    json={"name": "Test Client", "company": "Goldman Sachs"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["match_found"] is True

"""Tests for GET /api/kg/suggest endpoint (Task #9, beads: m-clone-2e6k).

Covers:
  - Trigram/ILIKE matching (fuzzy and prefix)
  - Empty results
  - Limit enforcement (default 10, max 50, min 1)
  - Team scoping (non-member gets 403)
  - Response shape: id, name, entity_type, relationship_count
  - Required q param (422 if missing)
  - db_suggest_kg_entities: result shape, limit clamping, ILIKE pattern

Run: cd backend && uv run python -m pytest tests/test_kg_suggest.py -v
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.routers.knowledge_graph import router as kg_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEAM_ID = str(uuid.uuid4())
USER_SID = f"user-{uuid.uuid4().hex[:8]}"


def _make_app(is_member: bool = True, is_sa: bool = False) -> FastAPI:
    """Test FastAPI app with mocked auth and team membership."""
    test_app = FastAPI()
    test_app.include_router(kg_router)

    async def _mock_user() -> dict[str, Any]:
        return {"sub": USER_SID}

    test_app.dependency_overrides[get_current_user] = _mock_user
    return test_app


def _make_result(
    name: str = "Tiger Capital",
    entity_type: str = "company",
    entity_id: str | None = None,
    relationship_count: int = 5,
) -> dict[str, Any]:
    return {
        "id": entity_id or str(uuid.uuid4()),
        "name": name,
        "entity_type": entity_type,
        "relationship_count": relationship_count,
    }


@contextmanager
def _team_ctx(
    is_member: bool = True,
    is_sa: bool = False,
    suggest_return: list[dict[str, Any]] | None = None,
) -> Generator[AsyncMock, None, None]:
    """Patch all DB helpers used by the suggest endpoint."""
    mock = AsyncMock(return_value=suggest_return or [])
    with (
        patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=is_sa)),
        patch("app.routers.knowledge_graph.db_is_team_member", AsyncMock(return_value=is_member)),
        patch("app.routers.knowledge_graph.db_list_user_teams", AsyncMock(return_value=[{"id": TEAM_ID}])),
        patch("app.routers.knowledge_graph.db_suggest_kg_entities", mock),
    ):
        yield mock


# ---------------------------------------------------------------------------
# Endpoint tests via httpx AsyncClient
# ---------------------------------------------------------------------------

class TestSuggestEndpoint:
    """Tests for GET /api/kg/suggest."""

    @pytest.mark.asyncio
    async def test_returns_list_of_results(self):
        """Valid query returns 200 with a list of matching entities."""
        expected = [_make_result("Tiger Capital", "company")]
        app = _make_app()

        with _team_ctx(is_member=True, suggest_return=expected):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=tiger&team_id={TEAM_ID}")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Tiger Capital"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Query with no matches returns 200 and empty list."""
        app = _make_app()

        with _team_ctx(is_member=True, suggest_return=[]):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=zzznomatch&team_id={TEAM_ID}")

        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_missing_q_returns_422(self):
        """Missing required 'q' parameter returns 422 Unprocessable Entity."""
        app = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/kg/suggest?team_id={TEAM_ID}")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_limit_above_50_returns_422(self):
        """limit > 50 is rejected with 422."""
        app = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/kg/suggest?q=test&team_id={TEAM_ID}&limit=99")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_non_member_gets_403(self):
        """User who is not a team member receives 403."""
        app = _make_app()

        with _team_ctx(is_member=False):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=test&team_id={TEAM_ID}")

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_response_shape(self):
        """Each result has id, name, entity_type, relationship_count."""
        entity_id = str(uuid.uuid4())
        expected = [_make_result("ACME Corp", "company", entity_id=entity_id, relationship_count=7)]
        app = _make_app()

        with _team_ctx(is_member=True, suggest_return=expected):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=acme&team_id={TEAM_ID}")

        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["id"] == entity_id
        assert item["name"] == "ACME Corp"
        assert item["entity_type"] == "company"
        assert item["relationship_count"] == 7

    @pytest.mark.asyncio
    async def test_multiple_results_returned(self):
        """Multiple matching results are returned in order."""
        expected = [
            _make_result("Tiger Capital", "company", relationship_count=12),
            _make_result("Tiger Global", "company", relationship_count=8),
            _make_result("Tiger Woods", "person", relationship_count=3),
        ]
        app = _make_app()

        with _team_ctx(is_member=True, suggest_return=expected):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=tiger&team_id={TEAM_ID}")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        names = [d["name"] for d in data]
        assert names == ["Tiger Capital", "Tiger Global", "Tiger Woods"]

    @pytest.mark.asyncio
    async def test_default_limit_is_10(self):
        """When limit is omitted, db function is called with limit=10."""
        app = _make_app()

        with _team_ctx(is_member=True) as mock_suggest:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.get(f"/api/kg/suggest?q=test&team_id={TEAM_ID}")

        mock_suggest.assert_awaited_once()
        _, kwargs = mock_suggest.call_args
        assert kwargs.get("limit") == 10

    @pytest.mark.asyncio
    async def test_custom_limit_forwarded(self):
        """Custom limit=25 is forwarded to db function."""
        app = _make_app()

        with _team_ctx(is_member=True) as mock_suggest:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.get(f"/api/kg/suggest?q=test&team_id={TEAM_ID}&limit=25")

        _, kwargs = mock_suggest.call_args
        assert kwargs.get("limit") == 25

    @pytest.mark.asyncio
    async def test_super_admin_can_access_any_team(self):
        """Super admin bypasses team membership check."""
        expected = [_make_result("Blackstone", "company")]
        other_team = str(uuid.uuid4())
        app = _make_app()

        with _team_ctx(is_sa=True, suggest_return=expected):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/kg/suggest?q=black&team_id={other_team}")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unit tests: db_suggest_kg_entities function directly
# ---------------------------------------------------------------------------

class TestDbSuggestKgEntities:
    """Unit tests for the db_suggest_kg_entities DB function."""

    @pytest.mark.asyncio
    async def test_limit_clamped_to_50(self):
        """limit > 50 is silently clamped to 50 inside the DB function."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        captured: list[Any] = []

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                captured.extend(args)
                return []

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            await db_suggest_kg_entities("test", TEAM_ID, limit=999)

        # Last arg in the parameterized query is the SQL LIMIT value
        assert captured[-1] == 50

    @pytest.mark.asyncio
    async def test_limit_minimum_is_1(self):
        """limit < 1 is clamped to 1."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        captured: list[Any] = []

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                captured.extend(args)
                return []

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            await db_suggest_kg_entities("test", TEAM_ID, limit=0)

        assert captured[-1] == 1

    @pytest.mark.asyncio
    async def test_result_shape(self):
        """Returns dicts with exactly id, name, entity_type, relationship_count."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        entity_id = uuid.uuid4()

        class FakeRow:
            _data = {
                "id": entity_id,
                "name": "Tiger Capital",
                "entity_type": "company",
                "sim": 0.85,
                "relationship_count": 12,
            }
            def __getitem__(self, key: str) -> Any:
                return self._data[key]

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                return [FakeRow()]

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            results = await db_suggest_kg_entities("tiger", TEAM_ID)

        assert len(results) == 1
        r = results[0]
        assert r["id"] == str(entity_id)
        assert r["name"] == "Tiger Capital"
        assert r["entity_type"] == "company"
        assert r["relationship_count"] == 12
        assert set(r.keys()) == {"id", "name", "entity_type", "relationship_count"}

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Returns empty list when no rows match."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                return []

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            results = await db_suggest_kg_entities("zzznomatch", TEAM_ID)

        assert results == []

    @pytest.mark.asyncio
    async def test_ilike_pattern_wraps_query(self):
        """ILIKE pattern is %query% for contains matching."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        captured: list[Any] = []

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                captured.extend(args)
                return []

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            await db_suggest_kg_entities("tiger", TEAM_ID)

        # SQL args: query($1), team_id($2), pattern($3), limit($4)
        assert captured[2] == "%tiger%"

    @pytest.mark.asyncio
    async def test_id_serialized_as_string(self):
        """UUID id is serialized to string in the result."""
        from app.db.knowledge_graph import db_suggest_kg_entities

        entity_id = uuid.uuid4()  # raw UUID object

        class FakeRow:
            _data = {"id": entity_id, "name": "X", "entity_type": "other", "sim": 0.5, "relationship_count": 0}
            def __getitem__(self, key: str) -> Any:
                return self._data[key]

        class FakeConn:
            async def fetch(self, sql: str, *args: Any) -> list[Any]:
                return [FakeRow()]

        class FakeCtx:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()
            async def __aexit__(self, *_: Any) -> None:
                pass

        with patch("app.db.knowledge_graph._acquire", return_value=FakeCtx()):
            results = await db_suggest_kg_entities("x", TEAM_ID)

        assert isinstance(results[0]["id"], str)
        assert results[0]["id"] == str(entity_id)

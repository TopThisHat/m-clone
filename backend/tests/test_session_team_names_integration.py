"""Integration tests for shared_team_names on session responses.

Requires a running PostgreSQL (docker compose up -d).
Run: cd backend && uv run pytest tests/test_session_team_names_integration.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db import (
    db_create_session,
    db_get_public_session,
    db_get_session,
    db_share_session_to_team,
    db_unshare_session,
    db_update_session,
)
from app.db._pool import _acquire
from app.db.teams import db_create_team, db_get_session_team_names


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner_sid():
    sid = f"test-owner-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "Owner User", f"{sid}@test.local",
        )
    yield sid
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def test_session(owner_sid):
    row = await db_create_session({
        "title": "Integration Test Session",
        "query": "test query",
        "report_markdown": "# Test Report",
        "message_history": [],
        "trace_steps": [],
        "owner_sid": owner_sid,
        "visibility": "private",
    })
    session_id = row["id"]
    yield session_id
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)


@pytest_asyncio.fixture
async def test_team(owner_sid):
    slug = f"test-team-{uuid.uuid4().hex[:8]}"
    team = await db_create_team(slug, f"Team {slug}", "A test team", owner_sid)
    yield team
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team["id"])


@pytest_asyncio.fixture
async def test_team_b(owner_sid):
    slug = f"test-team-b-{uuid.uuid4().hex[:8]}"
    team = await db_create_team(slug, f"Team B {slug}", "Another test team", owner_sid)
    yield team
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team["id"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDbGetSessionTeamNames:
    """Integration tests for db_get_session_team_names."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_unshared(self, test_session):
        """A session with no team shares returns an empty list."""
        names = await db_get_session_team_names(test_session)
        assert names == []

    @pytest.mark.asyncio
    async def test_returns_team_name_after_share(self, test_session, test_team):
        """After sharing with a team, its display_name is returned."""
        await db_share_session_to_team(test_session, test_team["id"])
        names = await db_get_session_team_names(test_session)
        assert test_team["display_name"] in names

    @pytest.mark.asyncio
    async def test_returns_all_team_names_when_shared_with_multiple(
        self, test_session, test_team, test_team_b
    ):
        """Sharing with multiple teams returns all display names."""
        await db_share_session_to_team(test_session, test_team["id"])
        await db_share_session_to_team(test_session, test_team_b["id"])
        names = await db_get_session_team_names(test_session)
        assert len(names) == 2
        assert test_team["display_name"] in names
        assert test_team_b["display_name"] in names

    @pytest.mark.asyncio
    async def test_name_removed_after_unshare(self, test_session, test_team):
        """After unsharing, the team name is no longer returned."""
        await db_share_session_to_team(test_session, test_team["id"])
        await db_unshare_session(test_session, test_team["id"])
        names = await db_get_session_team_names(test_session)
        assert test_team["display_name"] not in names
        assert names == []

    @pytest.mark.asyncio
    async def test_unshare_one_team_retains_other(
        self, test_session, test_team, test_team_b
    ):
        """Unsharing one team leaves the other team's name intact."""
        await db_share_session_to_team(test_session, test_team["id"])
        await db_share_session_to_team(test_session, test_team_b["id"])
        await db_unshare_session(test_session, test_team["id"])
        names = await db_get_session_team_names(test_session)
        assert test_team["display_name"] not in names
        assert test_team_b["display_name"] in names


class TestSessionDetailApiResponse:
    """Verify shared_team_names appears in the session detail db response."""

    @pytest.mark.asyncio
    async def test_db_get_session_does_not_include_shared_team_names(
        self, test_session, test_team
    ):
        """db_get_session alone does not include shared_team_names (router adds it)."""
        await db_share_session_to_team(test_session, test_team["id"])
        row = await db_get_session(test_session)
        # The raw db row does not have this field; the router enriches it.
        assert "shared_team_names" not in row

    @pytest.mark.asyncio
    async def test_router_enrichment_pattern(self, test_session, test_team):
        """The router pattern of enriching with shared_team_names works end-to-end."""
        await db_share_session_to_team(test_session, test_team["id"])

        row = await db_get_session(test_session)
        assert row is not None

        # Simulate what the router does
        row["shared_team_names"] = await db_get_session_team_names(test_session)

        assert "shared_team_names" in row
        assert test_team["display_name"] in row["shared_team_names"]

    @pytest.mark.asyncio
    async def test_public_session_enrichment_pattern(self, test_session, test_team):
        """Public session endpoint pattern includes shared_team_names."""
        await db_update_session(test_session, {"is_public": True})
        await db_share_session_to_team(test_session, test_team["id"])

        row = await db_get_public_session(test_session)
        assert row is not None

        # Simulate what the router does for the public endpoint
        row["shared_team_names"] = await db_get_session_team_names(test_session)

        assert "shared_team_names" in row
        assert test_team["display_name"] in row["shared_team_names"]

    @pytest.mark.asyncio
    async def test_unshared_session_has_empty_team_names(self, test_session):
        """A session not shared with any team returns empty shared_team_names."""
        row = await db_get_session(test_session)
        assert row is not None
        row["shared_team_names"] = await db_get_session_team_names(test_session)
        assert row["shared_team_names"] == []

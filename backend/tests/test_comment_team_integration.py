"""Integration tests for comment team attribution.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.comments import (
    db_create_comment,
    db_list_comments,
    db_get_comment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_session(conn, owner_sid: str) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.sessions (title, query, owner_sid)
        VALUES ($1, $2, $3) RETURNING id
        """,
        f"test-session-{uuid.uuid4().hex[:8]}", "test query", owner_sid,
    )
    return str(row["id"])


async def _create_team(conn, creator_sid: str) -> tuple[str, str]:
    """Returns (team_id, display_name)."""
    slug = f"team-{uuid.uuid4().hex[:8]}"
    display_name = f"Team {slug}"
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.teams (slug, display_name, description, created_by)
        VALUES ($1, $2, '', $3) RETURNING id
        """,
        slug, display_name, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'owner')",
        team_id, creator_sid,
    )
    return team_id, display_name


# ---------------------------------------------------------------------------
# Create comment with team_id
# ---------------------------------------------------------------------------

class TestCreateCommentWithTeam:

    @pytest.mark.asyncio
    async def test_create_stores_team_id_and_name(self, test_user_sid):
        """Creating a comment with team_id stores both team_id and team_name."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id, display_name = await _create_team(conn, test_user_sid)
        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Team comment body",
                mentions=[],
                team_id=team_id,
                team_name=display_name,
            )
            assert comment["team_id"] == team_id
            assert comment["team_name"] == display_name
            assert isinstance(comment["team_id"], str)
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

    @pytest.mark.asyncio
    async def test_create_null_team_stores_null(self, test_user_sid):
        """Creating a comment without team_id stores NULL for both team fields."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Personal comment",
                mentions=[],
            )
            assert comment["team_id"] is None
            assert comment["team_name"] is None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)

    @pytest.mark.asyncio
    async def test_create_explicit_none_team_id(self, test_user_sid):
        """Explicitly passing team_id=None also stores NULL."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Explicit none",
                mentions=[],
                team_id=None,
                team_name=None,
            )
            assert comment["team_id"] is None
            assert comment["team_name"] is None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)


# ---------------------------------------------------------------------------
# List comments includes team fields
# ---------------------------------------------------------------------------

class TestListCommentsTeamFields:

    @pytest.mark.asyncio
    async def test_list_includes_team_id_and_name(self, test_user_sid):
        """db_list_comments returns team_id and team_name on each comment."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id, display_name = await _create_team(conn, test_user_sid)
        try:
            await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Team comment",
                mentions=[],
                team_id=team_id,
                team_name=display_name,
            )
            comments = await db_list_comments(session_id)
            assert len(comments) == 1
            c = comments[0]
            assert c["team_id"] == team_id
            assert c["team_name"] == display_name
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

    @pytest.mark.asyncio
    async def test_list_null_team_in_mixed_session(self, test_user_sid):
        """Comments without team context return null team fields in list."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
        try:
            await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Personal",
                mentions=[],
            )
            comments = await db_list_comments(session_id)
            assert len(comments) == 1
            c = comments[0]
            assert c.get("team_id") is None
            assert c.get("team_name") is None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)

    @pytest.mark.asyncio
    async def test_list_mixed_team_and_personal_comments(self, test_user_sid):
        """Session can contain both team-attributed and personal comments."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id, display_name = await _create_team(conn, test_user_sid)
        try:
            await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Personal comment",
                mentions=[],
            )
            await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Team comment",
                mentions=[],
                team_id=team_id,
                team_name=display_name,
            )
            comments = await db_list_comments(session_id)
            assert len(comments) == 2

            personal = next(c for c in comments if c["body"] == "Personal comment")
            team_comment = next(c for c in comments if c["body"] == "Team comment")

            assert personal.get("team_id") is None
            assert team_comment["team_id"] == team_id
            assert team_comment["team_name"] == display_name
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


# ---------------------------------------------------------------------------
# Backward compatibility: existing comments (no team columns)
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    @pytest.mark.asyncio
    async def test_get_comment_returns_team_fields_as_none(self, test_user_sid):
        """db_get_comment returns team_id=None for comments created without team context."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Legacy comment",
                mentions=[],
            )
            fetched = await db_get_comment(comment["id"])
            assert fetched is not None
            assert fetched.get("team_id") is None
            assert fetched.get("team_name") is None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)

    @pytest.mark.asyncio
    async def test_team_id_uuid_returned_as_string(self, test_user_sid):
        """team_id stored as UUID in DB must come back as a string in API."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id, display_name = await _create_team(conn, test_user_sid)
        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="UUID check",
                mentions=[],
                team_id=team_id,
                team_name=display_name,
            )
            # Verify UUID was stored and returned as string
            assert isinstance(comment["team_id"], str)
            assert comment["team_id"] == team_id

            fetched = await db_get_comment(comment["id"])
            assert isinstance(fetched["team_id"], str)
            assert fetched["team_id"] == team_id
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

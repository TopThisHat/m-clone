"""E2E tests for comment team attribution.

Full flow: create team → create session → post comment with team_id →
list comments → verify team attribution.

Requires a running PostgreSQL instance (docker compose up -d).
Uses real DB via conftest.py fixtures.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.comments import db_create_comment, db_list_comments
from app.db.teams import db_get_team_by_id, db_is_team_member


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_user(conn, display_name: str) -> str:
    sid = f"e2e-user-{uuid.uuid4().hex[:8]}"
    await conn.execute(
        "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
        sid, display_name, f"{sid}@e2e.local",
    )
    return sid


async def _create_team(conn, creator_sid: str, display_name: str) -> str:
    slug = f"e2e-team-{uuid.uuid4().hex[:8]}"
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
    return team_id


async def _create_session(conn, owner_sid: str, title: str = "E2E Session") -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.sessions (title, query, owner_sid)
        VALUES ($1, $2, $3) RETURNING id
        """,
        title, "e2e query", owner_sid,
    )
    return str(row["id"])


# ---------------------------------------------------------------------------
# E2E: Full comment team attribution flow
# ---------------------------------------------------------------------------

class TestCommentTeamAttributionE2E:

    @pytest.mark.asyncio
    async def test_full_flow_create_team_post_comment_list(self, test_user_sid):
        """Full flow: create team → create session → post comment with team → list → verify."""
        team_display_name = "E2E Team Alpha"

        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id = await _create_team(conn, test_user_sid, team_display_name)

        try:
            # Verify team exists and user is a member
            team = await db_get_team_by_id(team_id)
            assert team is not None
            assert team["display_name"] == team_display_name

            is_member = await db_is_team_member(team_id, test_user_sid)
            assert is_member is True

            # Post a comment attributed to the team
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="E2E team comment",
                mentions=[],
                team_id=team_id,
                team_name=team_display_name,
            )

            assert comment["team_id"] == team_id
            assert comment["team_name"] == team_display_name
            assert isinstance(comment["team_id"], str)

            # List comments and verify team attribution is present
            comments = await db_list_comments(session_id)
            assert len(comments) == 1

            listed = comments[0]
            assert listed["team_id"] == team_id
            assert listed["team_name"] == team_display_name
            assert listed["body"] == "E2E team comment"
            assert listed["author_sid"] == test_user_sid

        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id
                )
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id
                )

    @pytest.mark.asyncio
    async def test_full_flow_personal_comment_no_team(self, test_user_sid):
        """Full flow: create session → post personal comment → list → verify null team fields."""
        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)

        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Personal E2E comment",
                mentions=[],
            )

            assert comment["team_id"] is None
            assert comment["team_name"] is None

            comments = await db_list_comments(session_id)
            assert len(comments) == 1

            listed = comments[0]
            assert listed.get("team_id") is None
            assert listed.get("team_name") is None

        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id
                )

    @pytest.mark.asyncio
    async def test_full_flow_mixed_comments_preserve_attribution(self, test_user_sid):
        """Multiple comments in a session retain their individual team attribution."""
        team_display_name = "E2E Team Beta"

        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id = await _create_team(conn, test_user_sid, team_display_name)

        try:
            # Post personal comment
            personal = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Personal message",
                mentions=[],
            )
            # Post team comment
            team_comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="Team message",
                mentions=[],
                team_id=team_id,
                team_name=team_display_name,
            )

            comments = await db_list_comments(session_id)
            assert len(comments) == 2

            by_body = {c["body"]: c for c in comments}

            assert by_body["Personal message"].get("team_id") is None
            assert by_body["Personal message"].get("team_name") is None

            assert by_body["Team message"]["team_id"] == team_id
            assert by_body["Team message"]["team_name"] == team_display_name

        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id
                )
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id
                )

    @pytest.mark.asyncio
    async def test_full_flow_non_member_cannot_be_attributed(self, test_user_sid):
        """A user who is NOT a team member should not pass membership check."""
        team_display_name = "E2E Team Gamma"

        async with _acquire() as conn:
            other_sid = await _create_user(conn, "Other User")
            team_id = await _create_team(conn, other_sid, team_display_name)

        try:
            # Confirm test_user_sid is NOT a member of this team
            is_member = await db_is_team_member(team_id, test_user_sid)
            assert is_member is False

        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.team_members WHERE team_id = $1::uuid",
                    team_id,
                )
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id
                )
                await conn.execute(
                    "DELETE FROM playbook.users WHERE sid = $1", other_sid
                )

    @pytest.mark.asyncio
    async def test_full_flow_invalid_team_id_not_found(self):
        """A non-existent team_id returns None from db_get_team_by_id."""
        fake_team_id = str(uuid.uuid4())
        team = await db_get_team_by_id(fake_team_id)
        assert team is None

    @pytest.mark.asyncio
    async def test_full_flow_team_id_persists_as_uuid_string(self, test_user_sid):
        """team_id stored as UUID in DB is returned as a string in all read paths."""
        team_display_name = "E2E Team Delta"

        async with _acquire() as conn:
            session_id = await _create_session(conn, test_user_sid)
            team_id = await _create_team(conn, test_user_sid, team_display_name)

        try:
            comment = await db_create_comment(
                session_id=session_id,
                author_sid=test_user_sid,
                body="UUID persistence check",
                mentions=[],
                team_id=team_id,
                team_name=team_display_name,
            )

            # Verify create response
            assert isinstance(comment["team_id"], str)
            assert comment["team_id"] == team_id

            # Verify list response
            comments = await db_list_comments(session_id)
            assert len(comments) == 1
            assert isinstance(comments[0]["team_id"], str)
            assert comments[0]["team_id"] == team_id

        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id
                )
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id
                )

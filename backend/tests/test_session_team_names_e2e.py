"""E2E tests for shared_team_names in the session detail and share API responses.

Requires a running PostgreSQL (docker compose up -d).
Run: cd backend && uv run pytest tests/test_session_team_names_e2e.py -v
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.db import (
    db_create_session,
    db_get_session,
    db_list_team_member_sids,
    db_share_session_to_team,
    db_unshare_session,
    db_update_session,
)
from app.db._pool import _acquire
from app.db.teams import db_create_team, db_get_session_team_names
from app.db.notifications import db_create_notification, db_list_notifications
from app.routers.sessions import TeamShareBody, share_to_team, get_session, get_public_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner():
    sid = f"e2e-owner-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "E2E Owner", f"{sid}@e2e.test",
        )
    yield {"sub": sid, "display_name": "E2E Owner"}
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def member():
    sid = f"e2e-member-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "E2E Member", f"{sid}@e2e.test",
        )
    yield {"sub": sid, "display_name": "E2E Member"}
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def e2e_session(owner):
    row = await db_create_session({
        "title": "E2E Test Session",
        "query": "e2e query",
        "report_markdown": "# E2E Report content for extraction",
        "message_history": [],
        "trace_steps": [],
        "owner_sid": owner["sub"],
        "visibility": "private",
    })
    session_id = row["id"]
    yield session_id
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.sessions WHERE id = $1::uuid", session_id)


@pytest_asyncio.fixture
async def e2e_team(owner, member):
    slug = f"e2e-team-{uuid.uuid4().hex[:8]}"
    team = await db_create_team(slug, f"E2E Team {slug}", "E2E test team", owner["sub"])
    # Add member to team
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'member')",
            team["id"], member["sub"],
        )
    yield team
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team["id"])


# ---------------------------------------------------------------------------
# E2E: Full share flow
# ---------------------------------------------------------------------------


class TestFullShareFlow:
    """Full lifecycle: create → share → verify names → unshare → verify removed."""

    @pytest.mark.asyncio
    async def test_create_share_get_verify_team_names(self, e2e_session, e2e_team, owner):
        """Create session, share with team, get session, verify shared_team_names populated."""
        # Share the session with the team (mocking KG extraction side effect)
        with patch("app.streams.publish_for_extraction", new_callable=AsyncMock):
            body = TeamShareBody(team_id=e2e_team["id"])
            with (
                patch("app.routers.sessions.db_record_activity", new_callable=AsyncMock),
            ):
                await share_to_team(e2e_session, body, owner)

        # Get the session and verify shared_team_names
        row = await db_get_session(e2e_session)
        assert row is not None
        row["shared_team_names"] = await db_get_session_team_names(e2e_session)

        assert "shared_team_names" in row
        assert e2e_team["display_name"] in row["shared_team_names"]

    @pytest.mark.asyncio
    async def test_unshare_removes_team_from_names(self, e2e_session, e2e_team, owner):
        """After unsharing, the team name is removed from shared_team_names."""
        # Share first
        await db_share_session_to_team(e2e_session, e2e_team["id"])

        names_after_share = await db_get_session_team_names(e2e_session)
        assert e2e_team["display_name"] in names_after_share

        # Unshare
        await db_unshare_session(e2e_session, e2e_team["id"])

        names_after_unshare = await db_get_session_team_names(e2e_session)
        assert e2e_team["display_name"] not in names_after_unshare
        assert names_after_unshare == []

    @pytest.mark.asyncio
    async def test_public_session_includes_team_names(self, e2e_session, e2e_team):
        """Public session endpoint flow includes shared_team_names."""
        await db_update_session(e2e_session, {"is_public": True})
        await db_share_session_to_team(e2e_session, e2e_team["id"])

        from app.db import db_get_public_session
        row = await db_get_public_session(e2e_session)
        assert row is not None

        row["shared_team_names"] = await db_get_session_team_names(e2e_session)

        assert "shared_team_names" in row
        assert e2e_team["display_name"] in row["shared_team_names"]


# ---------------------------------------------------------------------------
# E2E: Notification text includes team name
# ---------------------------------------------------------------------------


class TestNotificationTextE2E:
    """E2E verification that notification payload includes correct team name message."""

    @pytest.mark.asyncio
    async def test_share_creates_notification_with_team_name_message(
        self, e2e_session, e2e_team, owner, member
    ):
        """share_to_team creates notifications with 'message' field naming the team."""
        notifications_created: list[dict] = []

        async def capture_notification(recipient_sid, type_, payload):
            notifications_created.append({"recipient_sid": recipient_sid, "type_": type_, "payload": payload})
            return {}

        with (
            patch("app.routers.sessions.db_create_notification", side_effect=capture_notification),
            patch("app.routers.sessions.db_record_activity", new_callable=AsyncMock),
            patch("app.streams.publish_for_extraction", new_callable=AsyncMock),
        ):
            body = TeamShareBody(team_id=e2e_team["id"])
            await share_to_team(e2e_session, body, owner)

        # Should have created notification for the member (not the owner)
        member_notifications = [
            n for n in notifications_created
            if n["recipient_sid"] == member["sub"]
        ]
        assert len(member_notifications) >= 1

        notif = member_notifications[0]
        assert notif["type_"] == "shared_session"
        assert "message" in notif["payload"]
        assert e2e_team["display_name"] in notif["payload"]["message"]
        assert notif["payload"]["message"] == f"A session was shared with {e2e_team['display_name']}"

    @pytest.mark.asyncio
    async def test_notification_owner_not_notified(
        self, e2e_session, e2e_team, owner
    ):
        """The owner who shares is not sent a notification."""
        notifications_created: list[dict] = []

        async def capture_notification(recipient_sid, type_, payload):
            notifications_created.append({"recipient_sid": recipient_sid, "payload": payload})
            return {}

        with (
            patch("app.routers.sessions.db_create_notification", side_effect=capture_notification),
            patch("app.routers.sessions.db_record_activity", new_callable=AsyncMock),
            patch("app.streams.publish_for_extraction", new_callable=AsyncMock),
        ):
            body = TeamShareBody(team_id=e2e_team["id"])
            await share_to_team(e2e_session, body, owner)

        owner_notifications = [
            n for n in notifications_created
            if n["recipient_sid"] == owner["sub"]
        ]
        assert len(owner_notifications) == 0

    @pytest.mark.asyncio
    async def test_notification_payload_has_all_required_fields(
        self, e2e_session, e2e_team, owner, member
    ):
        """Notification payload must include all required fields for frontend rendering."""
        notifications_created: list[dict] = []

        async def capture_notification(recipient_sid, type_, payload):
            notifications_created.append(payload)
            return {}

        with (
            patch("app.routers.sessions.db_create_notification", side_effect=capture_notification),
            patch("app.routers.sessions.db_record_activity", new_callable=AsyncMock),
            patch("app.streams.publish_for_extraction", new_callable=AsyncMock),
        ):
            body = TeamShareBody(team_id=e2e_team["id"])
            await share_to_team(e2e_session, body, owner)

        assert len(notifications_created) >= 1
        payload = notifications_created[0]

        required = {"session_id", "session_title", "team_name", "shared_by_name", "message"}
        assert required.issubset(payload.keys()), (
            f"Missing fields: {required - payload.keys()}"
        )
        assert payload["team_name"] == e2e_team["display_name"]
        assert payload["shared_by_name"] == owner["display_name"]
        assert payload["session_id"] == e2e_session

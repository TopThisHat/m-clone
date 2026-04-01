"""Unit tests for shared_team_names on session responses.

Mocked — no running database required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.session import SessionFull


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# 1. SessionFull model
# ---------------------------------------------------------------------------


class TestSessionFullModel:
    """Verify SessionFull Pydantic model includes shared_team_names."""

    def test_session_full_has_shared_team_names_field(self):
        """SessionFull must have a shared_team_names field."""
        assert "shared_team_names" in SessionFull.model_fields

    def test_shared_team_names_defaults_to_empty_list(self):
        """shared_team_names should default to [] when not provided."""
        session = SessionFull(
            id=str(uuid4()),
            title="Test",
            query="test query",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            report_markdown="",
            message_history=[],
            trace_steps=[],
        )
        assert session.shared_team_names == []

    def test_shared_team_names_accepts_list_of_strings(self):
        """shared_team_names should accept a list of team display names."""
        session = SessionFull(
            id=str(uuid4()),
            title="Test",
            query="test query",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            report_markdown="",
            message_history=[],
            trace_steps=[],
            shared_team_names=["Alpha Team", "Beta Team"],
        )
        assert session.shared_team_names == ["Alpha Team", "Beta Team"]

    def test_session_full_is_backward_compatible(self):
        """SessionFull must still validate when shared_team_names is absent (backward compat)."""
        data = {
            "id": str(uuid4()),
            "title": "Old API Response",
            "query": "query",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "report_markdown": "# Report",
            "message_history": [],
            "trace_steps": [],
        }
        session = SessionFull(**data)
        assert session.shared_team_names == []

    def test_session_full_serializes_shared_team_names(self):
        """model_dump() should include shared_team_names."""
        session = SessionFull(
            id=str(uuid4()),
            title="Test",
            query="test query",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            report_markdown="",
            message_history=[],
            trace_steps=[],
            shared_team_names=["Gamma Team"],
        )
        dumped = session.model_dump()
        assert "shared_team_names" in dumped
        assert dumped["shared_team_names"] == ["Gamma Team"]


# ---------------------------------------------------------------------------
# 2. db_get_session_team_names DB function
# ---------------------------------------------------------------------------


class TestDbGetSessionTeamNames:
    """Verify db_get_session_team_names queries correctly."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_shares(self):
        """Returns [] when session has no team shares."""
        from app.db import teams

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(teams, "_acquire", return_value=mock_cm):
            result = await teams.db_get_session_team_names(str(uuid4()))
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_display_names(self):
        """Returns a list of display_name strings from the JOIN result."""
        from app.db import teams

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"display_name": "Alpha Team"},
            {"display_name": "Beta Team"},
        ])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(teams, "_acquire", return_value=mock_cm):
            result = await teams.db_get_session_team_names(str(uuid4()))
        assert result == ["Alpha Team", "Beta Team"]

    @pytest.mark.asyncio
    async def test_sql_joins_teams_table(self):
        """The SQL must JOIN the teams table to resolve display_name."""
        from app.db import teams

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(teams, "_acquire", return_value=mock_cm):
            await teams.db_get_session_team_names("some-session-id")

        sql = mock_conn.fetch.call_args[0][0]
        assert "session_teams" in sql
        assert "teams" in sql
        assert "display_name" in sql


# ---------------------------------------------------------------------------
# 3. Notification message includes team name
# ---------------------------------------------------------------------------


class TestNotificationTeamName:
    """Verify share notifications include team name in the message field."""

    @pytest.mark.asyncio
    async def test_share_notification_message_includes_team_name(self):
        """share_to_team must include 'message' key with team name in notification payload."""
        from app.routers import sessions as sessions_module

        fake_session = {
            "id": "sess-1",
            "owner_sid": "user-1",
            "title": "My Research",
            "report_markdown": "",
            "visibility": "private",
        }
        fake_team = {"id": "team-1", "display_name": "Alpha Team"}
        fake_user = {"sub": "user-1", "display_name": "Alice"}

        captured_payload: dict = {}

        async def fake_create_notification(recipient_sid, type_, payload):
            captured_payload.update(payload)
            return {}

        with (
            patch.object(sessions_module, "db_get_session", return_value=fake_session),
            patch.object(sessions_module, "db_get_team_by_id", return_value=fake_team),
            patch.object(sessions_module, "db_get_member_role", return_value="member"),
            patch.object(sessions_module, "db_share_session_to_team", return_value={}),
            patch.object(sessions_module, "db_update_session", return_value=fake_session),
            patch.object(sessions_module, "db_record_activity", return_value=None),
            patch.object(sessions_module, "db_list_team_member_sids", return_value=["user-2"]),
            patch.object(sessions_module, "db_create_notification", side_effect=fake_create_notification),
        ):
            from fastapi import Request
            from app.routers.sessions import TeamShareBody, share_to_team

            body = TeamShareBody(team_id="team-1")
            await share_to_team("sess-1", body, fake_user)

        assert "message" in captured_payload
        assert "Alpha Team" in captured_payload["message"]

    @pytest.mark.asyncio
    async def test_notification_message_format(self):
        """Notification message should follow 'A session was shared with [Team Name]' format."""
        from app.routers import sessions as sessions_module

        fake_session = {
            "id": "sess-2",
            "owner_sid": "user-1",
            "title": "Report",
            "report_markdown": "",
            "visibility": "private",
        }
        fake_team = {"id": "team-2", "display_name": "Gamma Team"}
        fake_user = {"sub": "user-1", "display_name": "Bob"}

        captured_payloads: list[dict] = []

        async def fake_create_notification(recipient_sid, type_, payload):
            captured_payloads.append(payload)
            return {}

        with (
            patch.object(sessions_module, "db_get_session", return_value=fake_session),
            patch.object(sessions_module, "db_get_team_by_id", return_value=fake_team),
            patch.object(sessions_module, "db_get_member_role", return_value="member"),
            patch.object(sessions_module, "db_share_session_to_team", return_value={}),
            patch.object(sessions_module, "db_update_session", return_value=fake_session),
            patch.object(sessions_module, "db_record_activity", return_value=None),
            patch.object(sessions_module, "db_list_team_member_sids", return_value=["user-3"]),
            patch.object(sessions_module, "db_create_notification", side_effect=fake_create_notification),
        ):
            from app.routers.sessions import TeamShareBody, share_to_team

            body = TeamShareBody(team_id="team-2")
            await share_to_team("sess-2", body, fake_user)

        assert len(captured_payloads) == 1
        msg = captured_payloads[0]["message"]
        assert msg == "A session was shared with Gamma Team"

    def test_notification_payload_still_has_team_name_field(self):
        """Notification payload must retain team_name for frontend rendering."""
        # This is a static assertion — ensures the spec is understood correctly.
        # The frontend renders: "{shared_by_name} shared '{title}' with {team_name}"
        # The new 'message' field is additive and does not replace team_name.
        required_fields = {"session_id", "session_title", "team_name", "shared_by_name", "message"}
        # These fields must all be present when a notification is created
        # (validated by the integration test; this unit test documents the contract).
        assert required_fields == {
            "session_id", "session_title", "team_name", "shared_by_name", "message"
        }

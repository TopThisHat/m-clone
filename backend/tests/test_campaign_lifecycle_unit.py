"""Unit tests for campaign lifecycle status.

Tests enum validation, transition rules, and audit logging without a real database.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.models.campaign import (
    CampaignOut,
    CampaignStatus,
    CampaignStatusUpdate,
    VALID_STATUS_TRANSITIONS,
)


# Override the autouse _ensure_schema fixture from conftest.py so that
# these pure-unit tests never attempt to connect to PostgreSQL.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# CampaignStatus enum
# ---------------------------------------------------------------------------

class TestCampaignStatusEnum:

    def test_enum_values(self):
        assert CampaignStatus.draft.value == "draft"
        assert CampaignStatus.active.value == "active"
        assert CampaignStatus.completed.value == "completed"
        assert CampaignStatus.archived.value == "archived"

    def test_enum_from_string(self):
        assert CampaignStatus("draft") is CampaignStatus.draft
        assert CampaignStatus("active") is CampaignStatus.active
        assert CampaignStatus("completed") is CampaignStatus.completed
        assert CampaignStatus("archived") is CampaignStatus.archived

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            CampaignStatus("nonexistent")

    def test_enum_is_str_subclass(self):
        """CampaignStatus(str, Enum) is JSON-serialisable."""
        assert isinstance(CampaignStatus.draft, str)
        assert CampaignStatus.draft == "draft"

    def test_all_four_statuses_covered(self):
        assert len(CampaignStatus) == 4


# ---------------------------------------------------------------------------
# CampaignStatusUpdate model
# ---------------------------------------------------------------------------

class TestCampaignStatusUpdateModel:

    def test_valid_status_accepted(self):
        body = CampaignStatusUpdate(status="active")
        assert body.status is CampaignStatus.active

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            CampaignStatusUpdate(status="bogus")

    def test_missing_status_rejected(self):
        with pytest.raises(ValidationError):
            CampaignStatusUpdate()


# ---------------------------------------------------------------------------
# CampaignOut includes status field
# ---------------------------------------------------------------------------

class TestCampaignOutStatus:

    def test_default_status_is_draft(self):
        out = CampaignOut(
            id="abc",
            owner_sid="user-1",
            name="Test",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert out.status is CampaignStatus.draft

    def test_explicit_status_accepted(self):
        out = CampaignOut(
            id="abc",
            owner_sid="user-1",
            name="Test",
            status="active",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        assert out.status is CampaignStatus.active

    def test_invalid_status_in_out_rejected(self):
        with pytest.raises(ValidationError):
            CampaignOut(
                id="abc",
                owner_sid="user-1",
                name="Test",
                status="invalid",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            )


# ---------------------------------------------------------------------------
# Transition rules (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestTransitionRules:
    """Verify VALID_STATUS_TRANSITIONS map covers the required lifecycle."""

    def test_draft_to_active_allowed(self):
        assert CampaignStatus.active in VALID_STATUS_TRANSITIONS[CampaignStatus.draft]

    def test_active_to_completed_allowed(self):
        assert CampaignStatus.completed in VALID_STATUS_TRANSITIONS[CampaignStatus.active]

    def test_active_to_archived_allowed(self):
        assert CampaignStatus.archived in VALID_STATUS_TRANSITIONS[CampaignStatus.active]

    def test_completed_to_archived_allowed(self):
        assert CampaignStatus.archived in VALID_STATUS_TRANSITIONS[CampaignStatus.completed]

    def test_archived_has_no_outgoing_transitions(self):
        assert VALID_STATUS_TRANSITIONS[CampaignStatus.archived] == set()

    # Invalid transitions
    def test_draft_to_completed_disallowed(self):
        assert CampaignStatus.completed not in VALID_STATUS_TRANSITIONS[CampaignStatus.draft]

    def test_draft_to_archived_disallowed(self):
        assert CampaignStatus.archived not in VALID_STATUS_TRANSITIONS[CampaignStatus.draft]

    def test_completed_to_active_disallowed(self):
        assert CampaignStatus.active not in VALID_STATUS_TRANSITIONS[CampaignStatus.completed]

    def test_completed_to_draft_disallowed(self):
        assert CampaignStatus.draft not in VALID_STATUS_TRANSITIONS[CampaignStatus.completed]

    def test_archived_to_draft_disallowed(self):
        assert CampaignStatus.draft not in VALID_STATUS_TRANSITIONS[CampaignStatus.archived]

    def test_archived_to_active_disallowed(self):
        assert CampaignStatus.active not in VALID_STATUS_TRANSITIONS[CampaignStatus.archived]

    def test_archived_to_completed_disallowed(self):
        assert CampaignStatus.completed not in VALID_STATUS_TRANSITIONS[CampaignStatus.archived]

    def test_active_to_draft_disallowed(self):
        assert CampaignStatus.draft not in VALID_STATUS_TRANSITIONS[CampaignStatus.active]

    def test_draft_to_draft_disallowed(self):
        """Self-transition from draft -> draft is not in the allowed set."""
        assert CampaignStatus.draft not in VALID_STATUS_TRANSITIONS[CampaignStatus.draft]

    def test_every_status_has_a_transition_entry(self):
        for status in CampaignStatus:
            assert status in VALID_STATUS_TRANSITIONS


# ---------------------------------------------------------------------------
# db_transition_campaign_status logic (mocked DB)
# ---------------------------------------------------------------------------

class _FakeTransaction:
    """Async context manager that mimics asyncpg's conn.transaction()."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class TestTransitionFunctionMocked:
    """Test the transition function's validation logic using a mocked DB."""

    @pytest.fixture
    def mock_conn(self):
        from unittest.mock import AsyncMock
        conn = AsyncMock()
        conn.transaction = lambda: _FakeTransaction()
        return conn

    async def test_transition_raises_404_when_not_found(self, mock_conn):
        from unittest.mock import AsyncMock, patch
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.campaigns._acquire", return_value=mock_ctx):
            from app.db.campaigns import db_transition_campaign_status
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await db_transition_campaign_status(
                    "00000000-0000-0000-0000-000000000000",
                    CampaignStatus.active,
                    "user-1",
                )
            assert exc_info.value.status_code == 404

    async def test_transition_raises_400_for_invalid_transition(self, mock_conn):
        from unittest.mock import AsyncMock, patch, MagicMock
        import uuid

        # Simulate a campaign row with status='completed'
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, key: {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "status": "completed",
        }[key]

        # fetchrow returns the row on first call (SELECT), shouldn't reach second
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.campaigns._acquire", return_value=mock_ctx):
            from app.db.campaigns import db_transition_campaign_status
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await db_transition_campaign_status(
                    "00000000-0000-0000-0000-000000000001",
                    CampaignStatus.active,  # completed -> active is invalid
                    "user-1",
                )
            assert exc_info.value.status_code == 400
            assert "Invalid status transition" in exc_info.value.detail

    async def test_audit_logging_called(self, mock_conn):
        """Verify that an INSERT into campaign_status_audit is executed."""
        from unittest.mock import AsyncMock, patch, MagicMock
        import uuid
        from datetime import datetime, timezone

        campaign_id = "00000000-0000-0000-0000-000000000002"

        fake_select_row = MagicMock()
        fake_select_row.__getitem__ = lambda self, key: {
            "id": uuid.UUID(campaign_id),
            "status": "draft",
        }[key]

        now = datetime.now(timezone.utc)
        fake_update_row = {
            "id": uuid.UUID(campaign_id),
            "owner_sid": "user-1",
            "team_id": None,
            "name": "Test",
            "description": None,
            "schedule": None,
            "is_active": True,
            "status": "active",
            "last_run_at": None,
            "next_run_at": None,
            "created_at": now,
            "updated_at": now,
        }

        # First fetchrow = SELECT ... FOR UPDATE, second = UPDATE ... RETURNING *
        mock_conn.fetchrow = AsyncMock(side_effect=[fake_select_row, fake_update_row])
        mock_conn.execute = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.campaigns._acquire", return_value=mock_ctx):
            from app.db.campaigns import db_transition_campaign_status
            await db_transition_campaign_status(campaign_id, CampaignStatus.active, "user-1")

        # Verify the audit INSERT was called
        audit_calls = [
            c for c in mock_conn.execute.call_args_list
            if "campaign_status_audit" in str(c)
        ]
        assert len(audit_calls) == 1, "Expected exactly one audit INSERT"

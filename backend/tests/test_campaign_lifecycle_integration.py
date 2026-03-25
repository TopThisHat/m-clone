"""Integration tests for campaign lifecycle status transitions.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.

Run: cd backend && uv run python -m pytest tests/test_campaign_lifecycle_integration.py -v
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.campaigns import (
    db_create_campaign,
    db_get_campaign,
    db_get_campaign_status_audit,
    db_transition_campaign_status,
)
from app.models.campaign import CampaignStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def campaign_owner_sid():
    """Create a throwaway user and return its SID."""
    sid = f"lifecycle-test-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "Lifecycle Tester", f"{sid}@test.local",
        )
    yield sid
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def draft_campaign(campaign_owner_sid):
    """Create a campaign in draft status and return its id."""
    result = await db_create_campaign(
        owner_sid=campaign_owner_sid,
        name=f"lifecycle-campaign-{uuid.uuid4().hex[:8]}",
        description="Integration test campaign",
        schedule=None,
    )
    campaign_id = result["id"]
    yield campaign_id
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id,
        )


# ---------------------------------------------------------------------------
# Basic transitions
# ---------------------------------------------------------------------------

class TestValidTransitions:

    async def test_draft_to_active(self, draft_campaign, campaign_owner_sid):
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.active, campaign_owner_sid,
        )
        assert result["status"] == "active"

    async def test_active_to_completed(self, draft_campaign, campaign_owner_sid):
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.completed, campaign_owner_sid,
        )
        assert result["status"] == "completed"

    async def test_active_to_archived(self, draft_campaign, campaign_owner_sid):
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.archived, campaign_owner_sid,
        )
        assert result["status"] == "archived"

    async def test_completed_to_archived(self, draft_campaign, campaign_owner_sid):
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        await db_transition_campaign_status(draft_campaign, CampaignStatus.completed, campaign_owner_sid)
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.archived, campaign_owner_sid,
        )
        assert result["status"] == "archived"


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:

    async def test_draft_to_completed_rejected(self, draft_campaign, campaign_owner_sid):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await db_transition_campaign_status(
                draft_campaign, CampaignStatus.completed, campaign_owner_sid,
            )
        assert exc_info.value.status_code == 400

    async def test_draft_to_archived_rejected(self, draft_campaign, campaign_owner_sid):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await db_transition_campaign_status(
                draft_campaign, CampaignStatus.archived, campaign_owner_sid,
            )
        assert exc_info.value.status_code == 400

    async def test_completed_to_active_rejected(self, draft_campaign, campaign_owner_sid):
        from fastapi import HTTPException
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        await db_transition_campaign_status(draft_campaign, CampaignStatus.completed, campaign_owner_sid)
        with pytest.raises(HTTPException) as exc_info:
            await db_transition_campaign_status(
                draft_campaign, CampaignStatus.active, campaign_owner_sid,
            )
        assert exc_info.value.status_code == 400

    async def test_archived_to_anything_rejected(self, draft_campaign, campaign_owner_sid):
        from fastapi import HTTPException
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        await db_transition_campaign_status(draft_campaign, CampaignStatus.archived, campaign_owner_sid)
        for target in [CampaignStatus.draft, CampaignStatus.active, CampaignStatus.completed]:
            with pytest.raises(HTTPException) as exc_info:
                await db_transition_campaign_status(
                    draft_campaign, target, campaign_owner_sid,
                )
            assert exc_info.value.status_code == 400

    async def test_nonexistent_campaign_returns_404(self, campaign_owner_sid):
        from fastapi import HTTPException
        fake_id = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(HTTPException) as exc_info:
            await db_transition_campaign_status(
                fake_id, CampaignStatus.active, campaign_owner_sid,
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Full lifecycle traversal
# ---------------------------------------------------------------------------

class TestFullLifecycle:

    async def test_full_lifecycle_draft_active_completed_archived(
        self, draft_campaign, campaign_owner_sid,
    ):
        """Walk the entire happy path: draft -> active -> completed -> archived."""
        # Verify starting status
        campaign = await db_get_campaign(draft_campaign)
        assert campaign["status"] == "draft"

        # draft -> active
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.active, campaign_owner_sid,
        )
        assert result["status"] == "active"

        # active -> completed
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.completed, campaign_owner_sid,
        )
        assert result["status"] == "completed"

        # completed -> archived
        result = await db_transition_campaign_status(
            draft_campaign, CampaignStatus.archived, campaign_owner_sid,
        )
        assert result["status"] == "archived"

        # Verify final DB state
        campaign = await db_get_campaign(draft_campaign)
        assert campaign["status"] == "archived"


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail:

    async def test_audit_records_created(self, draft_campaign, campaign_owner_sid):
        """Each transition creates an audit record."""
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        await db_transition_campaign_status(draft_campaign, CampaignStatus.completed, campaign_owner_sid)

        audit = await db_get_campaign_status_audit(draft_campaign)
        assert len(audit) == 2

        # Newest first
        assert audit[0]["old_status"] == "active"
        assert audit[0]["new_status"] == "completed"
        assert audit[0]["changed_by_sid"] == campaign_owner_sid

        assert audit[1]["old_status"] == "draft"
        assert audit[1]["new_status"] == "active"
        assert audit[1]["changed_by_sid"] == campaign_owner_sid

    async def test_audit_timestamps_present(self, draft_campaign, campaign_owner_sid):
        await db_transition_campaign_status(draft_campaign, CampaignStatus.active, campaign_owner_sid)
        audit = await db_get_campaign_status_audit(draft_campaign)
        assert len(audit) == 1
        assert audit[0]["changed_at"] is not None

    async def test_failed_transition_does_not_create_audit(
        self, draft_campaign, campaign_owner_sid,
    ):
        """If the transition is invalid, no audit record should be written."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await db_transition_campaign_status(
                draft_campaign, CampaignStatus.archived, campaign_owner_sid,
            )
        audit = await db_get_campaign_status_audit(draft_campaign)
        assert len(audit) == 0


# ---------------------------------------------------------------------------
# Database state consistency
# ---------------------------------------------------------------------------

class TestDatabaseState:

    async def test_updated_at_changes_on_transition(
        self, draft_campaign, campaign_owner_sid,
    ):
        campaign_before = await db_get_campaign(draft_campaign)
        await db_transition_campaign_status(
            draft_campaign, CampaignStatus.active, campaign_owner_sid,
        )
        campaign_after = await db_get_campaign(draft_campaign)
        assert campaign_after["updated_at"] >= campaign_before["updated_at"]

    async def test_new_campaign_defaults_to_draft(self, campaign_owner_sid):
        """Campaigns created via db_create_campaign default to 'draft' status."""
        result = await db_create_campaign(
            owner_sid=campaign_owner_sid,
            name=f"default-status-{uuid.uuid4().hex[:8]}",
            description=None,
            schedule=None,
        )
        campaign_id = result["id"]
        try:
            campaign = await db_get_campaign(campaign_id)
            assert campaign["status"] == "draft"
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id,
                )

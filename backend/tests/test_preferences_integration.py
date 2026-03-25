"""Integration tests for Preferences DB layer.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.

Tests get/upsert preferences against actual database rows.
"""
from __future__ import annotations

import uuid

import pytest_asyncio

from app.db._pool import _acquire
from app.db.preferences import (
    db_get_preferences,
    db_upsert_preferences,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def cleanup_preferences(test_user_sid):
    """Clean up any user_preferences rows for the test user after the test."""
    yield test_user_sid
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.user_preferences WHERE user_sid = $1",
            test_user_sid,
        )


# ---------------------------------------------------------------------------
# db_get_preferences
# ---------------------------------------------------------------------------

class TestDbGetPreferences:

    async def test_get_returns_none_when_no_prefs(self, cleanup_preferences):
        """Getting preferences for a user with no saved prefs returns None."""
        result = await db_get_preferences(cleanup_preferences)
        assert result is None

    async def test_get_global_preferences(self, cleanup_preferences):
        """After upserting global preferences, get returns them."""
        user_sid = cleanup_preferences
        await db_upsert_preferences(user_sid, None, {"sort_order": "asc"})

        result = await db_get_preferences(user_sid)
        assert result is not None
        assert result["user_sid"] == user_sid
        assert result["campaign_id"] is None
        assert result["preferences"]["sort_order"] == "asc"

    async def test_get_campaign_specific_preferences(self, cleanup_preferences, test_campaign):
        """Campaign-scoped preferences are separate from global ones."""
        user_sid = cleanup_preferences
        await db_upsert_preferences(user_sid, None, {"global_key": True})
        await db_upsert_preferences(
            user_sid, test_campaign, {"campaign_key": True}
        )

        global_prefs = await db_get_preferences(user_sid)
        campaign_prefs = await db_get_preferences(user_sid, test_campaign)

        assert global_prefs is not None
        assert "global_key" in global_prefs["preferences"]
        assert "campaign_key" not in global_prefs["preferences"]

        assert campaign_prefs is not None
        assert "campaign_key" in campaign_prefs["preferences"]
        assert "global_key" not in campaign_prefs["preferences"]

    async def test_get_nonexistent_campaign_returns_none(self, cleanup_preferences):
        """Getting preferences for a campaign that has no prefs returns None."""
        result = await db_get_preferences(
            cleanup_preferences, str(uuid.uuid4())
        )
        assert result is None


# ---------------------------------------------------------------------------
# db_upsert_preferences
# ---------------------------------------------------------------------------

class TestDbUpsertPreferences:

    async def test_insert_global_preferences(self, cleanup_preferences):
        """First upsert creates a new row."""
        user_sid = cleanup_preferences
        result = await db_upsert_preferences(
            user_sid, None, {"columns": ["name", "score"]}
        )
        assert result["user_sid"] == user_sid
        assert result["campaign_id"] is None
        assert result["preferences"]["columns"] == ["name", "score"]
        assert "id" in result
        assert "created_at" in result
        assert "updated_at" in result

    async def test_update_global_preferences(self, cleanup_preferences):
        """Second upsert with same user_sid + NULL campaign updates in place."""
        user_sid = cleanup_preferences
        first = await db_upsert_preferences(
            user_sid, None, {"sort": "asc"}
        )
        second = await db_upsert_preferences(
            user_sid, None, {"sort": "desc", "view": "grid"}
        )

        # Same row (same id)
        assert first["id"] == second["id"]
        # Updated preferences
        assert second["preferences"]["sort"] == "desc"
        assert second["preferences"]["view"] == "grid"

    async def test_upsert_campaign_specific(self, cleanup_preferences, test_campaign):
        """Upsert with a campaign_id creates a campaign-scoped row."""
        user_sid = cleanup_preferences
        result = await db_upsert_preferences(
            user_sid, test_campaign, {"columns": ["entity", "confidence"]}
        )
        assert result["campaign_id"] == test_campaign
        assert result["preferences"]["columns"] == ["entity", "confidence"]

    async def test_upsert_different_campaigns_are_independent(
        self, cleanup_preferences, test_campaign
    ):
        """Different campaign_ids produce separate rows."""
        user_sid = cleanup_preferences
        # Create a second campaign
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                f"second-{uuid.uuid4().hex[:8]}", user_sid,
            )
            second_campaign = str(row["id"])

        try:
            r1 = await db_upsert_preferences(
                user_sid, test_campaign, {"view": "table"}
            )
            r2 = await db_upsert_preferences(
                user_sid, second_campaign, {"view": "grid"}
            )

            assert r1["id"] != r2["id"]
            assert r1["preferences"]["view"] == "table"
            assert r2["preferences"]["view"] == "grid"
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.user_preferences WHERE campaign_id = $1::uuid",
                    second_campaign,
                )
                await conn.execute(
                    "DELETE FROM playbook.campaigns WHERE id = $1::uuid",
                    second_campaign,
                )

    async def test_upsert_empty_preferences(self, cleanup_preferences):
        """Upserting empty preferences dict is valid."""
        user_sid = cleanup_preferences
        result = await db_upsert_preferences(user_sid, None, {})
        assert result["preferences"] == {}

    async def test_upsert_complex_jsonb(self, cleanup_preferences):
        """Preferences can contain nested structures."""
        user_sid = cleanup_preferences
        prefs = {
            "columns": {"visible": ["name", "score"], "order": ["name", "score"]},
            "filters": [{"field": "score", "op": ">=", "value": 0.5}],
            "sort": {"field": "name", "direction": "asc"},
        }
        result = await db_upsert_preferences(user_sid, None, prefs)
        assert result["preferences"]["columns"]["visible"] == ["name", "score"]
        assert len(result["preferences"]["filters"]) == 1

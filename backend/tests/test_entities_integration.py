"""Integration tests for entity management against a real PostgreSQL database.

Covers:
  - Label uniqueness enforcement (create + update)
  - Metadata CRUD (set, get, delete)
  - External ID management (set, get, delete, upsert)
  - Sorting support (by name, created_at, score)

Requires: docker compose up -d (PostgreSQL on port 5432)
Run: cd backend && uv run python -m pytest tests/test_entities_integration.py -v
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.entities import (
    DuplicateLabelError,
    db_create_entity,
    db_delete_entity_metadata,
    db_get_entity_metadata,
    db_get_external_ids,
    db_list_entities,
    db_set_entity_metadata,
    db_set_external_id,
    db_delete_external_id,
    db_update_entity,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def entity(test_campaign: str) -> dict[str, Any]:
    """Create a single entity in the test campaign and return it."""
    e = await db_create_entity(
        campaign_id=test_campaign,
        label=f"Entity-{uuid.uuid4().hex[:6]}",
        description="Test entity",
        metadata={"initial": "value"},
    )
    return e


# ── Label uniqueness ────────────────────────────────────────────────────────

class TestLabelUniqueness:

    async def test_create_duplicate_label_raises(self, test_campaign: str):
        label = f"UniqueLabel-{uuid.uuid4().hex[:6]}"
        await db_create_entity(campaign_id=test_campaign, label=label)
        with pytest.raises(DuplicateLabelError) as exc_info:
            await db_create_entity(campaign_id=test_campaign, label=label)
        assert label in str(exc_info.value)

    async def test_create_case_insensitive_duplicate_raises(self, test_campaign: str):
        label = f"CaseTest-{uuid.uuid4().hex[:6]}"
        await db_create_entity(campaign_id=test_campaign, label=label)
        with pytest.raises(DuplicateLabelError):
            await db_create_entity(campaign_id=test_campaign, label=label.upper())

    async def test_create_trimmed_duplicate_raises(self, test_campaign: str):
        label = f"TrimTest-{uuid.uuid4().hex[:6]}"
        await db_create_entity(campaign_id=test_campaign, label=label)
        with pytest.raises(DuplicateLabelError):
            await db_create_entity(campaign_id=test_campaign, label=f"  {label}  ")

    async def test_update_to_existing_label_raises(self, test_campaign: str):
        e1 = await db_create_entity(campaign_id=test_campaign, label=f"E1-{uuid.uuid4().hex[:6]}")
        e2 = await db_create_entity(campaign_id=test_campaign, label=f"E2-{uuid.uuid4().hex[:6]}")
        with pytest.raises(DuplicateLabelError):
            await db_update_entity(e2["id"], test_campaign, label=e1["label"])

    async def test_update_same_label_on_self_succeeds(self, test_campaign: str):
        e = await db_create_entity(campaign_id=test_campaign, label=f"SelfUpdate-{uuid.uuid4().hex[:6]}")
        # Updating with the same label (case variation) should succeed
        updated = await db_update_entity(e["id"], test_campaign, label=e["label"])
        assert updated is not None
        assert updated["label"] == e["label"]

    async def test_different_campaigns_allow_same_label(self, test_user_sid: str):
        """Same label in different campaigns is fine."""
        label = f"CrossCamp-{uuid.uuid4().hex[:6]}"
        # Create two campaigns
        async with _acquire() as conn:
            row1 = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                f"camp-a-{uuid.uuid4().hex[:6]}", test_user_sid,
            )
            row2 = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                f"camp-b-{uuid.uuid4().hex[:6]}", test_user_sid,
            )
        c1, c2 = str(row1["id"]), str(row2["id"])
        try:
            await db_create_entity(campaign_id=c1, label=label)
            e2 = await db_create_entity(campaign_id=c2, label=label)
            assert e2["label"] == label
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id IN ($1::uuid, $2::uuid)", c1, c2)


# ── Metadata CRUD ────────────────────────────────────────────────────────────

class TestMetadataCRUD:

    async def test_get_initial_metadata(self, entity: dict):
        meta = await db_get_entity_metadata(entity["id"])
        assert meta == {"initial": "value"}

    async def test_set_metadata_key(self, entity: dict):
        result = await db_set_entity_metadata(entity["id"], "new_key", "new_value")
        assert result["new_key"] == "new_value"
        assert result["initial"] == "value"  # original preserved

    async def test_set_metadata_overwrite_key(self, entity: dict):
        await db_set_entity_metadata(entity["id"], "initial", "overwritten")
        meta = await db_get_entity_metadata(entity["id"])
        assert meta["initial"] == "overwritten"

    async def test_set_metadata_nested_value(self, entity: dict):
        nested = {"nested": {"deep": True, "list": [1, 2, 3]}}
        result = await db_set_entity_metadata(entity["id"], "complex", nested)
        assert result["complex"] == nested

    async def test_delete_metadata_key(self, entity: dict):
        result = await db_delete_entity_metadata(entity["id"], "initial")
        assert "initial" not in result

    async def test_delete_nonexistent_key(self, entity: dict):
        """Deleting a key that doesn't exist should not fail."""
        result = await db_delete_entity_metadata(entity["id"], "no_such_key")
        assert "initial" in result  # original still there


# ── External IDs ─────────────────────────────────────────────────────────────

class TestExternalIds:

    async def test_set_and_get_external_id(self, entity: dict):
        await db_set_external_id(entity["id"], "GWM", "GWM-12345")
        ids = await db_get_external_ids(entity["id"])
        assert len(ids) == 1
        assert ids[0]["system"] == "GWM"
        assert ids[0]["external_id"] == "GWM-12345"
        assert ids[0]["entity_id"] == entity["id"]

    async def test_upsert_external_id(self, entity: dict):
        """Setting the same system again should update, not duplicate."""
        await db_set_external_id(entity["id"], "GWM", "OLD-ID")
        await db_set_external_id(entity["id"], "GWM", "NEW-ID")
        ids = await db_get_external_ids(entity["id"])
        assert len(ids) == 1
        assert ids[0]["external_id"] == "NEW-ID"

    async def test_multiple_systems(self, entity: dict):
        await db_set_external_id(entity["id"], "GWM", "GWM-001")
        await db_set_external_id(entity["id"], "BLOOMBERG", "BBG-001")
        await db_set_external_id(entity["id"], "REFINITIV", "RIC-001")
        ids = await db_get_external_ids(entity["id"])
        assert len(ids) == 3
        systems = {i["system"] for i in ids}
        assert systems == {"BLOOMBERG", "GWM", "REFINITIV"}

    async def test_delete_external_id(self, entity: dict):
        await db_set_external_id(entity["id"], "GWM", "GWM-DEL")
        deleted = await db_delete_external_id(entity["id"], "GWM")
        assert deleted is True
        ids = await db_get_external_ids(entity["id"])
        assert len(ids) == 0

    async def test_delete_nonexistent_external_id(self, entity: dict):
        deleted = await db_delete_external_id(entity["id"], "NO_SUCH_SYSTEM")
        assert deleted is False

    async def test_get_external_ids_empty(self, entity: dict):
        ids = await db_get_external_ids(entity["id"])
        assert ids == []


# ── Sorting ──────────────────────────────────────────────────────────────────

class TestEntitySorting:

    async def test_sort_by_name_asc(self, test_campaign: str):
        await db_create_entity(campaign_id=test_campaign, label="Zebra")
        await db_create_entity(campaign_id=test_campaign, label="Alpha")
        await db_create_entity(campaign_id=test_campaign, label="Middle")
        result = await db_list_entities(test_campaign, sort_by="name", order="asc", limit=0)
        labels = [item["label"] for item in result["items"]]
        assert labels == sorted(labels, key=str.lower)

    async def test_sort_by_name_desc(self, test_campaign: str):
        await db_create_entity(campaign_id=test_campaign, label="Zebra2")
        await db_create_entity(campaign_id=test_campaign, label="Alpha2")
        result = await db_list_entities(test_campaign, sort_by="name", order="desc", limit=0)
        labels = [item["label"] for item in result["items"]]
        assert labels == sorted(labels, key=str.lower, reverse=True)

    async def test_sort_by_created_at(self, test_campaign: str):
        await db_create_entity(campaign_id=test_campaign, label=f"First-{uuid.uuid4().hex[:6]}")
        await db_create_entity(campaign_id=test_campaign, label=f"Second-{uuid.uuid4().hex[:6]}")
        result = await db_list_entities(test_campaign, sort_by="created_at", order="asc", limit=0)
        dates = [item["created_at"] for item in result["items"]]
        assert dates == sorted(dates)

    async def test_sort_by_score(self, test_campaign: str):
        """Sort by score LEFT JOINs entity_scores. Entities with no score get 0."""
        e1 = await db_create_entity(campaign_id=test_campaign, label=f"ScoreSort1-{uuid.uuid4().hex[:6]}")
        e2 = await db_create_entity(campaign_id=test_campaign, label=f"ScoreSort2-{uuid.uuid4().hex[:6]}")
        # Insert a score for e2 only
        async with _acquire() as conn:
            await conn.execute(
                """INSERT INTO playbook.entity_scores (entity_id, campaign_id, total_score)
                   VALUES ($1::uuid, $2::uuid, 95.0)""",
                e2["id"], test_campaign,
            )
        result = await db_list_entities(test_campaign, sort_by="score", order="desc", limit=0)
        # e2 should come first (score=95 > 0)
        items = result["items"]
        scored_ids = [i["id"] for i in items]
        assert scored_ids.index(e2["id"]) < scored_ids.index(e1["id"])

    async def test_default_sort_is_created_at_asc(self, test_campaign: str):
        """Without sort params, default is created_at ASC."""
        await db_create_entity(campaign_id=test_campaign, label=f"Default1-{uuid.uuid4().hex[:6]}")
        await db_create_entity(campaign_id=test_campaign, label=f"Default2-{uuid.uuid4().hex[:6]}")
        result = await db_list_entities(test_campaign, limit=0)
        dates = [item["created_at"] for item in result["items"]]
        assert dates == sorted(dates)

    async def test_invalid_sort_column_falls_back(self, test_campaign: str):
        """An unrecognized sort_by value falls back to created_at."""
        await db_create_entity(campaign_id=test_campaign, label=f"Fallback-{uuid.uuid4().hex[:6]}")
        result = await db_list_entities(test_campaign, sort_by="invalid_column", limit=0)
        assert "items" in result  # Should not raise

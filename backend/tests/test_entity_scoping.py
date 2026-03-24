"""Tests for the Entity Scoping and Import Pipeline fixes (m-clone-7pt).

Covers:
  - Library import SQL without NOT EXISTS gwm_id pre-filter (7pt.1)
  - Cross-campaign import SQL without NOT EXISTS gwm_id pre-filter (7pt.2)
  - Bulk create import SQL without NOT EXISTS gwm_id pre-filter (7pt.3)
  - Entity update data integrity (NULLIF/TRIM) (7pt.4)
  - Campaign clone team_id preservation (7pt.5)
  - Structured import response (7pt.7)
  - Library delete returns bool (7pt.9)
  - Error handling fixes (7pt.10)
  - Knowledge cache NULL gwm_id safety (7pt.11)
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.library import (
    db_create_entity_library,
    db_delete_attribute_library,
    db_delete_entity_library,
    db_import_entities_from_library,
    db_update_attribute_library,
    db_update_entity_library,
)
from app.db.campaigns import db_clone_campaign, db_import_entities
from app.db.entities import db_bulk_create_entities, db_update_entity
from app.db.knowledge import (
    db_check_staleness_batch,
    db_lookup_knowledge,
    db_lookup_knowledge_batch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_entity_lib(conn, owner_sid: str, label: str,
                             gwm_id: str | None = None,
                             team_id: str | None = None) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.entity_library (owner_sid, team_id, label, gwm_id)
        VALUES ($1, $2::uuid, $3, $4) RETURNING id
        """,
        owner_sid, team_id, label, gwm_id,
    )
    return str(row["id"])


async def _create_team(conn, creator_sid: str) -> str:
    slug = f"team-{uuid.uuid4().hex[:8]}"
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.teams (slug, display_name, description, created_by)
        VALUES ($1, $2, '', $3) RETURNING id
        """,
        slug, slug, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1::uuid, $2, 'owner')",
        team_id, creator_sid,
    )
    return team_id


# ---------------------------------------------------------------------------
# Task 7pt.1 / 7pt.7: Library import structured result + no NOT EXISTS filter
# ---------------------------------------------------------------------------

class TestLibraryImportStructuredResult:

    async def test_returns_structured_dict(self, test_user_sid, test_campaign):
        """db_import_entities_from_library returns dict with inserted/skipped_count/total_requested."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "Test Entity"))
        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            assert isinstance(result, dict)
            assert "inserted" in result
            assert "skipped_count" in result
            assert "total_requested" in result
            assert result["total_requested"] == 1
            assert len(result["inserted"]) == 1
            assert result["skipped_count"] == 0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.entity_library WHERE id = ANY($1::uuid[])", lib_ids)

    async def test_empty_returns_zero(self, test_user_sid, test_campaign):
        result = await db_import_entities_from_library(test_campaign, [])
        assert result == {"inserted": [], "skipped_count": 0, "total_requested": 0}

    async def test_null_gwm_id_entities_all_import(self, test_user_sid, test_campaign):
        """Multiple entities with NULL gwm_id should all import (no NOT EXISTS filter)."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "User2",
            )
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "Null A", gwm_id=None))
            lib_ids.append(await _insert_entity_lib(conn, sid2, "Null B", gwm_id=None))
        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(result["inserted"]) == 2
            assert result["skipped_count"] == 0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.entity_library WHERE id = ANY($1::uuid[])", lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_ownership_filter(self, test_user_sid, test_campaign):
        """When owner_sid is passed, only matching library rows are imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Other",
            )
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "Mine"))
            lib_ids.append(await _insert_entity_lib(conn, sid2, "Not Mine"))
        try:
            result = await db_import_entities_from_library(
                test_campaign, lib_ids, owner_sid=test_user_sid
            )
            # Only the entry owned by test_user_sid should be imported
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"] == "Mine"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.entity_library WHERE id = ANY($1::uuid[])", lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)


# ---------------------------------------------------------------------------
# Task 7pt.2: Cross-campaign import structured result
# ---------------------------------------------------------------------------

class TestCrossCampaignImportStructuredResult:

    async def test_returns_structured_dict(self, test_user_sid, test_campaign):
        """db_import_entities returns dict with inserted/skipped_count/total_requested."""
        async with _acquire() as conn:
            src_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "source-campaign", test_user_sid,
            )
            src_id = str(src_row["id"])
            await conn.execute(
                "INSERT INTO playbook.entities (campaign_id, label, gwm_id) VALUES ($1::uuid, $2, $3)",
                src_id, "Entity A", "GWM-001",
            )
            await conn.execute(
                "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2)",
                src_id, "Entity B",
            )
        try:
            result = await db_import_entities(test_campaign, src_id)
            assert isinstance(result, dict)
            assert result["total_requested"] == 2
            assert len(result["inserted"]) == 2
            assert result["skipped_count"] == 0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)

    async def test_null_gwm_ids_all_import(self, test_user_sid, test_campaign):
        """Entities with NULL gwm_id should all import from source campaign."""
        async with _acquire() as conn:
            src_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "source-null-gwm", test_user_sid,
            )
            src_id = str(src_row["id"])
            await conn.execute(
                "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2)",
                src_id, "No GWM X",
            )
            await conn.execute(
                "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2)",
                src_id, "No GWM Y",
            )
        try:
            result = await db_import_entities(test_campaign, src_id)
            assert len(result["inserted"]) == 2
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)


# ---------------------------------------------------------------------------
# Task 7pt.3: Bulk create without NOT EXISTS filter
# ---------------------------------------------------------------------------

class TestBulkCreateNoNotExists:

    async def test_mixed_null_and_nonnull_gwm_id(self, test_campaign):
        """Bulk create handles mix of NULL and non-NULL gwm_ids correctly."""
        entities = [
            {"label": "Alpha", "gwm_id": "GWM-ALPHA"},
            {"label": "Beta", "gwm_id": None},
            {"label": "Gamma", "gwm_id": ""},
            {"label": "Delta", "gwm_id": "GWM-DELTA"},
        ]
        result = await db_bulk_create_entities(test_campaign, entities)
        assert len(result["inserted"]) == 4
        assert result["skipped"] == 0

    async def test_null_gwm_ids_not_filtered(self, test_campaign):
        """Two entities with NULL gwm_id should both insert (no pre-filter)."""
        entities = [
            {"label": "First No GWM"},
            {"label": "Second No GWM"},
        ]
        result = await db_bulk_create_entities(test_campaign, entities)
        assert len(result["inserted"]) == 2


# ---------------------------------------------------------------------------
# Task 7pt.4: Entity update data integrity
# ---------------------------------------------------------------------------

class TestEntityUpdateIntegrity:

    async def test_gwm_id_trimmed_and_nullified(self, test_user_sid, test_campaign):
        """db_update_entity applies NULLIF(TRIM()) to gwm_id."""
        from app.db.entities import db_create_entity

        entity = await db_create_entity(test_campaign, "Test Entity", gwm_id="ORIGINAL")
        # Update with whitespace-only gwm_id should become NULL
        updated = await db_update_entity(entity["id"], test_campaign, gwm_id="   ")
        assert updated is not None
        assert updated["gwm_id"] is None

    async def test_label_trimmed(self, test_user_sid, test_campaign):
        """db_update_entity applies TRIM() to label."""
        from app.db.entities import db_create_entity

        entity = await db_create_entity(test_campaign, "Original")
        updated = await db_update_entity(entity["id"], test_campaign, label="  Trimmed  ")
        assert updated is not None
        assert updated["label"] == "Trimmed"

    async def test_library_entity_update_noop_returns_current(self, test_user_sid):
        """db_update_entity_library returns current state on no-op (empty fields)."""
        item = await db_create_entity_library(test_user_sid, None, "Lib Entity", None, None, None)
        result = await db_update_entity_library(item["id"], test_user_sid)
        assert result is not None
        assert result["id"] == item["id"]
        # Cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entity_library WHERE id = $1::uuid", item["id"])

    async def test_library_entity_gwm_id_trimmed(self, test_user_sid):
        """db_update_entity_library applies NULLIF(TRIM()) to gwm_id."""
        item = await db_create_entity_library(test_user_sid, None, "Lib GWM Test", None, "ORIG", None)
        updated = await db_update_entity_library(item["id"], test_user_sid, gwm_id="  ")
        assert updated is not None
        assert updated["gwm_id"] is None
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entity_library WHERE id = $1::uuid", item["id"])

    async def test_attribute_library_update_noop_returns_current(self, test_user_sid):
        """db_update_attribute_library returns current state on no-op."""
        from app.db.library import db_create_attribute_library

        item = await db_create_attribute_library(test_user_sid, None, "Lib Attr", None, 1.0)
        result = await db_update_attribute_library(item["id"], test_user_sid)
        assert result is not None
        assert result["id"] == item["id"]
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attribute_library WHERE id = $1::uuid", item["id"])


# ---------------------------------------------------------------------------
# Task 7pt.5: Campaign clone team_id preservation
# ---------------------------------------------------------------------------

class TestCloneCampaignTeamId:

    async def test_team_campaign_clone_preserves_team_id(self, test_user_sid):
        """Cloning a team campaign preserves the team_id on the new campaign."""
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
            row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid, team_id) VALUES ($1, $2, $3::uuid) RETURNING id",
                "team-campaign", test_user_sid, team_id,
            )
            src_id = str(row["id"])
        try:
            cloned = await db_clone_campaign(src_id, test_user_sid)
            assert cloned["team_id"] == team_id
            assert "(copy)" in cloned["name"]
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", cloned["id"])
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

    async def test_personal_campaign_clone_null_team_id(self, test_user_sid):
        """Cloning a personal campaign keeps team_id as NULL."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "personal-campaign", test_user_sid,
            )
            src_id = str(row["id"])
        try:
            cloned = await db_clone_campaign(src_id, test_user_sid)
            assert cloned.get("team_id") is None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", cloned["id"])
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)


# ---------------------------------------------------------------------------
# Task 7pt.9: Library delete returns bool
# ---------------------------------------------------------------------------

class TestLibraryDeleteReturnsBool:

    async def test_entity_delete_returns_true(self, test_user_sid):
        item = await db_create_entity_library(test_user_sid, None, "To Delete", None, None, None)
        result = await db_delete_entity_library(item["id"], test_user_sid)
        assert result is True

    async def test_entity_delete_returns_false_for_nonexistent(self, test_user_sid):
        fake_id = str(uuid.uuid4())
        result = await db_delete_entity_library(fake_id, test_user_sid)
        assert result is False

    async def test_attribute_delete_returns_true(self, test_user_sid):
        from app.db.library import db_create_attribute_library

        item = await db_create_attribute_library(test_user_sid, None, "To Delete Attr", None, 1.0)
        result = await db_delete_attribute_library(item["id"], test_user_sid)
        assert result is True

    async def test_attribute_delete_returns_false_for_nonexistent(self, test_user_sid):
        fake_id = str(uuid.uuid4())
        result = await db_delete_attribute_library(fake_id, test_user_sid)
        assert result is False


# ---------------------------------------------------------------------------
# Task 7pt.11: Knowledge cache NULL gwm_id safety
# ---------------------------------------------------------------------------

class TestKnowledgeCacheNullGwmId:

    async def test_lookup_with_empty_gwm_id_returns_none(self):
        result = await db_lookup_knowledge("", "some_attr")
        assert result is None

    async def test_lookup_with_whitespace_gwm_id_returns_none(self):
        result = await db_lookup_knowledge("   ", "some_attr")
        assert result is None

    async def test_batch_lookup_filters_all_empty_gwm_ids(self):
        """When ALL gwm_ids are empty, returns empty dict without hitting DB."""
        pairs = [("", "attr1"), ("  ", "attr3")]
        result = await db_lookup_knowledge_batch(pairs)
        assert result == {}

    async def test_staleness_batch_filters_empty_gwm_ids(self):
        pairs = [("", "attr1"), ("  ", "attr2")]
        result = await db_check_staleness_batch(pairs)
        assert result == {}

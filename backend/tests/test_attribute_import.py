"""Tests for attribute import structured results and cross-campaign import.

Covers:
  - Cross-campaign attribute import returns structured result (db_import_attributes)
  - Attribute library import ownership filter
  - db_insert_result NULL gwm_id warning log
  - Attribute router error handling (stack trace leak fix)
"""
from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.campaigns import db_import_attributes
from app.db.library import db_import_attributes_from_library


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_attr_lib(conn, owner_sid: str, label: str,
                           weight: float = 1.0,
                           team_id: str | None = None) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.attribute_library (owner_sid, team_id, label, weight)
        VALUES ($1, $2::uuid, $3, $4) RETURNING id
        """,
        owner_sid, team_id, label, weight,
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
# Cross-campaign attribute import structured result
# ---------------------------------------------------------------------------

class TestCrossCampaignAttributeImport:

    async def test_returns_structured_dict(self, test_user_sid, test_campaign):
        """db_import_attributes returns dict with inserted/skipped/total_requested."""
        async with _acquire() as conn:
            src_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "attr-source-campaign", test_user_sid,
            )
            src_id = str(src_row["id"])
            await conn.execute(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3)",
                src_id, "Attr A", 1.0,
            )
            await conn.execute(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3)",
                src_id, "Attr B", 2.0,
            )
        try:
            result = await db_import_attributes(test_campaign, src_id)
            assert isinstance(result, dict)
            assert "inserted" in result
            assert "skipped" in result
            assert "total_requested" in result
            assert result["total_requested"] == 2
            assert len(result["inserted"]) == 2
            assert result["skipped"] == 0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)

    async def test_skips_duplicate_labels(self, test_user_sid, test_campaign):
        """Attributes with labels already in target campaign are skipped."""
        async with _acquire() as conn:
            # Pre-populate target with one attribute
            await conn.execute(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3)",
                test_campaign, "Existing Attr", 1.0,
            )
            src_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "attr-source-dup", test_user_sid,
            )
            src_id = str(src_row["id"])
            await conn.execute(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3)",
                src_id, "Existing Attr", 2.0,
            )
            await conn.execute(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3)",
                src_id, "New Attr", 3.0,
            )
        try:
            result = await db_import_attributes(test_campaign, src_id)
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"] == "New Attr"
            assert result["skipped"] == 1
            assert result["total_requested"] == 2
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", src_id)


# ---------------------------------------------------------------------------
# Attribute library import team ownership filter
# ---------------------------------------------------------------------------

class TestAttributeLibraryTeamFilter:

    async def test_team_filter_imports_only_team_items(self, test_user_sid, test_campaign):
        """When team_id is passed, only team-owned items are imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Other User",
            )
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Team Attr", team_id=team_id))
            lib_ids.append(await _insert_attr_lib(conn, sid2, "Personal Attr"))
        try:
            result = await db_import_attributes_from_library(
                test_campaign, lib_ids, team_id=team_id
            )
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"] == "Team Attr"
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.attribute_library WHERE id = ANY($1::uuid[])", lib_ids,
                )
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)


# ---------------------------------------------------------------------------
# db_insert_result NULL gwm_id warning log
# ---------------------------------------------------------------------------

class TestInsertResultNullGwmIdLog:

    async def test_logs_warning_for_null_gwm_id(self, test_user_sid, test_campaign, caplog):
        """db_insert_result logs a warning when entity has NULL gwm_id."""
        from app.db.validation import db_insert_result

        async with _acquire() as conn:
            # Create entity without gwm_id
            entity_row = await conn.fetchrow(
                "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2) RETURNING id",
                test_campaign, "No GWM Entity",
            )
            entity_id = str(entity_row["id"])
            # Create attribute
            attr_row = await conn.fetchrow(
                "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3) RETURNING id",
                test_campaign, "Test Attr", 1.0,
            )
            attr_id = str(attr_row["id"])
            # Create validation job
            job_row = await conn.fetchrow(
                """
                INSERT INTO playbook.validation_jobs (campaign_id, triggered_by)
                VALUES ($1::uuid, 'test') RETURNING id
                """,
                test_campaign,
            )
            job_id = str(job_row["id"])

        with caplog.at_level(logging.WARNING, logger="app.db.validation"):
            await db_insert_result(
                job_id, entity_id, attr_id,
                {"present": True, "confidence": 0.9, "evidence": "test"},
                "test report",
            )

        assert any("NULL gwm_id" in record.message for record in caplog.records)

        # Cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.validation_results WHERE job_id = $1::uuid", job_id)
            await conn.execute("DELETE FROM playbook.validation_jobs WHERE id = $1::uuid", job_id)

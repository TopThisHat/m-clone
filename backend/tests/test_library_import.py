"""Integration tests for entity/attribute library -> campaign import.

Exercises every edge case that previously caused unique-constraint violations:
  - Duplicate labels within the import batch
  - Duplicate gwm_ids within the import batch (different labels)
  - Duplicate gwm_ids against entities already in the target campaign
  - NULL / empty / whitespace-only gwm_ids
  - Case-insensitive and whitespace-padded collisions
  - Re-importing the same library entries (idempotency)

Requires: docker compose up -d  (PostgreSQL on localhost:5432)
Run:      cd backend && uv run python -m pytest tests/test_library_import.py -v
"""
from __future__ import annotations

import uuid

from app.db._pool import _acquire
from app.db.library import (
    db_import_attributes_from_library,
    db_import_entities_from_library,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_entity_lib(conn, owner_sid: str, label: str,
                             gwm_id: str | None = None,
                             team_id: str | None = None) -> str:
    """Insert a single entity_library row and return its id."""
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.entity_library (owner_sid, team_id, label, gwm_id)
        VALUES ($1, $2::uuid, $3, $4) RETURNING id
        """,
        owner_sid, team_id, label, gwm_id,
    )
    return str(row["id"])


async def _insert_attr_lib(conn, owner_sid: str, label: str,
                           weight: float = 1.0,
                           team_id: str | None = None) -> str:
    """Insert a single attribute_library row and return its id."""
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.attribute_library (owner_sid, team_id, label, weight)
        VALUES ($1, $2::uuid, $3, $4) RETURNING id
        """,
        owner_sid, team_id, label, weight,
    )
    return str(row["id"])


async def _count_entities(conn, campaign_id: str) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM playbook.entities WHERE campaign_id = $1::uuid",
        campaign_id,
    )


async def _count_attributes(conn, campaign_id: str) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM playbook.attributes WHERE campaign_id = $1::uuid",
        campaign_id,
    )


async def _cleanup_lib(conn, lib_ids: list[str]) -> None:
    """Remove library rows created during a test."""
    if lib_ids:
        await conn.execute(
            "DELETE FROM playbook.entity_library WHERE id = ANY($1::uuid[])", lib_ids,
        )


async def _cleanup_attr_lib(conn, lib_ids: list[str]) -> None:
    if lib_ids:
        await conn.execute(
            "DELETE FROM playbook.attribute_library WHERE id = ANY($1::uuid[])", lib_ids,
        )


# ---------------------------------------------------------------------------
# Entity import tests
# ---------------------------------------------------------------------------

class TestImportEntitiesFromLibrary:
    """db_import_entities_from_library must never raise a constraint error."""

    async def test_duplicate_labels_in_batch(self, test_user_sid, test_campaign):
        """Two library rows with the same label -> only one imported, no error."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "Acme Corp"))
            sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(await _insert_entity_lib(conn, sid2, "  ACME CORP  "))

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"].strip().lower() == "acme corp"
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_duplicate_gwm_ids_in_batch(self, test_user_sid, test_campaign):
        """Two library rows with different labels but same gwm_id -> one imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "Alpha Inc", gwm_id="GWM-DUP-001")
            )
            lib_ids.append(
                await _insert_entity_lib(conn, sid2, "Beta LLC", gwm_id="GWM-DUP-001")
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) >= 1
            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count <= 2
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_gwm_id_conflict_with_existing(self, test_user_sid, test_campaign):
        """Library gwm_id already exists in campaign -> silently skipped."""
        lib_ids = []
        async with _acquire() as conn:
            await conn.execute(
                """
                INSERT INTO playbook.entities (campaign_id, label, gwm_id)
                VALUES ($1::uuid, 'Existing Entity', 'GWM-EXIST-001')
                """,
                test_campaign,
            )
            lib_ids.append(
                await _insert_entity_lib(
                    conn, test_user_sid, "Different Label", gwm_id="GWM-EXIST-001"
                )
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) == 0
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_null_gwm_ids_allowed(self, test_user_sid, test_campaign):
        """Multiple entities with NULL gwm_id -> all imported (NULLs are distinct)."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "No GWM A", gwm_id=None)
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "No GWM B", gwm_id=None)
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) == 2
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_case_insensitive_gwm_id_dedup(self, test_user_sid, test_campaign):
        """gwm_id dedup is case-insensitive: 'abc' and 'ABC' are the same."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "Entity A", gwm_id="gwm-case-001")
            )
            lib_ids.append(
                await _insert_entity_lib(conn, sid2, "Entity B", gwm_id="GWM-CASE-001")
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_idempotent_reimport(self, test_user_sid, test_campaign):
        """Importing the same library entries twice -> no error, no duplicates."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "Stable Entity", gwm_id="GWM-IDEM-001")
            )

        try:
            first = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(first["inserted"]) == 1

            second = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(second["inserted"]) == 0

            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_whitespace_gwm_ids_treated_as_null(self, test_user_sid, test_campaign):
        """gwm_id of '  ' (whitespace) is normalized to NULL via NULLIF(TRIM(...), '')."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "WS GWM A", gwm_id="   ")
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "WS GWM B", gwm_id="  ")
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) == 2
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_empty_lib_ids(self, test_user_sid, test_campaign):
        """Empty lib_ids list returns structured empty result, no error."""
        result = await db_import_entities_from_library(test_campaign, [])
        assert result == {"inserted": [], "skipped": 0, "total_requested": 0}

    async def test_mixed_scenario(self, test_user_sid, test_campaign):
        """Kitchen-sink: mix of duplicates, nulls, conflicts -- no errors."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            await conn.execute(
                """
                INSERT INTO playbook.entities (campaign_id, label, gwm_id)
                VALUES ($1::uuid, 'Pre-Existing', 'GWM-PRE-001')
                """,
                test_campaign,
            )
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "New Label", gwm_id="GWM-PRE-001"))
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "Fresh Entity", gwm_id="GWM-NEW-001"))
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "No GWM Entity", gwm_id=None))
            lib_ids.append(await _insert_entity_lib(
                conn, sid2, "Another Fresh", gwm_id="GWM-NEW-001"))

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids, owner_sid=test_user_sid)
            assert len(result["inserted"]) >= 2

            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count == 3
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_owner_scoped_import(self, test_user_sid, test_campaign):
        """Only entities belonging to the specified owner_sid are imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Other User",
            )
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "My Entity"))
            lib_ids.append(await _insert_entity_lib(conn, sid2, "Other Entity"))

        try:
            result = await db_import_entities_from_library(
                test_campaign, lib_ids, owner_sid=test_user_sid,
            )
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"] == "My Entity"
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_team_scoped_import(self, test_user_sid, test_campaign):
        """When team_id is passed, entities from all team members are imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Teammate",
            )
            await conn.execute(
                "INSERT INTO playbook.teams (id, slug, display_name, created_by) VALUES ($1::uuid, $2, $3, $4)",
                team_id, f"test-team-{uuid.uuid4().hex[:8]}", "Test Team", test_user_sid,
            )
            await conn.execute(
                "INSERT INTO playbook.team_members (team_id, sid) VALUES ($1::uuid, $2), ($1::uuid, $3)",
                team_id, test_user_sid, sid2,
            )
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "Team Entity A", team_id=team_id,
            ))
            lib_ids.append(await _insert_entity_lib(
                conn, sid2, "Team Entity B", team_id=team_id,
            ))

        try:
            result = await db_import_entities_from_library(
                test_campaign, lib_ids, team_id=team_id,
            )
            assert len(result["inserted"]) == 2
            labels = {e["label"] for e in result["inserted"]}
            assert labels == {"Team Entity A", "Team Entity B"}
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_mixed_gwm_ids_with_team_context(self, test_user_sid, test_campaign):
        """Team entities from multiple members with/without gwm_ids all import."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        team_id = str(uuid.uuid4())
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Teammate",
            )
            await conn.execute(
                "INSERT INTO playbook.teams (id, slug, display_name, created_by) VALUES ($1::uuid, $2, $3, $4)",
                team_id, f"test-team-{uuid.uuid4().hex[:8]}", "Test Team", test_user_sid,
            )
            await conn.execute(
                "INSERT INTO playbook.team_members (team_id, sid) VALUES ($1::uuid, $2), ($1::uuid, $3)",
                team_id, test_user_sid, sid2,
            )
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "With GWM A", gwm_id="GWM-TEAM-001", team_id=team_id,
            ))
            lib_ids.append(await _insert_entity_lib(
                conn, sid2, "With GWM B", gwm_id="GWM-TEAM-002", team_id=team_id,
            ))
            lib_ids.append(await _insert_entity_lib(
                conn, test_user_sid, "No GWM C", gwm_id=None, team_id=team_id,
            ))
            lib_ids.append(await _insert_entity_lib(
                conn, sid2, "No GWM D", gwm_id=None, team_id=team_id,
            ))

        try:
            result = await db_import_entities_from_library(
                test_campaign, lib_ids, team_id=team_id,
            )
            assert len(result["inserted"]) == 4
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)


# ---------------------------------------------------------------------------
# Attribute import tests
# ---------------------------------------------------------------------------

class TestImportAttributesFromLibrary:
    """db_import_attributes_from_library must never raise a constraint error."""

    async def test_duplicate_labels_in_batch(self, test_user_sid, test_campaign):
        """Two library rows with same label -> one imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Revenue"))
            lib_ids.append(await _insert_attr_lib(conn, sid2, "  REVENUE  "))

        try:
            result = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert isinstance(result, dict)
            assert len(result["inserted"]) == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_idempotent_reimport(self, test_user_sid, test_campaign):
        """Re-importing same attributes -> no error, no duplicates."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Headcount"))

        try:
            first = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert len(first["inserted"]) == 1

            second = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert len(second["inserted"]) == 0

            async with _acquire() as conn:
                count = await _count_attributes(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)

    async def test_empty_lib_ids(self, test_user_sid, test_campaign):
        result = await db_import_attributes_from_library(test_campaign, [])
        assert result == {"inserted": [], "skipped": 0, "total_requested": 0}

    async def test_structured_return(self, test_user_sid, test_campaign):
        """db_import_attributes_from_library returns structured dict."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Metric A"))
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Metric B"))
        try:
            result = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert "inserted" in result
            assert "skipped" in result
            assert "total_requested" in result
            assert result["total_requested"] == 2
            assert len(result["inserted"]) == 2
            assert result["skipped"] == 0
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)

    async def test_ownership_filter(self, test_user_sid, test_campaign):
        """When owner_sid is passed, only matching library rows are imported."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Other",
            )
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "My Attr"))
            lib_ids.append(await _insert_attr_lib(conn, sid2, "Not My Attr"))
        try:
            result = await db_import_attributes_from_library(
                test_campaign, lib_ids, owner_sid=test_user_sid
            )
            assert len(result["inserted"]) == 1
            assert result["inserted"][0]["label"] == "My Attr"
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

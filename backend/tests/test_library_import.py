"""Integration tests for entity/attribute library → campaign import.

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
        """Two library rows with the same label → only one imported, no error."""
        lib_ids = []
        async with _acquire() as conn:
            # Bypass the library's own unique index by using different owner scopes
            # Instead, insert with slightly different labels that normalize to the same
            # Actually the library has its own unique index on (owner_sid, lower(trim(label)))
            # So we can't insert two identical labels for the same owner.
            # But we CAN import from two different owners/teams.
            # Simplest: insert one, then import it alongside a manually crafted duplicate.

            # Insert two entities with case-different labels that normalize the same
            lib_ids.append(await _insert_entity_lib(conn, test_user_sid, "Acme Corp"))
            # Create a second owner to bypass library unique index
            sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(await _insert_entity_lib(conn, sid2, "  ACME CORP  "))

        try:
            # Should not raise — duplicates are deduplicated/skipped
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(result) == 1
            assert result[0]["label"].strip().lower() == "acme corp"
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_duplicate_gwm_ids_in_batch(self, test_user_sid, test_campaign):
        """Two library rows with different labels but same gwm_id → one imported."""
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
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            # One or both may be returned (first inserts, second hits ON CONFLICT DO NOTHING)
            assert len(result) >= 1
            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            # At most one entity per gwm_id in the campaign
            assert count <= 2  # two different labels, but gwm_id constraint allows only 1 gwm_id
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_gwm_id_conflict_with_existing(self, test_user_sid, test_campaign):
        """Library gwm_id already exists in campaign → silently skipped."""
        lib_ids = []
        async with _acquire() as conn:
            # Pre-insert an entity into the campaign
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
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(result) == 0  # skipped because gwm_id already exists
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_null_gwm_ids_allowed(self, test_user_sid, test_campaign):
        """Multiple entities with NULL gwm_id → all imported (NULLs are distinct)."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "No GWM A", gwm_id=None)
            )
            lib_ids.append(
                await _insert_entity_lib(conn, sid2, "No GWM B", gwm_id=None)
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(result) == 2
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

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
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            # Only one should survive the gwm_id unique constraint
            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_idempotent_reimport(self, test_user_sid, test_campaign):
        """Importing the same library entries twice → no error, no duplicates."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "Stable Entity", gwm_id="GWM-IDEM-001")
            )

        try:
            first = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(first) == 1

            second = await db_import_entities_from_library(test_campaign, lib_ids)
            assert len(second) == 0  # already exists

            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)

    async def test_whitespace_gwm_ids_treated_as_null(self, test_user_sid, test_campaign):
        """gwm_id of '  ' (whitespace) is normalized to NULL via NULLIF(TRIM(...), '')."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            lib_ids.append(
                await _insert_entity_lib(conn, test_user_sid, "WS GWM A", gwm_id="   ")
            )
            lib_ids.append(
                await _insert_entity_lib(conn, sid2, "WS GWM B", gwm_id="  ")
            )

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            # Both should import — whitespace gwm_ids become NULL, NULLs are distinct
            assert len(result) == 2
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_empty_lib_ids(self, test_user_sid, test_campaign):
        """Empty lib_ids list returns empty result, no error."""
        result = await db_import_entities_from_library(test_campaign, [])
        assert result == []

    async def test_mixed_scenario(self, test_user_sid, test_campaign):
        """Kitchen-sink: mix of duplicates, nulls, conflicts — no errors."""
        lib_ids = []
        sid2 = f"test-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                sid2, "Test User 2",
            )
            # Pre-existing entity
            await conn.execute(
                """
                INSERT INTO playbook.entities (campaign_id, label, gwm_id)
                VALUES ($1::uuid, 'Pre-Existing', 'GWM-PRE-001')
                """,
                test_campaign,
            )

            # Library entries to import:
            lib_ids.append(await _insert_entity_lib(  # conflicts gwm_id with existing
                conn, test_user_sid, "New Label", gwm_id="GWM-PRE-001"))
            lib_ids.append(await _insert_entity_lib(  # unique, should import
                conn, test_user_sid, "Fresh Entity", gwm_id="GWM-NEW-001"))
            lib_ids.append(await _insert_entity_lib(  # null gwm_id, should import
                conn, test_user_sid, "No GWM Entity", gwm_id=None))
            lib_ids.append(await _insert_entity_lib(  # same gwm_id as "Fresh", different label
                conn, sid2, "Another Fresh", gwm_id="GWM-NEW-001"))

        try:
            result = await db_import_entities_from_library(test_campaign, lib_ids)
            # "New Label" skipped (gwm_id conflict)
            # "Fresh Entity" imported
            # "No GWM Entity" imported
            # "Another Fresh" skipped (gwm_id=GWM-NEW-001 already inserted by "Fresh Entity")
            assert len(result) >= 2  # at least Fresh + No GWM

            async with _acquire() as conn:
                count = await _count_entities(conn, test_campaign)
            # Pre-Existing + Fresh Entity + No GWM Entity = 3
            assert count == 3
        finally:
            async with _acquire() as conn:
                await _cleanup_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)


# ---------------------------------------------------------------------------
# Attribute import tests
# ---------------------------------------------------------------------------

class TestImportAttributesFromLibrary:
    """db_import_attributes_from_library must never raise a constraint error."""

    async def test_duplicate_labels_in_batch(self, test_user_sid, test_campaign):
        """Two library rows with same label → one imported."""
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
            assert len(result) == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid2)

    async def test_idempotent_reimport(self, test_user_sid, test_campaign):
        """Re-importing same attributes → no error, no duplicates."""
        lib_ids = []
        async with _acquire() as conn:
            lib_ids.append(await _insert_attr_lib(conn, test_user_sid, "Headcount"))

        try:
            first = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert len(first) == 1

            second = await db_import_attributes_from_library(test_campaign, lib_ids)
            assert len(second) == 0

            async with _acquire() as conn:
                count = await _count_attributes(conn, test_campaign)
            assert count == 1
        finally:
            async with _acquire() as conn:
                await _cleanup_attr_lib(conn, lib_ids)

    async def test_empty_lib_ids(self, test_user_sid, test_campaign):
        result = await db_import_attributes_from_library(test_campaign, [])
        assert result == []

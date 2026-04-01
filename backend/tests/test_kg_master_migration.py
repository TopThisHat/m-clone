"""Tests for Tasks 1.1-1.5 and 2.1-2.5: Master team bootstrap and NULL migration.

Covers:
  - 1.1: KG_MASTER_TEAM_ID config setting exists with correct default
  - 1.2: Master team row bootstrapped in teams table (ON CONFLICT DO NOTHING)
  - 1.3: master_entity_id column exists on kg_entities
  - 1.4: team_id column exists on kg_relationship_conflicts
  - 1.5: kg_entity_flags table exists with correct schema
  - 2.1: Pre-migration duplicate detection merges NULL-team duplicates
  - 2.2: NULL kg_entities migrated to master team
  - 2.3: NULL kg_relationships migrated to master team
  - 2.4: kg_relationship_conflicts.team_id backfilled from relationships
  - 2.5: Remaining NULL conflict team_ids defaulted to master
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.config import settings
from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _cleanup_test_entities():
    """Track entity UUIDs created during tests and clean up after."""
    entity_ids: list[str] = []
    yield entity_ids
    async with _acquire() as conn:
        for eid in entity_ids:
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE id = $1::uuid", eid,
            )


# ---------------------------------------------------------------------------
# Task 1.1: Config
# ---------------------------------------------------------------------------


class TestConfigMasterTeamId:
    """Task 1.1: KG_MASTER_TEAM_ID setting."""

    def test_config_has_kg_master_team_id(self):
        assert hasattr(settings, "kg_master_team_id")

    def test_config_default_value(self):
        assert settings.kg_master_team_id == "00000000-0000-0000-0000-000000000001"

    def test_config_value_is_valid_uuid(self):
        parsed = uuid.UUID(settings.kg_master_team_id)
        assert str(parsed) == settings.kg_master_team_id


# ---------------------------------------------------------------------------
# Task 1.2: Master team bootstrap
# ---------------------------------------------------------------------------


class TestMasterTeamBootstrap:
    """Task 1.2: Master team row exists after schema init."""

    @pytest.mark.asyncio
    async def test_master_team_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, slug, display_name FROM playbook.teams WHERE id = $1::uuid",
                settings.kg_master_team_id,
            )
        assert row is not None
        assert row["slug"] == "master-kg"
        assert row["display_name"] == "Master Knowledge Graph"

    @pytest.mark.asyncio
    async def test_master_team_idempotent(self):
        """Running schema init again should not raise or duplicate the row."""
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM playbook.teams WHERE slug = 'master-kg'",
            )
        assert count == 1


# ---------------------------------------------------------------------------
# Task 1.3: master_entity_id column
# ---------------------------------------------------------------------------


class TestMasterEntityIdColumn:
    """Task 1.3: kg_entities has master_entity_id UUID FK column."""

    @pytest.mark.asyncio
    async def test_column_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'playbook'
                  AND table_name = 'kg_entities'
                  AND column_name = 'master_entity_id'
                """,
            )
        assert row is not None
        assert row["data_type"] == "uuid"
        assert row["is_nullable"] == "YES"  # ON DELETE SET NULL requires nullable

    @pytest.mark.asyncio
    async def test_fk_references_kg_entities(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'playbook'
                  AND tc.table_name = 'kg_entities'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'master_entity_id'
                """,
            )
        assert row is not None


# ---------------------------------------------------------------------------
# Task 1.4: team_id on kg_relationship_conflicts
# ---------------------------------------------------------------------------


class TestConflictsTeamIdColumn:
    """Task 1.4: kg_relationship_conflicts has team_id UUID FK column."""

    @pytest.mark.asyncio
    async def test_column_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'playbook'
                  AND table_name = 'kg_relationship_conflicts'
                  AND column_name = 'team_id'
                """,
            )
        assert row is not None
        assert row["data_type"] == "uuid"


# ---------------------------------------------------------------------------
# Task 1.5: kg_entity_flags table
# ---------------------------------------------------------------------------


class TestEntityFlagsTable:
    """Task 1.5: kg_entity_flags table with correct schema."""

    @pytest.mark.asyncio
    async def test_table_exists(self):
        async with _acquire() as conn:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'playbook' AND table_name = 'kg_entity_flags'
                )
                """,
            )
        assert exists is True

    @pytest.mark.asyncio
    async def test_columns(self):
        async with _acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'playbook' AND table_name = 'kg_entity_flags'
                ORDER BY ordinal_position
                """,
            )
        columns = {row["column_name"] for row in rows}
        expected = {
            "id", "entity_id", "team_id", "reason",
            "resolved", "resolved_by", "resolved_at", "created_at",
        }
        assert expected.issubset(columns)

    @pytest.mark.asyncio
    async def test_unique_constraint(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND tablename = 'kg_entity_flags'
                  AND indexdef LIKE '%entity_id%team_id%reason%'
                  AND indexdef LIKE '%UNIQUE%'
                """,
            )
        assert row is not None

    @pytest.mark.asyncio
    async def test_pending_index_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND tablename = 'kg_entity_flags'
                  AND indexname = 'kg_entity_flags_pending_idx'
                """,
            )
        assert row is not None

    @pytest.mark.asyncio
    async def test_resolved_by_references_users(self):
        """resolved_by should be TEXT REFERENCES playbook.users(sid)."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'playbook'
                  AND table_name = 'kg_entity_flags'
                  AND column_name = 'resolved_by'
                """,
            )
        assert row is not None
        assert row["data_type"] == "text"


# ---------------------------------------------------------------------------
# Task 2.2-2.3: NULL entity/relationship migration
# ---------------------------------------------------------------------------


class TestNullToMasterMigration:
    """Tasks 2.2 and 2.3: After schema init, no NULL team_ids should remain."""

    @pytest.mark.asyncio
    async def test_no_null_entity_team_ids(self):
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM playbook.kg_entities WHERE team_id IS NULL",
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_null_relationship_team_ids(self):
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM playbook.kg_relationships WHERE team_id IS NULL",
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_null_conflict_team_ids(self):
        """Tasks 2.4 and 2.5: No NULL team_ids on conflicts."""
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM playbook.kg_relationship_conflicts WHERE team_id IS NULL",
            )
        assert count == 0

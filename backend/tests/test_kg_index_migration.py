"""Tests for Tasks 3.1-3.9: Team-scoped unique indexes and CHECK constraints.

Covers:
  - 3.1: Old COALESCE-based kg_entities_name_team_unique and kg_entities_name_idx dropped
  - 3.2: Clean kg_entities_name_team_unique on (LOWER(name), team_id) created
  - 3.3: Old non-team-scoped kg_rel_active_family_idx dropped
  - 3.4: Team-scoped kg_rel_active_family_team_idx created
  - 3.5: kg_rel_team_check PG function exists and validates correctly
  - 3.6: kg_rel_intra_team_check CHECK constraint on kg_relationships
  - 3.7: ON DELETE RESTRICT on team FK for kg_entities and kg_relationships
  - 3.8: NOT NULL on kg_entities.team_id and kg_relationships.team_id
  - 3.9: Performance indexes created
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest
import pytest_asyncio

from app.config import settings
from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MASTER_TEAM_ID = settings.kg_master_team_id


async def _create_test_team(conn: asyncpg.Connection) -> str:
    """Create a disposable team and return its UUID string."""
    team_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO playbook.teams (id, slug, display_name)
        VALUES ($1::uuid, $2, $3)
        """,
        team_id,
        f"test-team-{team_id[:8]}",
        f"Test Team {team_id[:8]}",
    )
    return team_id


async def _create_entity(
    conn: asyncpg.Connection, name: str, team_id: str, entity_type: str = "COMPANY",
) -> str:
    """Insert a kg_entity and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.kg_entities (name, entity_type, team_id)
        VALUES ($1, $2, $3::uuid)
        RETURNING id
        """,
        name,
        entity_type,
        team_id,
    )
    return str(row["id"])


async def _create_relationship(
    conn: asyncpg.Connection,
    subject_id: str,
    object_id: str,
    team_id: str,
    predicate: str = "OWNS",
    predicate_family: str = "OWNERSHIP",
) -> str:
    """Insert a kg_relationship and return its UUID string."""
    row = await conn.fetchrow(
        """
        INSERT INTO playbook.kg_relationships
            (subject_id, predicate, predicate_family, object_id, team_id)
        VALUES ($1::uuid, $2, $3, $4::uuid, $5::uuid)
        RETURNING id
        """,
        subject_id,
        predicate,
        predicate_family,
        object_id,
        team_id,
    )
    return str(row["id"])


@pytest_asyncio.fixture
async def test_team():
    """Create a throwaway team, yield its id, clean up after."""
    async with _acquire() as conn:
        team_id = await _create_test_team(conn)
    yield team_id
    async with _acquire() as conn:
        # Remove all KG data referencing this team before deleting the team
        await conn.execute(
            "DELETE FROM playbook.kg_relationship_conflicts WHERE team_id = $1::uuid",
            team_id,
        )
        await conn.execute(
            "DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid", team_id,
        )
        await conn.execute(
            "DELETE FROM playbook.kg_entity_flags WHERE team_id = $1::uuid", team_id,
        )
        await conn.execute(
            "DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid", team_id,
        )
        await conn.execute(
            "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id,
        )


@pytest_asyncio.fixture
async def two_teams():
    """Create two throwaway teams, yield (team_a_id, team_b_id), clean up."""
    async with _acquire() as conn:
        team_a = await _create_test_team(conn)
        team_b = await _create_test_team(conn)
    yield team_a, team_b
    async with _acquire() as conn:
        for tid in (team_a, team_b):
            await conn.execute(
                "DELETE FROM playbook.kg_relationship_conflicts WHERE team_id = $1::uuid",
                tid,
            )
            await conn.execute(
                "DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid", tid,
            )
            await conn.execute(
                "DELETE FROM playbook.kg_entity_flags WHERE team_id = $1::uuid", tid,
            )
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid", tid,
            )
            await conn.execute(
                "DELETE FROM playbook.teams WHERE id = $1::uuid", tid,
            )


# ---------------------------------------------------------------------------
# Task 3.1: Old indexes dropped
# ---------------------------------------------------------------------------


class TestOldIndexesDropped:
    """Task 3.1: COALESCE-based and old plain name indexes are gone."""

    @pytest.mark.asyncio
    async def test_old_coalesce_index_not_using_coalesce(self):
        """The kg_entities_name_team_unique index should not contain COALESCE."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_entities_name_team_unique'
                """,
            )
        assert row is not None
        assert "COALESCE" not in row["indexdef"].upper()

    @pytest.mark.asyncio
    async def test_old_name_only_index_dropped(self):
        """The old kg_entities_name_idx (LOWER(name) only) should not exist."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_entities_name_idx'
                """,
            )
        assert row is None


# ---------------------------------------------------------------------------
# Task 3.2: Clean team-scoped entity unique index
# ---------------------------------------------------------------------------


class TestEntityNameTeamUnique:
    """Task 3.2: Unique index on (LOWER(name), team_id)."""

    @pytest.mark.asyncio
    async def test_index_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_entities_name_team_unique'
                """,
            )
        assert row is not None
        defn = row["indexdef"].upper()
        assert "UNIQUE" in defn
        assert "LOWER" in defn
        assert "TEAM_ID" in defn

    @pytest.mark.asyncio
    async def test_same_name_different_teams_allowed(self, two_teams):
        """Two teams MAY have entities with the same name."""
        team_a, team_b = two_teams
        async with _acquire() as conn:
            eid_a = await _create_entity(conn, "Apple Inc", team_a)
            eid_b = await _create_entity(conn, "Apple Inc", team_b)
        assert eid_a != eid_b

    @pytest.mark.asyncio
    async def test_same_name_same_team_rejected(self, test_team):
        """Same team duplicate name is rejected by the unique index."""
        async with _acquire() as conn:
            await _create_entity(conn, "Apple Inc", test_team)
            with pytest.raises(asyncpg.UniqueViolationError):
                await _create_entity(conn, "Apple Inc", test_team)

    @pytest.mark.asyncio
    async def test_case_insensitive(self, test_team):
        """LOWER(name) means 'apple inc' and 'Apple Inc' collide."""
        async with _acquire() as conn:
            await _create_entity(conn, "apple inc", test_team)
            with pytest.raises(asyncpg.UniqueViolationError):
                await _create_entity(conn, "APPLE INC", test_team)


# ---------------------------------------------------------------------------
# Task 3.3: Old relationship index dropped
# ---------------------------------------------------------------------------


class TestOldRelIndexDropped:
    """Task 3.3: Non-team-scoped kg_rel_active_family_idx is gone."""

    @pytest.mark.asyncio
    async def test_old_rel_index_dropped(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_rel_active_family_idx'
                """,
            )
        assert row is None


# ---------------------------------------------------------------------------
# Task 3.4: Team-scoped relationship unique index
# ---------------------------------------------------------------------------


class TestRelActiveTeamUnique:
    """Task 3.4: Unique index on (subject_id, object_id, predicate_family, team_id) WHERE is_active."""

    @pytest.mark.asyncio
    async def test_index_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_rel_active_family_team_idx'
                """,
            )
        assert row is not None
        defn = row["indexdef"].upper()
        assert "UNIQUE" in defn
        assert "SUBJECT_ID" in defn
        assert "OBJECT_ID" in defn
        assert "PREDICATE_FAMILY" in defn
        assert "TEAM_ID" in defn
        assert "IS_ACTIVE" in defn

    @pytest.mark.asyncio
    async def test_same_rel_different_teams_allowed(self, two_teams):
        """Two teams can have the same relationship pattern."""
        team_a, team_b = two_teams
        async with _acquire() as conn:
            sa = await _create_entity(conn, "SubjectA", team_a)
            oa = await _create_entity(conn, "ObjectA", team_a)
            sb = await _create_entity(conn, "SubjectA", team_b)
            ob = await _create_entity(conn, "ObjectA", team_b)

            rid_a = await _create_relationship(conn, sa, oa, team_a)
            rid_b = await _create_relationship(conn, sb, ob, team_b)
        assert rid_a != rid_b

    @pytest.mark.asyncio
    async def test_duplicate_active_rel_same_team_rejected(self, test_team):
        """Duplicate active relationship within same team is rejected."""
        async with _acquire() as conn:
            s = await _create_entity(conn, "SubDup", test_team)
            o = await _create_entity(conn, "ObjDup", test_team)
            await _create_relationship(conn, s, o, test_team)
            with pytest.raises(asyncpg.UniqueViolationError):
                await _create_relationship(conn, s, o, test_team)


# ---------------------------------------------------------------------------
# Task 3.5: kg_rel_team_check function
# ---------------------------------------------------------------------------


class TestKgRelTeamCheckFunction:
    """Task 3.5: PG function validates both endpoints belong to same team."""

    @pytest.mark.asyncio
    async def test_function_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT routine_name FROM information_schema.routines
                WHERE routine_schema = 'playbook'
                  AND routine_name = 'kg_rel_team_check'
                """,
            )
        assert row is not None

    @pytest.mark.asyncio
    async def test_returns_true_for_same_team(self, test_team):
        """Both entities in same team returns TRUE."""
        async with _acquire() as conn:
            eid1 = await _create_entity(conn, "CheckEnt1", test_team)
            eid2 = await _create_entity(conn, "CheckEnt2", test_team)
            result = await conn.fetchval(
                "SELECT playbook.kg_rel_team_check($1::uuid, $2::uuid, $3::uuid)",
                eid1,
                eid2,
                test_team,
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_cross_team(self, two_teams):
        """Subject in team_a, object in team_b returns FALSE."""
        team_a, team_b = two_teams
        async with _acquire() as conn:
            eid_a = await _create_entity(conn, "CrossA", team_a)
            eid_b = await _create_entity(conn, "CrossB", team_b)
            result = await conn.fetchval(
                "SELECT playbook.kg_rel_team_check($1::uuid, $2::uuid, $3::uuid)",
                eid_a,
                eid_b,
                team_a,
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_wrong_team(self, two_teams):
        """Both entities in team_a but checking against team_b returns FALSE."""
        team_a, team_b = two_teams
        async with _acquire() as conn:
            eid1 = await _create_entity(conn, "WrongTeam1", team_a)
            eid2 = await _create_entity(conn, "WrongTeam2", team_a)
            result = await conn.fetchval(
                "SELECT playbook.kg_rel_team_check($1::uuid, $2::uuid, $3::uuid)",
                eid1,
                eid2,
                team_b,
            )
        assert result is False


# ---------------------------------------------------------------------------
# Task 3.6: CHECK constraint on kg_relationships
# ---------------------------------------------------------------------------


class TestIntraTeamCheckConstraint:
    """Task 3.6: CHECK constraint blocks cross-team relationship inserts."""

    @pytest.mark.asyncio
    async def test_constraint_exists(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT conname FROM pg_constraint
                WHERE conname = 'kg_rel_intra_team_check'
                  AND conrelid = 'playbook.kg_relationships'::regclass
                """,
            )
        assert row is not None

    @pytest.mark.asyncio
    async def test_cross_team_insert_rejected(self, two_teams):
        """Inserting a relationship with cross-team endpoints raises CheckViolationError."""
        team_a, team_b = two_teams
        async with _acquire() as conn:
            eid_a = await _create_entity(conn, "CrossRelA", team_a)
            eid_b = await _create_entity(conn, "CrossRelB", team_b)
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    """
                    INSERT INTO playbook.kg_relationships
                        (subject_id, predicate, predicate_family, object_id, team_id)
                    VALUES ($1::uuid, 'OWNS', 'OWNERSHIP', $2::uuid, $3::uuid)
                    """,
                    eid_a,
                    eid_b,
                    team_a,
                )

    @pytest.mark.asyncio
    async def test_valid_intra_team_insert_succeeds(self, test_team):
        """Valid intra-team relationship inserts without error."""
        async with _acquire() as conn:
            s = await _create_entity(conn, "ValidSub", test_team)
            o = await _create_entity(conn, "ValidObj", test_team)
            rid = await _create_relationship(conn, s, o, test_team)
        assert rid is not None


# ---------------------------------------------------------------------------
# Task 3.7: ON DELETE RESTRICT for team FK
# ---------------------------------------------------------------------------


class TestTeamDeletionGuard:
    """Task 3.7: ON DELETE RESTRICT prevents team deletion when KG data exists."""

    @pytest.mark.asyncio
    async def test_entity_fk_is_restrict(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT rc.delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                  ON tc.constraint_name = rc.constraint_name
                  AND tc.table_schema = rc.constraint_schema
                WHERE tc.table_schema = 'playbook'
                  AND tc.table_name = 'kg_entities'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'team_id'
                """,
            )
        assert row is not None
        assert row["delete_rule"] == "RESTRICT"

    @pytest.mark.asyncio
    async def test_relationship_fk_is_restrict(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT rc.delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                  ON tc.constraint_name = rc.constraint_name
                  AND tc.table_schema = rc.constraint_schema
                WHERE tc.table_schema = 'playbook'
                  AND tc.table_name = 'kg_relationships'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'team_id'
                """,
            )
        assert row is not None
        assert row["delete_rule"] == "RESTRICT"

    @pytest.mark.asyncio
    async def test_delete_team_with_entities_blocked(self, test_team):
        """Deleting a team that has KG entities should fail."""
        async with _acquire() as conn:
            await _create_entity(conn, "GuardedEntity", test_team)
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", test_team,
                )

    @pytest.mark.asyncio
    async def test_delete_team_with_no_kg_data_succeeds(self):
        """Deleting a team with zero KG data should succeed."""
        async with _acquire() as conn:
            empty_team = await _create_test_team(conn)
            await conn.execute(
                "DELETE FROM playbook.teams WHERE id = $1::uuid", empty_team,
            )
            row = await conn.fetchrow(
                "SELECT 1 FROM playbook.teams WHERE id = $1::uuid", empty_team,
            )
        assert row is None


# ---------------------------------------------------------------------------
# Task 3.8: NOT NULL on team_id
# ---------------------------------------------------------------------------


class TestTeamIdNotNull:
    """Task 3.8: kg_entities.team_id and kg_relationships.team_id are NOT NULL."""

    @pytest.mark.asyncio
    async def test_entity_team_id_not_null(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_nullable FROM information_schema.columns
                WHERE table_schema = 'playbook'
                  AND table_name = 'kg_entities'
                  AND column_name = 'team_id'
                """,
            )
        assert row is not None
        assert row["is_nullable"] == "NO"

    @pytest.mark.asyncio
    async def test_relationship_team_id_not_null(self):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_nullable FROM information_schema.columns
                WHERE table_schema = 'playbook'
                  AND table_name = 'kg_relationships'
                  AND column_name = 'team_id'
                """,
            )
        assert row is not None
        assert row["is_nullable"] == "NO"

    @pytest.mark.asyncio
    async def test_insert_entity_without_team_rejected(self):
        """Inserting an entity with NULL team_id should fail."""
        async with _acquire() as conn:
            with pytest.raises(asyncpg.NotNullViolationError):
                await conn.execute(
                    """
                    INSERT INTO playbook.kg_entities (name, entity_type, team_id)
                    VALUES ('NoTeam', 'COMPANY', NULL)
                    """,
                )


# ---------------------------------------------------------------------------
# Task 3.9: Performance indexes
# ---------------------------------------------------------------------------


class TestPerformanceIndexes:
    """Task 3.9: All performance indexes exist."""

    EXPECTED_INDEXES = [
        ("kg_entities", "kg_entities_team_name_idx"),
        ("kg_entities", "kg_entities_team_type_idx"),
        ("kg_entities", "kg_entities_team_updated_idx"),
        ("kg_entities", "kg_entities_master_entity_idx"),
        ("kg_relationships", "kg_rel_team_subject_idx"),
        ("kg_relationships", "kg_rel_team_object_idx"),
        ("kg_relationship_conflicts", "kg_conflicts_team_detected_idx"),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("table,index_name", EXPECTED_INDEXES)
    async def test_index_exists(self, table: str, index_name: str):
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexname, indexdef FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND tablename = $1
                  AND indexname = $2
                """,
                table,
                index_name,
            )
        assert row is not None, f"Index {index_name} not found on {table}"

    @pytest.mark.asyncio
    async def test_team_name_idx_has_lower(self):
        """kg_entities_team_name_idx should use LOWER(name)."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE indexname = 'kg_entities_team_name_idx'
                """,
            )
        assert row is not None
        assert "lower" in row["indexdef"].lower()

    @pytest.mark.asyncio
    async def test_team_updated_idx_desc(self):
        """kg_entities_team_updated_idx should include DESC."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE indexname = 'kg_entities_team_updated_idx'
                """,
            )
        assert row is not None
        assert "DESC" in row["indexdef"]

    @pytest.mark.asyncio
    async def test_master_entity_idx_is_partial(self):
        """kg_entities_master_entity_idx should be partial (WHERE master_entity_id IS NOT NULL)."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE indexname = 'kg_entities_master_entity_idx'
                """,
            )
        assert row is not None
        assert "WHERE" in row["indexdef"]
        assert "master_entity_id IS NOT NULL" in row["indexdef"]

    @pytest.mark.asyncio
    async def test_conflicts_idx_is_partial(self):
        """kg_conflicts_team_detected_idx should be partial."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef FROM pg_indexes
                WHERE indexname = 'kg_conflicts_team_detected_idx'
                """,
            )
        assert row is not None
        assert "WHERE" in row["indexdef"]
        assert "team_id IS NOT NULL" in row["indexdef"]

    @pytest.mark.asyncio
    async def test_flags_pending_idx_already_exists(self):
        """Phase 1 created kg_entity_flags_pending_idx — verify it survived."""
        async with _acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'playbook'
                  AND indexname = 'kg_entity_flags_pending_idx'
                """,
            )
        assert row is not None


# ---------------------------------------------------------------------------
# Integration: Idempotency
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    """Running the migration multiple times should not error."""

    @pytest.mark.asyncio
    async def test_schema_init_idempotent(self):
        """Re-running init_schema should not raise any errors."""
        from app.db import init_schema
        # If this raises, the migration is not idempotent
        await init_schema()

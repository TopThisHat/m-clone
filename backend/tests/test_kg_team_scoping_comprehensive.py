"""Comprehensive KG team-scoping tests (m-clone-qxfb).

Covers tasks 8.1-8.10:
  8.1  — Team isolation (entities and relationships invisible across teams)
  8.2  — Resolution modes (team_hit, team_alias_hit, master_copy, created)
  8.3  — Intra-team constraint (cross-team relationships rejected)
  8.4  — Concurrent extraction (two workers resolve same entity simultaneously)
  8.5  — API authorization (master team gate, super admin bypass)
  8.6  — Team deletion guard (RESTRICT prevents deleting teams with KG data)
  8.7  — Entity flags (auto-flag on master_copy, list, resolve)
  8.8  — Migration validation (no NULL team_id, unique index enforcement)
  8.9  — Promote/sync/merge operations
  8.10 — Relationship dedup across teams
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
import pytest_asyncio

from app.config import settings
from app.db._pool import _acquire
from app.db.knowledge_graph import (
    db_find_or_create_entity,
    db_flag_entity_for_review,
    db_get_entity_relationships,
    db_list_entity_flags,
    db_list_kg_entities,
    db_merge_kg_entities,
    db_promote_entity_to_master,
    db_resolve_entity_flag,
    db_sync_entity_from_master,
    db_upsert_relationship,
)

MASTER_TEAM_ID = settings.kg_master_team_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

async def _make_team(conn: asyncpg.Connection, creator_sid: str) -> str:
    """Create a team and add the creator as admin. Returns team_id as str."""
    slug = f"team-{uuid.uuid4().hex[:8]}"
    row = await conn.fetchrow(
        "INSERT INTO playbook.teams (slug, display_name, description, created_by) "
        "VALUES ($1, $2, '', $3) RETURNING id",
        slug, slug, creator_sid,
    )
    team_id = str(row["id"])
    await conn.execute(
        "INSERT INTO playbook.team_members (team_id, sid, role) "
        "VALUES ($1::uuid, $2, 'admin')",
        team_id, creator_sid,
    )
    return team_id


async def _cleanup_team(conn: asyncpg.Connection, team_id: str) -> None:
    """Remove all KG data and then the team itself."""
    await conn.execute(
        "DELETE FROM playbook.kg_entity_flags WHERE team_id = $1::uuid", team_id,
    )
    await conn.execute(
        "DELETE FROM playbook.kg_relationship_conflicts WHERE team_id = $1::uuid", team_id,
    )
    await conn.execute(
        "DELETE FROM playbook.kg_relationships WHERE team_id = $1::uuid", team_id,
    )
    await conn.execute(
        "DELETE FROM playbook.kg_entities WHERE team_id = $1::uuid", team_id,
    )
    await conn.execute(
        "DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id,
    )
    await conn.execute(
        "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id,
    )


@pytest_asyncio.fixture
async def two_teams(test_user_sid: str):
    """Create two isolated teams, each with two entities and a relationship.

    Yields a dict with team_a_id, team_b_id, entity ids, and the user sid.
    Cleans up all data afterward.
    """
    async with _acquire() as conn:
        team_a = await _make_team(conn, test_user_sid)
        team_b = await _make_team(conn, test_user_sid)

    # Team A entities
    ea1, _ = await db_find_or_create_entity(
        "Acme Corp", "organization", ["ACME"], team_id=team_a,
    )
    ea2, _ = await db_find_or_create_entity(
        "Jane Doe", "person", [], team_id=team_a,
    )
    await db_upsert_relationship(
        subject_id=ea2, predicate="works_at", predicate_family="employment",
        object_id=ea1, confidence=0.9, evidence="test",
        source_session_id=None, team_id=team_a,
    )

    # Team B entities
    eb1, _ = await db_find_or_create_entity(
        "Globex Inc", "organization", ["Globex"], team_id=team_b,
    )
    eb2, _ = await db_find_or_create_entity(
        "John Smith", "person", [], team_id=team_b,
    )
    await db_upsert_relationship(
        subject_id=eb2, predicate="works_at", predicate_family="employment",
        object_id=eb1, confidence=0.85, evidence="test",
        source_session_id=None, team_id=team_b,
    )

    yield {
        "team_a_id": team_a,
        "team_b_id": team_b,
        "team_a_entity_1": ea1,  # Acme Corp
        "team_a_entity_2": ea2,  # Jane Doe
        "team_b_entity_1": eb1,  # Globex Inc
        "team_b_entity_2": eb2,  # John Smith
        "user_sid": test_user_sid,
    }

    # Cleanup both teams
    async with _acquire() as conn:
        await _cleanup_team(conn, team_a)
        await _cleanup_team(conn, team_b)


@pytest_asyncio.fixture
async def single_team(test_user_sid: str):
    """Create a single team. Yields (team_id, user_sid). Cleans up after."""
    async with _acquire() as conn:
        team_id = await _make_team(conn, test_user_sid)

    yield {"team_id": team_id, "user_sid": test_user_sid}

    async with _acquire() as conn:
        await _cleanup_team(conn, team_id)


# ---------------------------------------------------------------------------
# 8.1: Team isolation tests
# ---------------------------------------------------------------------------

class TestTeamIsolation:
    """Entities and relationships are invisible across teams."""

    async def test_team_a_entity_invisible_to_team_b(self, two_teams):
        """db_list_kg_entities for team_a returns only team_a entities."""
        result = await db_list_kg_entities(team_id=two_teams["team_a_id"])
        entity_ids = {e["id"] for e in result["items"]}
        # Team A entities present
        assert two_teams["team_a_entity_1"] in entity_ids
        assert two_teams["team_a_entity_2"] in entity_ids
        # Team B entities absent
        assert two_teams["team_b_entity_1"] not in entity_ids
        assert two_teams["team_b_entity_2"] not in entity_ids

    async def test_team_b_entity_invisible_to_team_a(self, two_teams):
        """db_list_kg_entities for team_b returns only team_b entities."""
        result = await db_list_kg_entities(team_id=two_teams["team_b_id"])
        entity_ids = {e["id"] for e in result["items"]}
        assert two_teams["team_b_entity_1"] in entity_ids
        assert two_teams["team_b_entity_2"] in entity_ids
        assert two_teams["team_a_entity_1"] not in entity_ids

    async def test_team_a_relationship_invisible_to_team_b(self, two_teams):
        """Relationships for team_a entity queried with team_b scope return empty."""
        rels = await db_get_entity_relationships(
            two_teams["team_a_entity_2"], team_id=two_teams["team_b_id"],
        )
        assert len(rels) == 0

    async def test_team_a_relationship_visible_within_team_a(self, two_teams):
        """Relationships for team_a entity queried with team_a scope are found."""
        rels = await db_get_entity_relationships(
            two_teams["team_a_entity_2"], team_id=two_teams["team_a_id"],
        )
        assert len(rels) >= 1
        predicates = [r["predicate"] for r in rels]
        assert "works_at" in predicates

    async def test_total_count_scoped_to_team(self, two_teams):
        """The total count returned by db_list_kg_entities is team-scoped."""
        result_a = await db_list_kg_entities(team_id=two_teams["team_a_id"])
        result_b = await db_list_kg_entities(team_id=two_teams["team_b_id"])
        assert result_a["total"] == 2
        assert result_b["total"] == 2


# ---------------------------------------------------------------------------
# 8.2: Resolution mode tests
# ---------------------------------------------------------------------------

class TestResolutionModes:
    """The 4-phase resolution: team_hit, team_alias_hit, master_copy, created."""

    async def test_team_hit_existing_entity(self, single_team):
        """Re-resolving an existing entity name returns team_hit."""
        team_id = single_team["team_id"]
        eid_first, mode_first = await db_find_or_create_entity(
            "Alpha Inc", "organization", [], team_id=team_id,
        )
        assert mode_first == "created"

        eid_second, mode_second = await db_find_or_create_entity(
            "Alpha Inc", "organization", [], team_id=team_id,
        )
        assert mode_second == "team_hit"
        assert eid_second == eid_first

    async def test_team_hit_case_insensitive(self, single_team):
        """team_hit is case-insensitive."""
        team_id = single_team["team_id"]
        eid1, _ = await db_find_or_create_entity(
            "Beta Corp", "organization", [], team_id=team_id,
        )
        eid2, mode = await db_find_or_create_entity(
            "beta corp", "organization", [], team_id=team_id,
        )
        assert mode == "team_hit"
        assert eid2 == eid1

    async def test_team_alias_hit(self, single_team):
        """Entity found by alias returns team_alias_hit."""
        team_id = single_team["team_id"]
        eid1, _ = await db_find_or_create_entity(
            "Gamma LLC", "organization", ["gamma"], team_id=team_id,
        )
        eid2, mode = await db_find_or_create_entity(
            "gamma", "organization", [], team_id=team_id,
        )
        assert mode == "team_alias_hit"
        assert eid2 == eid1

    async def test_master_copy_creates_team_entity(self, single_team):
        """Entity in master but not in team returns master_copy with a new entity."""
        team_id = single_team["team_id"]

        # Insert entity directly into master team
        master_name = f"MasterOnlyCo-{uuid.uuid4().hex[:6]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id) "
                "VALUES ($1, 'organization', '{}', $2::uuid)",
                master_name, MASTER_TEAM_ID,
            )

        eid, mode = await db_find_or_create_entity(
            master_name, "organization", [], team_id=team_id,
        )
        assert mode == "master_copy"
        assert eid is not None

        # Verify the new entity has master_entity_id set
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT master_entity_id, team_id FROM playbook.kg_entities WHERE id = $1::uuid",
                eid,
            )
        assert row is not None
        assert str(row["team_id"]) == team_id
        assert row["master_entity_id"] is not None

        # Cleanup master entity
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE LOWER(name) = $1 AND team_id = $2::uuid",
                master_name.lower(), MASTER_TEAM_ID,
            )

    async def test_created_brand_new_entity(self, single_team):
        """Entity that exists nowhere returns created."""
        team_id = single_team["team_id"]
        unique_name = f"NewEntity-{uuid.uuid4().hex[:8]}"
        eid, mode = await db_find_or_create_entity(
            unique_name, "person", [], team_id=team_id,
        )
        assert mode == "created"
        assert eid is not None


# ---------------------------------------------------------------------------
# 8.3: Intra-team constraint test
# ---------------------------------------------------------------------------

class TestIntraTeamConstraint:
    """Cross-team relationships are rejected by the CHECK constraint."""

    async def test_cross_team_relationship_rejected(self, two_teams):
        """Inserting a relationship where subject and object belong to different
        teams returns cross_team_error (CheckViolationError caught by db_upsert)."""
        result = await db_upsert_relationship(
            subject_id=two_teams["team_a_entity_2"],  # Jane Doe (team A)
            predicate="knows",
            predicate_family="social",
            object_id=two_teams["team_b_entity_2"],   # John Smith (team B)
            confidence=0.7,
            evidence="cross-team test",
            source_session_id=None,
            team_id=two_teams["team_a_id"],
        )
        assert result["status"] == "cross_team_error"

    async def test_same_team_relationship_accepted(self, two_teams):
        """A relationship within the same team succeeds."""
        result = await db_upsert_relationship(
            subject_id=two_teams["team_a_entity_1"],  # Acme Corp (team A)
            predicate="employs",
            predicate_family="employment_reverse",
            object_id=two_teams["team_a_entity_2"],   # Jane Doe (team A)
            confidence=0.95,
            evidence="same-team test",
            source_session_id=None,
            team_id=two_teams["team_a_id"],
        )
        assert result["status"] in ("new", "duplicate")


# ---------------------------------------------------------------------------
# 8.4: Concurrent extraction test
# ---------------------------------------------------------------------------

class TestConcurrentExtraction:
    """Two workers resolving the same entity simultaneously produce exactly one record."""

    async def test_concurrent_resolve_same_entity_one_record(self, single_team):
        """Two concurrent calls to db_find_or_create_entity for the same name
        produce exactly one entity record in the database."""
        team_id = single_team["team_id"]
        entity_name = f"ConcurrentCo-{uuid.uuid4().hex[:8]}"

        async def resolve():
            return await db_find_or_create_entity(
                entity_name, "organization", ["concurrent-alias"], team_id=team_id,
            )

        # Run two resolutions concurrently
        results = await asyncio.gather(resolve(), resolve())

        # Both should return the same entity id
        id_a, mode_a = results[0]
        id_b, mode_b = results[1]
        assert id_a == id_b, "Concurrent resolution should yield the same entity"

        # Verify exactly one record in the DB
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*)::int FROM playbook.kg_entities "
                "WHERE LOWER(name) = $1 AND team_id = $2::uuid",
                entity_name.lower(), team_id,
            )
        assert count == 1


# ---------------------------------------------------------------------------
# 8.5: API authorization tests (mock-based)
# ---------------------------------------------------------------------------

class TestAPIAuthorization:
    """Master team gate and super admin bypass via _resolve_team_access."""

    @pytest.mark.asyncio
    async def test_regular_user_blocked_from_master_team(self):
        """Non-super-admin user gets 403 when accessing master team."""
        from fastapi import HTTPException
        from app.routers.knowledge_graph import _resolve_team_access

        user = {"sub": "regular-user"}
        with patch(
            "app.routers.knowledge_graph.db_is_super_admin",
            AsyncMock(return_value=False),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_team_access(user, MASTER_TEAM_ID)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_super_admin_allowed_master_team(self):
        """Super admin can access the master team."""
        from app.routers.knowledge_graph import _resolve_team_access

        user = {"sub": "admin-user"}
        with patch(
            "app.routers.knowledge_graph.db_is_super_admin",
            AsyncMock(return_value=True),
        ):
            result = await _resolve_team_access(user, MASTER_TEAM_ID)
        assert result == MASTER_TEAM_ID

    @pytest.mark.asyncio
    async def test_non_member_blocked_from_regular_team(self):
        """Non-member gets 403 for a regular team."""
        from fastapi import HTTPException
        from app.routers.knowledge_graph import _resolve_team_access

        user = {"sub": "outsider"}
        team_id = str(uuid.uuid4())
        with (
            patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=False)),
            patch("app.routers.knowledge_graph.db_is_team_member", AsyncMock(return_value=False)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_team_access(user, team_id)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_super_admin_bypasses_membership(self):
        """Super admin bypasses membership check for any team."""
        from app.routers.knowledge_graph import _resolve_team_access

        user = {"sub": "admin-user"}
        team_id = str(uuid.uuid4())
        with patch(
            "app.routers.knowledge_graph.db_is_super_admin",
            AsyncMock(return_value=True),
        ):
            result = await _resolve_team_access(user, team_id)
        assert result == team_id


# ---------------------------------------------------------------------------
# 8.6: Team deletion guard test
# ---------------------------------------------------------------------------

class TestTeamDeletionGuard:
    """Teams with KG entities cannot be deleted (RESTRICT FK)."""

    async def test_delete_team_with_entities_fails(self, single_team):
        """Attempting to delete a team that has KG entities raises a FK violation."""
        team_id = single_team["team_id"]

        # Create an entity in the team
        await db_find_or_create_entity(
            "GuardTestEntity", "organization", [], team_id=team_id,
        )

        # Attempt to delete the team directly should raise ForeignKeyViolationError
        async with _acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id,
                )

    async def test_empty_team_can_be_deleted(self, test_user_sid):
        """A team with no KG data can be deleted normally."""
        async with _acquire() as conn:
            team_id = await _make_team(conn, test_user_sid)

        # Delete team members first, then the team
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id,
            )
            # This should not raise
            await conn.execute(
                "DELETE FROM playbook.teams WHERE id = $1::uuid", team_id,
            )


# ---------------------------------------------------------------------------
# 8.7: Entity flag tests
# ---------------------------------------------------------------------------

class TestEntityFlags:
    """Auto-flag on master_copy, list flags, resolve flags."""

    async def test_flag_entity_creates_flag(self, single_team):
        """db_flag_entity_for_review creates a flag record."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            "FlagTestCo", "organization", [], team_id=team_id,
        )

        flag = await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        assert flag is not None
        assert flag["entity_id"] == eid
        assert flag["team_id"] == team_id
        assert flag["reason"] == "sourced_from_master"
        assert flag["resolved"] is False

    async def test_list_flags_returns_unresolved(self, single_team):
        """db_list_entity_flags returns only unresolved flags."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            "FlagListCo", "organization", [], team_id=team_id,
        )

        await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        flags = await db_list_entity_flags(team_id)
        matching = [f for f in flags if f["entity_id"] == eid]
        assert len(matching) == 1
        assert matching[0]["resolved"] is False

    async def test_resolve_flag_marks_resolved(self, single_team):
        """db_resolve_entity_flag marks a flag as resolved."""
        team_id = single_team["team_id"]
        user_sid = single_team["user_sid"]
        eid, _ = await db_find_or_create_entity(
            "FlagResolveCo", "organization", [], team_id=team_id,
        )

        flag = await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        assert flag is not None

        resolved = await db_resolve_entity_flag(flag["id"], resolved_by=user_sid)
        assert resolved is True

        # Flag should no longer appear in unresolved list
        flags = await db_list_entity_flags(team_id)
        matching = [f for f in flags if f["entity_id"] == eid]
        assert len(matching) == 0

    async def test_duplicate_flag_returns_none(self, single_team):
        """Flagging the same entity+team+reason again returns None (ON CONFLICT DO NOTHING)."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            "FlagDupCo", "organization", [], team_id=team_id,
        )

        flag1 = await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        assert flag1 is not None

        flag2 = await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        assert flag2 is None

    async def test_master_copy_auto_flags_via_resolution(self, single_team):
        """When db_find_or_create_entity returns master_copy mode,
        the entity gets a master_entity_id set (flag is caller's responsibility)."""
        team_id = single_team["team_id"]
        master_name = f"AutoFlagMaster-{uuid.uuid4().hex[:6]}"

        # Insert master entity
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id) "
                "VALUES ($1, 'organization', '{}', $2::uuid)",
                master_name, MASTER_TEAM_ID,
            )

        eid, mode = await db_find_or_create_entity(
            master_name, "organization", [], team_id=team_id,
        )
        assert mode == "master_copy"

        # Now manually flag (as the extraction code does)
        flag = await db_flag_entity_for_review(eid, team_id, "sourced_from_master")
        assert flag is not None

        flags = await db_list_entity_flags(team_id)
        matching = [f for f in flags if f["entity_id"] == eid]
        assert len(matching) == 1

        # Cleanup master entity
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE LOWER(name) = $1 AND team_id = $2::uuid",
                master_name.lower(), MASTER_TEAM_ID,
            )


# ---------------------------------------------------------------------------
# 8.8: Migration validation tests
# ---------------------------------------------------------------------------

class TestMigrationValidation:
    """Post-migration: no NULL team_ids, unique index works."""

    async def test_zero_null_team_id_entities(self):
        """No kg_entities rows have NULL team_id after migration."""
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*)::int FROM playbook.kg_entities WHERE team_id IS NULL",
            )
        assert count == 0

    async def test_zero_null_team_id_relationships(self):
        """No kg_relationships rows have NULL team_id after migration."""
        async with _acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*)::int FROM playbook.kg_relationships WHERE team_id IS NULL",
            )
        assert count == 0

    async def test_unique_index_prevents_duplicate_name_in_team(self, single_team):
        """The UNIQUE index on (LOWER(name), team_id) prevents raw duplicate inserts."""
        team_id = single_team["team_id"]
        entity_name = f"UniqueTest-{uuid.uuid4().hex[:8]}"

        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id) "
                "VALUES ($1, 'organization', '{}', $2::uuid)",
                entity_name, team_id,
            )
            # Inserting the same LOWER(name) + team_id should violate the unique index
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id) "
                    "VALUES ($1, 'organization', '{}', $2::uuid)",
                    entity_name, team_id,
                )

    async def test_same_name_different_teams_allowed(self, two_teams):
        """The same entity name in different teams is allowed by the index."""
        shared_name = f"SharedName-{uuid.uuid4().hex[:8]}"

        eid_a, mode_a = await db_find_or_create_entity(
            shared_name, "organization", [], team_id=two_teams["team_a_id"],
        )
        eid_b, mode_b = await db_find_or_create_entity(
            shared_name, "organization", [], team_id=two_teams["team_b_id"],
        )
        assert mode_a == "created"
        assert mode_b == "created"
        assert eid_a != eid_b, "Different teams should get different entity ids"

    async def test_team_id_not_null_constraint_on_entities(self):
        """Attempting to insert a kg_entity with NULL team_id is rejected."""
        async with _acquire() as conn:
            with pytest.raises((asyncpg.NotNullViolationError, asyncpg.PostgresError)):
                await conn.execute(
                    "INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id) "
                    "VALUES ('null-test', 'organization', '{}', NULL)",
                )


# ---------------------------------------------------------------------------
# 8.9: Promote/sync/merge tests
# ---------------------------------------------------------------------------

class TestPromoteSyncMerge:
    """Promote team entity to master, sync from master, merge entities."""

    async def test_promote_entity_to_master(self, single_team):
        """Promoting a team entity creates a master entity and links them."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            f"PromoteCo-{uuid.uuid4().hex[:6]}", "organization", ["promo-alias"],
            team_id=team_id,
        )

        master_id = await db_promote_entity_to_master(eid, team_id)
        assert master_id is not None

        # Verify master entity exists in master team
        async with _acquire() as conn:
            master_row = await conn.fetchrow(
                "SELECT * FROM playbook.kg_entities WHERE id = $1::uuid",
                master_id,
            )
        assert master_row is not None
        assert str(master_row["team_id"]) == MASTER_TEAM_ID

        # Verify team entity now has master_entity_id set
        async with _acquire() as conn:
            team_row = await conn.fetchrow(
                "SELECT master_entity_id FROM playbook.kg_entities WHERE id = $1::uuid",
                eid,
            )
        assert str(team_row["master_entity_id"]) == master_id

        # Cleanup master entity
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE id = $1::uuid", master_id,
            )

    async def test_promote_nonexistent_returns_none(self, single_team):
        """Promoting a nonexistent entity returns None."""
        result = await db_promote_entity_to_master(str(uuid.uuid4()), single_team["team_id"])
        assert result is None

    async def test_sync_entity_from_master(self, single_team):
        """Syncing from master updates the team entity with master data."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            f"SyncCo-{uuid.uuid4().hex[:6]}", "organization", [],
            team_id=team_id,
        )

        # Promote first to establish the link
        master_id = await db_promote_entity_to_master(eid, team_id)
        assert master_id is not None

        # Update the master entity's name and description
        async with _acquire() as conn:
            await conn.execute(
                "UPDATE playbook.kg_entities SET name = 'SyncedMasterName', "
                "description = 'Master description', entity_type = 'organization' "
                "WHERE id = $1::uuid",
                master_id,
            )

        # Sync from master
        synced = await db_sync_entity_from_master(eid, team_id)
        assert synced is not None
        assert synced["name"] == "SyncedMasterName"
        assert synced["description"] == "Master description"

        # Cleanup master entity
        async with _acquire() as conn:
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE id = $1::uuid", master_id,
            )

    async def test_sync_without_master_link_returns_none(self, single_team):
        """Syncing an entity with no master_entity_id returns None."""
        team_id = single_team["team_id"]
        eid, _ = await db_find_or_create_entity(
            f"NoMaster-{uuid.uuid4().hex[:6]}", "person", [], team_id=team_id,
        )
        result = await db_sync_entity_from_master(eid, team_id)
        assert result is None

    async def test_merge_entities(self, single_team):
        """Merging loser into winner: relationships moved, aliases merged, loser deleted."""
        team_id = single_team["team_id"]

        winner_id, _ = await db_find_or_create_entity(
            "MergeWinner", "organization", ["winner-alias"], team_id=team_id,
        )
        loser_id, _ = await db_find_or_create_entity(
            "MergeLoser", "organization", ["loser-alias"], team_id=team_id,
        )
        third_id, _ = await db_find_or_create_entity(
            "ThirdParty", "person", [], team_id=team_id,
        )

        # Create relationship: ThirdParty -> MergeLoser
        await db_upsert_relationship(
            subject_id=third_id, predicate="works_at", predicate_family="employment",
            object_id=loser_id, confidence=0.9, evidence="merge test",
            source_session_id=None, team_id=team_id,
        )

        # Merge loser into winner
        merged = await db_merge_kg_entities(winner_id, loser_id, team_id)
        assert merged is not None

        # Winner should have loser's name in aliases
        assert "MergeLoser" in merged["aliases"]

        # Relationship should now point to winner
        rels = await db_get_entity_relationships(winner_id, team_id=team_id)
        rel_subjects = [r.get("subject_id") for r in rels]
        assert third_id in rel_subjects

        # Loser should be deleted
        async with _acquire() as conn:
            loser_row = await conn.fetchrow(
                "SELECT id FROM playbook.kg_entities WHERE id = $1::uuid", loser_id,
            )
        assert loser_row is None

    async def test_merge_nonexistent_returns_none(self, single_team):
        """Merging when one entity does not exist returns None."""
        team_id = single_team["team_id"]
        winner_id, _ = await db_find_or_create_entity(
            "MergeReal", "organization", [], team_id=team_id,
        )
        result = await db_merge_kg_entities(winner_id, str(uuid.uuid4()), team_id)
        assert result is None


# ---------------------------------------------------------------------------
# 8.10: Relationship dedup test
# ---------------------------------------------------------------------------

class TestRelationshipDedupAcrossTeams:
    """Same relationship in two teams is NOT treated as a duplicate."""

    async def test_same_relationship_different_teams_not_deduped(self, two_teams):
        """Two teams with identically-named entities and same relationship
        predicate each have their own independent relationship records."""
        shared_name_1 = f"SharedOrg-{uuid.uuid4().hex[:6]}"
        shared_name_2 = f"SharedPerson-{uuid.uuid4().hex[:6]}"

        # Create same-named entities in both teams
        ea1, _ = await db_find_or_create_entity(
            shared_name_1, "organization", [], team_id=two_teams["team_a_id"],
        )
        ea2, _ = await db_find_or_create_entity(
            shared_name_2, "person", [], team_id=two_teams["team_a_id"],
        )
        eb1, _ = await db_find_or_create_entity(
            shared_name_1, "organization", [], team_id=two_teams["team_b_id"],
        )
        eb2, _ = await db_find_or_create_entity(
            shared_name_2, "person", [], team_id=two_teams["team_b_id"],
        )

        # Create same relationship in both teams
        result_a = await db_upsert_relationship(
            subject_id=ea2, predicate="works_at", predicate_family="employment",
            object_id=ea1, confidence=0.9, evidence="team A",
            source_session_id=None, team_id=two_teams["team_a_id"],
        )
        result_b = await db_upsert_relationship(
            subject_id=eb2, predicate="works_at", predicate_family="employment",
            object_id=eb1, confidence=0.9, evidence="team B",
            source_session_id=None, team_id=two_teams["team_b_id"],
        )

        # Both should be "new", not "duplicate"
        assert result_a["status"] == "new"
        assert result_b["status"] == "new"

    async def test_same_relationship_same_team_is_duplicate(self, single_team):
        """The same relationship within the same team IS treated as duplicate."""
        team_id = single_team["team_id"]

        eid1, _ = await db_find_or_create_entity(
            f"DedupOrg-{uuid.uuid4().hex[:6]}", "organization", [], team_id=team_id,
        )
        eid2, _ = await db_find_or_create_entity(
            f"DedupPerson-{uuid.uuid4().hex[:6]}", "person", [], team_id=team_id,
        )

        result1 = await db_upsert_relationship(
            subject_id=eid2, predicate="works_at", predicate_family="employment",
            object_id=eid1, confidence=0.9, evidence="first",
            source_session_id=None, team_id=team_id,
        )
        result2 = await db_upsert_relationship(
            subject_id=eid2, predicate="works_at", predicate_family="employment",
            object_id=eid1, confidence=0.9, evidence="second",
            source_session_id=None, team_id=team_id,
        )

        assert result1["status"] == "new"
        assert result2["status"] == "duplicate"

"""Integration tests for Programs DB layer.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.programs import (
    db_create_program,
    db_delete_program,
    db_get_program,
    db_list_programs,
    db_update_program,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
# CRUD: Create
# ---------------------------------------------------------------------------

class TestCreateProgram:

    async def test_create_minimal(self, test_user_sid):
        """Create a program with just a name."""
        program = await db_create_program(
            name="2024 NFL Draft",
            description=None,
            owner_sid=test_user_sid,
        )
        try:
            assert program["name"] == "2024 NFL Draft"
            assert program["owner_sid"] == test_user_sid
            assert program["description"] is None
            assert program["team_id"] is None
            assert "id" in program
            assert "created_at" in program
            assert "updated_at" in program
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_create_with_description(self, test_user_sid):
        """Create a program with name + description."""
        program = await db_create_program(
            name="NBA Free Agency",
            description="Track all NBA free agent signings",
            owner_sid=test_user_sid,
        )
        try:
            assert program["description"] == "Track all NBA free agent signings"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_create_with_team(self, test_user_sid):
        """Create a program associated with a team."""
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
        try:
            program = await db_create_program(
                name="Team Program",
                description=None,
                owner_sid=test_user_sid,
                team_id=team_id,
            )
            assert program["team_id"] == team_id
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


# ---------------------------------------------------------------------------
# CRUD: List
# ---------------------------------------------------------------------------

class TestListPrograms:

    async def test_list_personal_programs(self, test_user_sid):
        """List programs for a user without team scope."""
        p1 = await db_create_program(name="Program A", description=None, owner_sid=test_user_sid)
        p2 = await db_create_program(name="Program B", description=None, owner_sid=test_user_sid)
        try:
            programs = await db_list_programs(owner_sid=test_user_sid)
            ids = {p["id"] for p in programs}
            assert p1["id"] in ids
            assert p2["id"] in ids
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", p1["id"])
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", p2["id"])

    async def test_list_team_programs(self, test_user_sid):
        """List programs scoped to a team."""
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
        p1 = await db_create_program(name="Team Prog", description=None, owner_sid=test_user_sid, team_id=team_id)
        p2 = await db_create_program(name="Personal Prog", description=None, owner_sid=test_user_sid)
        try:
            team_programs = await db_list_programs(owner_sid=test_user_sid, team_id=team_id)
            ids = {p["id"] for p in team_programs}
            assert p1["id"] in ids
            assert p2["id"] not in ids  # personal program excluded from team scope
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", p1["id"])
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", p2["id"])
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

    async def test_list_excludes_other_users(self, test_user_sid):
        """Personal programs from other users should not appear."""
        other_sid = f"other-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
        other_prog = await db_create_program(name="Other's Prog", description=None, owner_sid=other_sid)
        my_prog = await db_create_program(name="My Prog", description=None, owner_sid=test_user_sid)
        try:
            programs = await db_list_programs(owner_sid=test_user_sid)
            ids = {p["id"] for p in programs}
            assert my_prog["id"] in ids
            assert other_prog["id"] not in ids
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", other_prog["id"])
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", my_prog["id"])
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

    async def test_list_empty(self, test_user_sid):
        """No programs returns empty list."""
        programs = await db_list_programs(owner_sid=test_user_sid)
        assert programs == []


# ---------------------------------------------------------------------------
# CRUD: Get
# ---------------------------------------------------------------------------

class TestGetProgram:

    async def test_get_existing(self, test_user_sid):
        program = await db_create_program(name="Findable", description=None, owner_sid=test_user_sid)
        try:
            found = await db_get_program(program["id"])
            assert found is not None
            assert found["id"] == program["id"]
            assert found["name"] == "Findable"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_get_nonexistent(self):
        fake_id = str(uuid.uuid4())
        result = await db_get_program(fake_id)
        assert result is None


# ---------------------------------------------------------------------------
# CRUD: Update
# ---------------------------------------------------------------------------

class TestUpdateProgram:

    async def test_update_name(self, test_user_sid):
        program = await db_create_program(name="Old Name", description=None, owner_sid=test_user_sid)
        try:
            updated = await db_update_program(program["id"], name="New Name")
            assert updated is not None
            assert updated["name"] == "New Name"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_update_description(self, test_user_sid):
        program = await db_create_program(name="Prog", description="Old desc", owner_sid=test_user_sid)
        try:
            updated = await db_update_program(program["id"], description="New desc")
            assert updated is not None
            assert updated["description"] == "New desc"
            assert updated["name"] == "Prog"  # unchanged
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_noop_update_returns_current(self, test_user_sid):
        program = await db_create_program(name="Stable", description=None, owner_sid=test_user_sid)
        try:
            result = await db_update_program(program["id"])
            assert result is not None
            assert result["name"] == "Stable"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])

    async def test_update_nonexistent(self):
        fake_id = str(uuid.uuid4())
        result = await db_update_program(fake_id, name="Nope")
        assert result is None

    async def test_update_bumps_updated_at(self, test_user_sid):
        program = await db_create_program(name="TimeProg", description=None, owner_sid=test_user_sid)
        try:
            updated = await db_update_program(program["id"], name="TimeProgV2")
            assert updated is not None
            assert updated["updated_at"] >= program["updated_at"]
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program["id"])


# ---------------------------------------------------------------------------
# CRUD: Delete
# ---------------------------------------------------------------------------

class TestDeleteProgram:

    async def test_delete_existing(self, test_user_sid):
        program = await db_create_program(name="Doomed", description=None, owner_sid=test_user_sid)
        result = await db_delete_program(program["id"])
        assert result is True
        # Verify it is gone
        assert await db_get_program(program["id"]) is None

    async def test_delete_nonexistent(self):
        fake_id = str(uuid.uuid4())
        result = await db_delete_program(fake_id)
        assert result is False

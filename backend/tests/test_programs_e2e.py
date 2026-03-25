"""E2E tests for Programs REST endpoints.

Tests the full HTTP request/response cycle using httpx AsyncClient
against the FastAPI application with mocked auth.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db._pool import _acquire


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_app(user_sid: str):
    """Create a FastAPI app with a patched auth dependency for testing."""
    from fastapi import FastAPI
    from app.routers.programs import router as programs_router
    from app.auth import get_current_user

    app = FastAPI()
    app.include_router(programs_router)

    async def _mock_user():
        return {"sub": user_sid, "name": "Test"}

    app.dependency_overrides[get_current_user] = _mock_user
    return app


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
# POST /api/programs
# ---------------------------------------------------------------------------

class TestCreateProgramEndpoint:

    async def test_create_returns_201(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/programs", json={"name": "New Program"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "New Program"
        assert data["owner_sid"] == test_user_sid
        # Cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", data["id"])

    async def test_create_with_description(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/programs", json={
                "name": "NFL Draft 2024",
                "description": "Annual NFL Draft tracking",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["description"] == "Annual NFL Draft tracking"
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", data["id"])

    async def test_create_with_team_id(self, test_user_sid):
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/programs", json={
                    "name": "Team Program",
                    "team_id": team_id,
                })
            assert resp.status_code == 201
            data = resp.json()
            assert data["team_id"] == team_id
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", data["id"])
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)

    async def test_create_missing_name_returns_422(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/programs", json={})
        assert resp.status_code == 422

    async def test_create_forbidden_team(self, test_user_sid):
        """Creating a program for a team you are not a member of returns 403."""
        other_sid = f"other-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
            team_id = await _create_team(conn, other_sid)
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/programs", json={
                    "name": "Forbidden Program",
                    "team_id": team_id,
                })
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# GET /api/programs
# ---------------------------------------------------------------------------

class TestListProgramsEndpoint:

    async def test_list_returns_200(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/programs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_includes_created(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post("/api/programs", json={"name": "Listed Program"})
            program_id = create_resp.json()["id"]
            list_resp = await client.get("/api/programs")
        try:
            ids = {p["id"] for p in list_resp.json()}
            assert program_id in ids
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", program_id)

    async def test_list_with_team_filter(self, test_user_sid):
        async with _acquire() as conn:
            team_id = await _create_team(conn, test_user_sid)
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/api/programs", json={"name": "Team Prog", "team_id": team_id})
                await client.post("/api/programs", json={"name": "Personal Prog"})
                resp = await client.get(f"/api/programs?team_id={team_id}")
            data = resp.json()
            assert all(p["team_id"] == team_id for p in data)
        finally:
            async with _acquire() as conn:
                await conn.execute(
                    "DELETE FROM playbook.programs WHERE owner_sid = $1", test_user_sid,
                )
                await conn.execute("DELETE FROM playbook.team_members WHERE team_id = $1::uuid", team_id)
                await conn.execute("DELETE FROM playbook.teams WHERE id = $1::uuid", team_id)


# ---------------------------------------------------------------------------
# GET /api/programs/{id}
# ---------------------------------------------------------------------------

class TestGetProgramEndpoint:

    async def test_get_existing(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post("/api/programs", json={"name": "Gettable"})
            pid = create_resp.json()["id"]
            resp = await client.get(f"/api/programs/{pid}")
        try:
            assert resp.status_code == 200
            assert resp.json()["name"] == "Gettable"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", pid)

    async def test_get_nonexistent_returns_404(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/programs/{fake_id}")
        assert resp.status_code == 404

    async def test_get_other_users_program_returns_403(self, test_user_sid):
        """A user cannot get another user's personal program."""
        other_sid = f"other-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
            row = await conn.fetchrow(
                "INSERT INTO playbook.programs (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "Other's Program", other_sid,
            )
            pid = str(row["id"])
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/api/programs/{pid}")
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", pid)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# PUT /api/programs/{id}
# ---------------------------------------------------------------------------

class TestUpdateProgramEndpoint:

    async def test_update_name(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post("/api/programs", json={"name": "Old Name"})
            pid = create_resp.json()["id"]
            resp = await client.put(f"/api/programs/{pid}", json={"name": "New Name"})
        try:
            assert resp.status_code == 200
            assert resp.json()["name"] == "New Name"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", pid)

    async def test_update_nonexistent_returns_404(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(f"/api/programs/{fake_id}", json={"name": "Nope"})
        assert resp.status_code == 404

    async def test_update_other_users_program_returns_403(self, test_user_sid):
        other_sid = f"other-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
            row = await conn.fetchrow(
                "INSERT INTO playbook.programs (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "Theirs", other_sid,
            )
            pid = str(row["id"])
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.put(f"/api/programs/{pid}", json={"name": "Hijacked"})
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", pid)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ---------------------------------------------------------------------------
# DELETE /api/programs/{id}
# ---------------------------------------------------------------------------

class TestDeleteProgramEndpoint:

    async def test_delete_returns_204(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post("/api/programs", json={"name": "Doomed"})
            pid = create_resp.json()["id"]
            resp = await client.delete(f"/api/programs/{pid}")
        assert resp.status_code == 204
        # Verify it is gone
        async with _acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM playbook.programs WHERE id = $1::uuid", pid,
            )
            assert row is None

    async def test_delete_nonexistent_returns_404(self, test_user_sid):
        app = _make_test_app(test_user_sid)
        transport = ASGITransport(app=app)
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/programs/{fake_id}")
        assert resp.status_code == 404

    async def test_delete_other_users_program_returns_403(self, test_user_sid):
        other_sid = f"other-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name) VALUES ($1, $2)",
                other_sid, "Other",
            )
            row = await conn.fetchrow(
                "INSERT INTO playbook.programs (name, owner_sid) VALUES ($1, $2) RETURNING id",
                "Protected", other_sid,
            )
            pid = str(row["id"])
        try:
            app = _make_test_app(test_user_sid)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(f"/api/programs/{pid}")
            assert resp.status_code == 403
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.programs WHERE id = $1::uuid", pid)
                await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

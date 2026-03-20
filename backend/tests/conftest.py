"""Shared fixtures for integration tests.

Requires a running PostgreSQL (docker compose up -d).
Uses the app's own pool and schema initialization.

Run: cd backend && uv run python -m pytest tests/ -v
"""
from __future__ import annotations

import uuid

import pytest_asyncio

from app.db import init_schema
from app.db._pool import _acquire, close_pool


_schema_initialized = False


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    """Run schema migrations once, then yield. Closes pool after each test to
    avoid event-loop mismatches between tests."""
    global _schema_initialized
    if not _schema_initialized:
        await init_schema()
        _schema_initialized = True
    yield
    await close_pool()


@pytest_asyncio.fixture
async def test_user_sid():
    """Create a throwaway user and return its sid. Cleaned up after test."""
    sid = f"test-user-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
            sid, "Test User", f"{sid}@test.local",
        )
    yield sid
    async with _acquire() as conn:
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest_asyncio.fixture
async def test_campaign(test_user_sid):
    """Create a throwaway campaign and return its id (str). Cleaned up via CASCADE."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.campaigns (name, owner_sid)
            VALUES ($1, $2) RETURNING id
            """,
            f"test-campaign-{uuid.uuid4().hex[:8]}", test_user_sid,
        )
    campaign_id = str(row["id"])
    yield campaign_id
    async with _acquire() as conn:
        # CASCADE deletes entities/attributes
        await conn.execute(
            "DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id,
        )

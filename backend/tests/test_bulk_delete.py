"""Integration tests for bulk delete DB functions and API endpoints.

Covers:
  - db_bulk_delete_entities / db_bulk_delete_attributes (campaign)
  - db_bulk_delete_library_entities / db_bulk_delete_library_attributes (library)
  - Empty array returns 0 without querying DB
  - Authorization: only deletes rows owned by the authenticated user
  - Mixed ownership: only matching rows are deleted

Requires: docker compose up -d (PostgreSQL on port 5432)
Run: cd backend && uv run python -m pytest tests/test_bulk_delete.py -v
"""
from __future__ import annotations

import uuid

import pytest

from app.db._pool import _acquire
from app.db.attributes import db_bulk_delete_attributes, db_create_attribute
from app.db.entities import db_bulk_delete_entities, db_create_entity
from app.db.library import (
    db_bulk_delete_library_attributes,
    db_bulk_delete_library_entities,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _insert_entity(campaign_id: str, label: str | None = None) -> str:
    e = await db_create_entity(
        campaign_id=campaign_id,
        label=label or f"Entity-{uuid.uuid4().hex[:8]}",
    )
    return e["id"]


async def _insert_attribute(campaign_id: str, label: str | None = None) -> str:
    a = await db_create_attribute(
        campaign_id=campaign_id,
        label=label or f"Attr-{uuid.uuid4().hex[:8]}",
    )
    return a["id"]


async def _insert_lib_entity(conn, owner_sid: str, label: str | None = None) -> str:
    row = await conn.fetchrow(
        "INSERT INTO playbook.entity_library (owner_sid, label) VALUES ($1, $2) RETURNING id",
        owner_sid, label or f"LibEntity-{uuid.uuid4().hex[:8]}",
    )
    return str(row["id"])


async def _insert_lib_attribute(conn, owner_sid: str, label: str | None = None) -> str:
    row = await conn.fetchrow(
        "INSERT INTO playbook.attribute_library (owner_sid, label, weight) VALUES ($1, $2, 1.0) RETURNING id",
        owner_sid, label or f"LibAttr-{uuid.uuid4().hex[:8]}",
    )
    return str(row["id"])


async def _entity_exists(entity_id: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM playbook.entities WHERE id = $1::uuid", entity_id,
        )
    return row is not None


async def _attribute_exists(attribute_id: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM playbook.attributes WHERE id = $1::uuid", attribute_id,
        )
    return row is not None


async def _lib_entity_exists(item_id: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM playbook.entity_library WHERE id = $1::uuid", item_id,
        )
    return row is not None


async def _lib_attribute_exists(item_id: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM playbook.attribute_library WHERE id = $1::uuid", item_id,
        )
    return row is not None


# ── Campaign entities bulk delete ─────────────────────────────────────────────

class TestBulkDeleteEntities:

    async def test_delete_multiple(self, test_campaign):
        id1 = await _insert_entity(test_campaign)
        id2 = await _insert_entity(test_campaign)
        id3 = await _insert_entity(test_campaign)

        deleted = await db_bulk_delete_entities(test_campaign, [id1, id2])

        assert deleted == 2
        assert not await _entity_exists(id1)
        assert not await _entity_exists(id2)
        assert await _entity_exists(id3)  # untouched

        # cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entities WHERE id = $1::uuid", id3)

    async def test_empty_ids_returns_zero(self, test_campaign):
        deleted = await db_bulk_delete_entities(test_campaign, [])
        assert deleted == 0

    async def test_nonexistent_ids_returns_zero(self, test_campaign):
        fake_id = str(uuid.uuid4())
        deleted = await db_bulk_delete_entities(test_campaign, [fake_id])
        assert deleted == 0

    async def test_wrong_campaign_does_not_delete(self, test_campaign, test_user_sid):
        """IDs from another campaign must not be deleted."""
        id1 = await _insert_entity(test_campaign)

        other_campaign_id = str(uuid.uuid4())  # non-existent campaign
        deleted = await db_bulk_delete_entities(other_campaign_id, [id1])

        assert deleted == 0
        assert await _entity_exists(id1)

        # cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entities WHERE id = $1::uuid", id1)

    async def test_mixed_ownership_only_deletes_matching(self, test_campaign):
        """Only IDs belonging to the given campaign_id are deleted."""
        id_own = await _insert_entity(test_campaign)

        # Insert entity into a second campaign
        async with _acquire() as conn:
            owner_row = await conn.fetchrow(
                "SELECT owner_sid FROM playbook.campaigns WHERE id = $1::uuid", test_campaign,
            )
            other_camp_row = await conn.fetchrow(
                "INSERT INTO playbook.campaigns (name, owner_sid) VALUES ($1, $2) RETURNING id",
                f"other-{uuid.uuid4().hex[:6]}", owner_row["owner_sid"],
            )
        other_campaign_id = str(other_camp_row["id"])
        id_other = await _insert_entity(other_campaign_id)

        deleted = await db_bulk_delete_entities(test_campaign, [id_own, id_other])

        assert deleted == 1
        assert not await _entity_exists(id_own)
        assert await _entity_exists(id_other)

        # cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.campaigns WHERE id = $1::uuid", other_campaign_id)

    async def test_single_delete(self, test_campaign):
        id1 = await _insert_entity(test_campaign)
        deleted = await db_bulk_delete_entities(test_campaign, [id1])
        assert deleted == 1
        assert not await _entity_exists(id1)


# ── Campaign attributes bulk delete ──────────────────────────────────────────

class TestBulkDeleteAttributes:

    async def test_delete_multiple(self, test_campaign):
        id1 = await _insert_attribute(test_campaign)
        id2 = await _insert_attribute(test_campaign)
        id3 = await _insert_attribute(test_campaign)

        deleted = await db_bulk_delete_attributes(test_campaign, [id1, id2])

        assert deleted == 2
        assert not await _attribute_exists(id1)
        assert not await _attribute_exists(id2)
        assert await _attribute_exists(id3)

        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", id3)

    async def test_empty_ids_returns_zero(self, test_campaign):
        deleted = await db_bulk_delete_attributes(test_campaign, [])
        assert deleted == 0

    async def test_nonexistent_ids_returns_zero(self, test_campaign):
        deleted = await db_bulk_delete_attributes(test_campaign, [str(uuid.uuid4())])
        assert deleted == 0

    async def test_wrong_campaign_does_not_delete(self, test_campaign):
        id1 = await _insert_attribute(test_campaign)
        deleted = await db_bulk_delete_attributes(str(uuid.uuid4()), [id1])
        assert deleted == 0
        assert await _attribute_exists(id1)
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", id1)


# ── Library entities bulk delete ──────────────────────────────────────────────

class TestBulkDeleteLibraryEntities:

    async def test_delete_multiple(self, test_user_sid):
        async with _acquire() as conn:
            id1 = await _insert_lib_entity(conn, test_user_sid)
            id2 = await _insert_lib_entity(conn, test_user_sid)
            id3 = await _insert_lib_entity(conn, test_user_sid)

        deleted = await db_bulk_delete_library_entities(test_user_sid, [id1, id2])

        assert deleted == 2
        assert not await _lib_entity_exists(id1)
        assert not await _lib_entity_exists(id2)
        assert await _lib_entity_exists(id3)

        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entity_library WHERE id = $1::uuid", id3)

    async def test_empty_ids_returns_zero(self, test_user_sid):
        deleted = await db_bulk_delete_library_entities(test_user_sid, [])
        assert deleted == 0

    async def test_nonexistent_ids_returns_zero(self, test_user_sid):
        deleted = await db_bulk_delete_library_entities(test_user_sid, [str(uuid.uuid4())])
        assert deleted == 0

    async def test_cannot_delete_other_users_items(self, test_user_sid):
        """Items owned by another user must not be deleted."""
        other_sid = f"other-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
                other_sid, "Other User", f"{other_sid}@test.local",
            )
            other_id = await _insert_lib_entity(conn, other_sid)

        deleted = await db_bulk_delete_library_entities(test_user_sid, [other_id])
        assert deleted == 0
        assert await _lib_entity_exists(other_id)

        # cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entity_library WHERE id = $1::uuid", other_id)
            await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

    async def test_mixed_ownership_only_deletes_own(self, test_user_sid):
        """Only the authenticated user's items are deleted; others survive."""
        other_sid = f"other-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
                other_sid, "Other User", f"{other_sid}@test.local",
            )
            own_id = await _insert_lib_entity(conn, test_user_sid)
            other_id = await _insert_lib_entity(conn, other_sid)

        deleted = await db_bulk_delete_library_entities(test_user_sid, [own_id, other_id])
        assert deleted == 1
        assert not await _lib_entity_exists(own_id)
        assert await _lib_entity_exists(other_id)

        # cleanup
        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.entity_library WHERE id = $1::uuid", other_id)
            await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)


# ── Library attributes bulk delete ────────────────────────────────────────────

class TestBulkDeleteLibraryAttributes:

    async def test_delete_multiple(self, test_user_sid):
        async with _acquire() as conn:
            id1 = await _insert_lib_attribute(conn, test_user_sid)
            id2 = await _insert_lib_attribute(conn, test_user_sid)
            id3 = await _insert_lib_attribute(conn, test_user_sid)

        deleted = await db_bulk_delete_library_attributes(test_user_sid, [id1, id2])

        assert deleted == 2
        assert not await _lib_attribute_exists(id1)
        assert not await _lib_attribute_exists(id2)
        assert await _lib_attribute_exists(id3)

        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attribute_library WHERE id = $1::uuid", id3)

    async def test_empty_ids_returns_zero(self, test_user_sid):
        deleted = await db_bulk_delete_library_attributes(test_user_sid, [])
        assert deleted == 0

    async def test_nonexistent_ids_returns_zero(self, test_user_sid):
        deleted = await db_bulk_delete_library_attributes(test_user_sid, [str(uuid.uuid4())])
        assert deleted == 0

    async def test_cannot_delete_other_users_items(self, test_user_sid):
        other_sid = f"other-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
                other_sid, "Other User", f"{other_sid}@test.local",
            )
            other_id = await _insert_lib_attribute(conn, other_sid)

        deleted = await db_bulk_delete_library_attributes(test_user_sid, [other_id])
        assert deleted == 0
        assert await _lib_attribute_exists(other_id)

        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attribute_library WHERE id = $1::uuid", other_id)
            await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

    async def test_mixed_ownership_only_deletes_own(self, test_user_sid):
        other_sid = f"other-user-{uuid.uuid4().hex[:8]}"
        async with _acquire() as conn:
            await conn.execute(
                "INSERT INTO playbook.users (sid, display_name, email) VALUES ($1, $2, $3)",
                other_sid, "Other User", f"{other_sid}@test.local",
            )
            own_id = await _insert_lib_attribute(conn, test_user_sid)
            other_id = await _insert_lib_attribute(conn, other_sid)

        deleted = await db_bulk_delete_library_attributes(test_user_sid, [own_id, other_id])
        assert deleted == 1
        assert not await _lib_attribute_exists(own_id)
        assert await _lib_attribute_exists(other_id)

        async with _acquire() as conn:
            await conn.execute("DELETE FROM playbook.attribute_library WHERE id = $1::uuid", other_id)
            await conn.execute("DELETE FROM playbook.users WHERE sid = $1", other_sid)

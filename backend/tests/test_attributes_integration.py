"""Integration tests for Attributes DB layer.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.
"""
from __future__ import annotations

import uuid

from app.db._pool import _acquire
from app.db.attributes import (
    db_create_attribute,
    db_delete_attribute,
    db_get_attribute,
    db_list_attributes,
    db_update_attribute,
)


# ---------------------------------------------------------------------------
# CRUD: Create
# ---------------------------------------------------------------------------


class TestCreateAttribute:

    async def test_create_minimal(self, test_campaign):
        """Create an attribute with just a label."""
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Height",
        )
        try:
            assert attr["label"] == "Height"
            assert attr["campaign_id"] == test_campaign
            assert attr["weight"] == 1.0
            assert attr["attribute_type"] == "text"
            assert attr["category"] is None
            assert attr["numeric_min"] is None
            assert attr["numeric_max"] is None
            assert attr["options"] is None
            assert "id" in attr
            assert "created_at" in attr
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_create_numeric_with_bounds(self, test_campaign):
        """Create a numeric attribute with min/max bounds."""
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="40-Yard Dash",
            description="Sprint time in seconds",
            weight=2.0,
            attribute_type="numeric",
            category="Performance",
            numeric_min=4.0,
            numeric_max=6.0,
        )
        try:
            assert attr["attribute_type"] == "numeric"
            assert attr["category"] == "Performance"
            assert attr["numeric_min"] == 4.0
            assert attr["numeric_max"] == 6.0
            assert attr["weight"] == 2.0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_create_select_with_options(self, test_campaign):
        """Create a select attribute with options."""
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Position",
            attribute_type="select",
            category="Physical",
            options=["QB", "RB", "WR", "TE"],
        )
        try:
            assert attr["attribute_type"] == "select"
            assert attr["options"] == ["QB", "RB", "WR", "TE"]
            assert attr["category"] == "Physical"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_create_boolean(self, test_campaign):
        """Create a boolean attribute."""
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Is Starter",
            attribute_type="boolean",
        )
        try:
            assert attr["attribute_type"] == "boolean"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])


# ---------------------------------------------------------------------------
# CRUD: List
# ---------------------------------------------------------------------------


class TestListAttributes:

    async def test_list_returns_created(self, test_campaign):
        a1 = await db_create_attribute(campaign_id=test_campaign, label="Attr A")
        a2 = await db_create_attribute(campaign_id=test_campaign, label="Attr B")
        try:
            result = await db_list_attributes(test_campaign)
            ids = {item["id"] for item in result["items"]}
            assert a1["id"] in ids
            assert a2["id"] in ids
            assert result["total"] >= 2
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a1["id"])
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a2["id"])

    async def test_list_filter_by_category(self, test_campaign):
        """Category filter should only return matching attributes."""
        a1 = await db_create_attribute(
            campaign_id=test_campaign, label="Height", category="Physical",
        )
        a2 = await db_create_attribute(
            campaign_id=test_campaign, label="Speed", category="Performance",
        )
        a3 = await db_create_attribute(
            campaign_id=test_campaign, label="Weight", category="Physical",
        )
        try:
            result = await db_list_attributes(test_campaign, category="Physical")
            labels = {item["label"] for item in result["items"]}
            assert "Height" in labels
            assert "Weight" in labels
            assert "Speed" not in labels
            assert result["total"] == 2
        finally:
            async with _acquire() as conn:
                for a in (a1, a2, a3):
                    await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a["id"])

    async def test_list_filter_by_search(self, test_campaign):
        a1 = await db_create_attribute(campaign_id=test_campaign, label="Height")
        a2 = await db_create_attribute(campaign_id=test_campaign, label="Weight")
        try:
            result = await db_list_attributes(test_campaign, search="eight")
            labels = {item["label"] for item in result["items"]}
            assert "Height" in labels
            assert "Weight" in labels
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a1["id"])
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a2["id"])

    async def test_list_combined_filters(self, test_campaign):
        """Search + category filter combined."""
        a1 = await db_create_attribute(
            campaign_id=test_campaign, label="Height CM", category="Physical",
        )
        a2 = await db_create_attribute(
            campaign_id=test_campaign, label="Height IN", category="Physical",
        )
        a3 = await db_create_attribute(
            campaign_id=test_campaign, label="Speed", category="Performance",
        )
        try:
            result = await db_list_attributes(test_campaign, search="Height", category="Physical")
            assert result["total"] == 2
            labels = {item["label"] for item in result["items"]}
            assert "Height CM" in labels
            assert "Height IN" in labels
        finally:
            async with _acquire() as conn:
                for a in (a1, a2, a3):
                    await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a["id"])

    async def test_list_empty(self, test_campaign):
        result = await db_list_attributes(test_campaign)
        assert result["items"] == []
        assert result["total"] == 0

    async def test_list_with_limit_zero_returns_all(self, test_campaign):
        a1 = await db_create_attribute(campaign_id=test_campaign, label="A1")
        a2 = await db_create_attribute(campaign_id=test_campaign, label="A2")
        try:
            result = await db_list_attributes(test_campaign, limit=0)
            assert result["total"] == len(result["items"])
            assert result["total"] >= 2
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a1["id"])
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", a2["id"])


# ---------------------------------------------------------------------------
# CRUD: Get
# ---------------------------------------------------------------------------


class TestGetAttribute:

    async def test_get_existing(self, test_campaign):
        attr = await db_create_attribute(campaign_id=test_campaign, label="Findable")
        try:
            found = await db_get_attribute(attr["id"])
            assert found is not None
            assert found["id"] == attr["id"]
            assert found["label"] == "Findable"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_get_nonexistent(self):
        fake_id = str(uuid.uuid4())
        result = await db_get_attribute(fake_id)
        assert result is None

    async def test_get_returns_all_new_fields(self, test_campaign):
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Full Attr",
            attribute_type="select",
            category="Performance",
            numeric_min=1.0,
            numeric_max=10.0,
            options=["A", "B"],
        )
        try:
            found = await db_get_attribute(attr["id"])
            assert found is not None
            assert found["attribute_type"] == "select"
            assert found["category"] == "Performance"
            assert found["numeric_min"] == 1.0
            assert found["numeric_max"] == 10.0
            assert found["options"] == ["A", "B"]
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])


# ---------------------------------------------------------------------------
# CRUD: Update
# ---------------------------------------------------------------------------


class TestUpdateAttribute:

    async def test_update_label(self, test_campaign):
        attr = await db_create_attribute(campaign_id=test_campaign, label="Old Label")
        try:
            updated = await db_update_attribute(attr["id"], test_campaign, {"label": "New Label"})
            assert updated is not None
            assert updated["label"] == "New Label"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_update_category(self, test_campaign):
        attr = await db_create_attribute(campaign_id=test_campaign, label="Cat Test")
        try:
            updated = await db_update_attribute(attr["id"], test_campaign, {"category": "Physical"})
            assert updated is not None
            assert updated["category"] == "Physical"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_update_numeric_bounds(self, test_campaign):
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Bounds Test",
            attribute_type="numeric",
        )
        try:
            updated = await db_update_attribute(
                attr["id"], test_campaign,
                {"numeric_min": 0.0, "numeric_max": 100.0},
            )
            assert updated is not None
            assert updated["numeric_min"] == 0.0
            assert updated["numeric_max"] == 100.0
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_update_options(self, test_campaign):
        attr = await db_create_attribute(
            campaign_id=test_campaign,
            label="Options Test",
            attribute_type="select",
            options=["X"],
        )
        try:
            updated = await db_update_attribute(
                attr["id"], test_campaign,
                {"options": ["X", "Y", "Z"]},
            )
            assert updated is not None
            assert updated["options"] == ["X", "Y", "Z"]
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_noop_update_returns_current(self, test_campaign):
        attr = await db_create_attribute(campaign_id=test_campaign, label="Stable")
        try:
            result = await db_update_attribute(attr["id"], test_campaign, {})
            assert result is not None
            assert result["label"] == "Stable"
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

    async def test_update_nonexistent(self, test_campaign):
        fake_id = str(uuid.uuid4())
        result = await db_update_attribute(fake_id, test_campaign, {"label": "Nope"})
        assert result is None


# ---------------------------------------------------------------------------
# CRUD: Delete
# ---------------------------------------------------------------------------


class TestDeleteAttribute:

    async def test_delete_existing(self, test_campaign):
        attr = await db_create_attribute(campaign_id=test_campaign, label="Doomed")
        result = await db_delete_attribute(attr["id"], test_campaign)
        assert result is True
        assert await db_get_attribute(attr["id"]) is None

    async def test_delete_nonexistent(self, test_campaign):
        fake_id = str(uuid.uuid4())
        result = await db_delete_attribute(fake_id, test_campaign)
        assert result is False

    async def test_delete_wrong_campaign(self, test_campaign):
        """Cannot delete an attribute using a different campaign_id."""
        attr = await db_create_attribute(campaign_id=test_campaign, label="Protected")
        try:
            fake_campaign = str(uuid.uuid4())
            result = await db_delete_attribute(attr["id"], fake_campaign)
            assert result is False
            # Still exists
            assert await db_get_attribute(attr["id"]) is not None
        finally:
            async with _acquire() as conn:
                await conn.execute("DELETE FROM playbook.attributes WHERE id = $1::uuid", attr["id"])

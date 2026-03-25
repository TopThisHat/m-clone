"""Unit tests for Attribute management business logic and validation.

Tests Pydantic model validation, row-to-dict conversion, type-change
prohibition, and edge cases without requiring a database connection.
"""
from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.campaign import (
    AttributeCreate,
    AttributeOut,
    AttributeType,
    AttributeUpdate,
)


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Pydantic Model Validation: AttributeCreate
# ---------------------------------------------------------------------------


class TestAttributeCreateModel:

    def test_minimal_create(self):
        body = AttributeCreate(label="Height")
        assert body.label == "Height"
        assert body.description is None
        assert body.weight == 1.0
        assert body.attribute_type == AttributeType.text
        assert body.category is None
        assert body.numeric_min is None
        assert body.numeric_max is None
        assert body.options is None

    def test_full_create_numeric(self):
        body = AttributeCreate(
            label="Speed",
            description="40-yard dash time",
            weight=2.0,
            attribute_type=AttributeType.numeric,
            category="Performance",
            numeric_min=4.0,
            numeric_max=6.0,
        )
        assert body.attribute_type == AttributeType.numeric
        assert body.category == "Performance"
        assert body.numeric_min == 4.0
        assert body.numeric_max == 6.0

    def test_full_create_select(self):
        body = AttributeCreate(
            label="Position",
            attribute_type=AttributeType.select,
            category="Physical",
            options=["QB", "RB", "WR"],
        )
        assert body.attribute_type == AttributeType.select
        assert body.options == ["QB", "RB", "WR"]

    def test_boolean_type(self):
        body = AttributeCreate(
            label="Is Starter",
            attribute_type=AttributeType.boolean,
        )
        assert body.attribute_type == AttributeType.boolean

    def test_create_requires_label(self):
        with pytest.raises(Exception):
            AttributeCreate()

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            AttributeCreate(label="X", attribute_type="invalid_type")


# ---------------------------------------------------------------------------
# Pydantic Model Validation: AttributeUpdate
# ---------------------------------------------------------------------------


class TestAttributeUpdateModel:

    def test_empty_update(self):
        body = AttributeUpdate()
        assert body.label is None
        assert body.description is None
        assert body.weight is None
        assert body.attribute_type is None
        assert body.category is None
        assert body.numeric_min is None
        assert body.numeric_max is None
        assert body.options is None

    def test_partial_update_label(self):
        body = AttributeUpdate(label="New Label")
        assert body.label == "New Label"
        assert body.weight is None

    def test_update_category(self):
        body = AttributeUpdate(category="Physical")
        assert body.category == "Physical"

    def test_update_numeric_bounds(self):
        body = AttributeUpdate(numeric_min=1.0, numeric_max=10.0)
        assert body.numeric_min == 1.0
        assert body.numeric_max == 10.0

    def test_update_options(self):
        body = AttributeUpdate(options=["A", "B", "C"])
        assert body.options == ["A", "B", "C"]

    def test_update_with_type_field(self):
        """attribute_type can be set on the model (validation at router level)."""
        body = AttributeUpdate(attribute_type=AttributeType.numeric)
        assert body.attribute_type == AttributeType.numeric


# ---------------------------------------------------------------------------
# Pydantic Model Validation: AttributeOut
# ---------------------------------------------------------------------------


class TestAttributeOutModel:

    def test_out_roundtrip(self):
        out = AttributeOut(
            id="abc",
            campaign_id="camp-1",
            label="Height",
            description="Player height",
            weight=1.5,
            attribute_type=AttributeType.numeric,
            category="Physical",
            numeric_min=60.0,
            numeric_max=84.0,
            options=None,
            created_at="2024-01-01T00:00:00",
        )
        assert out.id == "abc"
        assert out.attribute_type == AttributeType.numeric
        assert out.category == "Physical"
        assert out.numeric_min == 60.0

    def test_out_defaults(self):
        out = AttributeOut(
            id="abc",
            campaign_id="camp-1",
            label="Name",
            created_at="2024-01-01T00:00:00",
        )
        assert out.weight == 1.0
        assert out.attribute_type == AttributeType.text
        assert out.category is None
        assert out.numeric_min is None
        assert out.numeric_max is None
        assert out.options is None

    def test_out_with_select_options(self):
        out = AttributeOut(
            id="abc",
            campaign_id="camp-1",
            label="Position",
            attribute_type=AttributeType.select,
            options=["QB", "RB"],
            created_at="2024-01-01T00:00:00",
        )
        assert out.options == ["QB", "RB"]

    def test_out_requires_mandatory_fields(self):
        with pytest.raises(Exception):
            AttributeOut(id="abc")


# ---------------------------------------------------------------------------
# AttributeType enum
# ---------------------------------------------------------------------------


class TestAttributeTypeEnum:

    def test_valid_types(self):
        assert AttributeType.text.value == "text"
        assert AttributeType.numeric.value == "numeric"
        assert AttributeType.boolean.value == "boolean"
        assert AttributeType.select.value == "select"

    def test_from_string(self):
        assert AttributeType("text") == AttributeType.text
        assert AttributeType("numeric") == AttributeType.numeric
        assert AttributeType("boolean") == AttributeType.boolean
        assert AttributeType("select") == AttributeType.select

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            AttributeType("dropdown")


# ---------------------------------------------------------------------------
# Row-to-dict conversion
# ---------------------------------------------------------------------------


class TestAttributeRowToDict:

    def test_uuid_fields_converted_to_str(self):
        from app.db.attributes import _attribute_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Height",
            "description": None,
            "weight": 1.0,
            "attribute_type": "numeric",
            "category": "Physical",
            "numeric_min": 60.0,
            "numeric_max": 84.0,
            "options": None,
            "created_at": now,
        }
        result = _attribute_row_to_dict(row_dict)
        assert isinstance(result["id"], str)
        assert isinstance(result["campaign_id"], str)
        assert isinstance(result["created_at"], str)

    def test_none_uuid_stays_none(self):
        from app.db.attributes import _attribute_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": None,
            "label": "Test",
            "created_at": now,
        }
        result = _attribute_row_to_dict(row_dict)
        assert result["campaign_id"] is None

    def test_none_timestamp_stays_none(self):
        from app.db.attributes import _attribute_row_to_dict

        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "created_at": None,
        }
        result = _attribute_row_to_dict(row_dict)
        assert result["created_at"] is None

    def test_json_string_options_deserialized(self):
        from app.db.attributes import _attribute_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Position",
            "options": '["QB", "RB", "WR"]',
            "created_at": now,
        }
        result = _attribute_row_to_dict(row_dict)
        assert result["options"] == ["QB", "RB", "WR"]

    def test_list_options_unchanged(self):
        from app.db.attributes import _attribute_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Position",
            "options": ["QB", "RB"],
            "created_at": now,
        }
        result = _attribute_row_to_dict(row_dict)
        assert result["options"] == ["QB", "RB"]


# ---------------------------------------------------------------------------
# DB function logic (mocked DB)
# ---------------------------------------------------------------------------


class TestDbUpdateAttributeLogic:

    @pytest.mark.asyncio
    async def test_noop_update_calls_get(self):
        """When no allowed fields are provided, db_update_attribute fetches current state."""
        from app.db import attributes

        fake_attr = {
            "id": str(uuid4()),
            "campaign_id": str(uuid4()),
            "label": "Unchanged",
            "description": None,
            "weight": 1.0,
            "attribute_type": "text",
            "category": None,
            "numeric_min": None,
            "numeric_max": None,
            "options": None,
            "created_at": "2024-01-01T00:00:00",
        }
        with patch.object(attributes, "db_get_attribute", new_callable=AsyncMock, return_value=fake_attr):
            result = await attributes.db_update_attribute(fake_attr["id"], fake_attr["campaign_id"], {})
            assert result == fake_attr

    @pytest.mark.asyncio
    async def test_update_with_new_fields(self):
        """db_update_attribute accepts category, numeric_min, numeric_max, options."""
        from app.db import attributes

        attr_id = str(uuid4())
        campaign_id = str(uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)

        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Speed",
            "description": None,
            "weight": 1.0,
            "attribute_type": "numeric",
            "category": "Performance",
            "numeric_min": 4.0,
            "numeric_max": 6.0,
            "options": None,
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(attributes, "_acquire", return_value=mock_cm):
            result = await attributes.db_update_attribute(
                attr_id, campaign_id,
                {"category": "Performance", "numeric_min": 4.0, "numeric_max": 6.0},
            )
            assert result is not None
            assert result["category"] == "Performance"
            # Verify the SQL was called with correct params
            call_args = mock_conn.fetchrow.call_args
            sql = call_args[0][0]
            assert "category" in sql
            assert "numeric_min" in sql
            assert "numeric_max" in sql

    @pytest.mark.asyncio
    async def test_update_options_serialized_as_json(self):
        """db_update_attribute serialises options list to JSON string."""
        from app.db import attributes

        attr_id = str(uuid4())
        campaign_id = str(uuid4())

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(attributes, "_acquire", return_value=mock_cm):
            await attributes.db_update_attribute(
                attr_id, campaign_id,
                {"options": ["A", "B"]},
            )
            call_args = mock_conn.fetchrow.call_args
            # The options value should be a JSON string
            values = call_args[0][1:]
            assert json.dumps(["A", "B"]) in [v for v in values if isinstance(v, str)]

    @pytest.mark.asyncio
    async def test_delete_returns_bool(self):
        """db_delete_attribute returns True when DELETE affected 1 row."""
        from app.db import attributes

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(attributes, "_acquire", return_value=mock_cm):
            result = await attributes.db_delete_attribute(str(uuid4()), str(uuid4()))
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_no_rows(self):
        """db_delete_attribute returns False when DELETE affected 0 rows."""
        from app.db import attributes

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(attributes, "_acquire", return_value=mock_cm):
            result = await attributes.db_delete_attribute(str(uuid4()), str(uuid4()))
            assert result is False


# ---------------------------------------------------------------------------
# Type-change prohibition (router-level, tested via mock)
# ---------------------------------------------------------------------------


class TestTypeChangeProhibition:

    @pytest.mark.asyncio
    async def test_type_change_raises_400(self):
        """Router prohibits attribute_type changes with HTTP 400."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.routers.attributes import router
        from app.auth import get_current_user

        user_sid = "test-user-unit"
        attr_id = str(uuid4())
        campaign_id = str(uuid4())

        app = FastAPI()
        app.include_router(router)

        async def _mock_user():
            return {"sub": user_sid, "name": "Test"}

        app.dependency_overrides[get_current_user] = _mock_user

        fake_campaign = {"id": campaign_id, "owner_sid": user_sid, "team_id": None}
        fake_attr = {
            "id": attr_id,
            "campaign_id": campaign_id,
            "label": "Height",
            "attribute_type": "text",
        }

        with (
            patch("app.routers.attributes.db_get_campaign", new_callable=AsyncMock, return_value=fake_campaign),
            patch("app.routers.attributes.db_get_attribute", new_callable=AsyncMock, return_value=fake_attr),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/campaigns/{campaign_id}/attributes/{attr_id}",
                    json={"attribute_type": "numeric"},
                )
            assert resp.status_code == 400
            assert "type" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_same_type_allowed(self):
        """Sending the same type in an update should not be rejected."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.routers.attributes import router
        from app.auth import get_current_user

        user_sid = "test-user-unit"
        attr_id = str(uuid4())
        campaign_id = str(uuid4())

        app = FastAPI()
        app.include_router(router)

        async def _mock_user():
            return {"sub": user_sid, "name": "Test"}

        app.dependency_overrides[get_current_user] = _mock_user

        fake_campaign = {"id": campaign_id, "owner_sid": user_sid, "team_id": None}
        fake_attr = {
            "id": attr_id,
            "campaign_id": campaign_id,
            "label": "Height",
            "attribute_type": "text",
            "description": None,
            "weight": 1.0,
            "category": None,
            "numeric_min": None,
            "numeric_max": None,
            "options": None,
            "created_at": "2024-01-01T00:00:00",
        }

        with (
            patch("app.routers.attributes.db_get_campaign", new_callable=AsyncMock, return_value=fake_campaign),
            patch("app.routers.attributes.db_get_attribute", new_callable=AsyncMock, return_value=fake_attr),
            patch("app.routers.attributes.db_update_attribute", new_callable=AsyncMock, return_value=fake_attr),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/campaigns/{campaign_id}/attributes/{attr_id}",
                    json={"attribute_type": "text", "label": "Height Updated"},
                )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_without_type_field_succeeds(self):
        """Updating label without touching attribute_type should work."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.routers.attributes import router
        from app.auth import get_current_user

        user_sid = "test-user-unit"
        attr_id = str(uuid4())
        campaign_id = str(uuid4())

        app = FastAPI()
        app.include_router(router)

        async def _mock_user():
            return {"sub": user_sid, "name": "Test"}

        app.dependency_overrides[get_current_user] = _mock_user

        fake_campaign = {"id": campaign_id, "owner_sid": user_sid, "team_id": None}
        fake_attr = {
            "id": attr_id,
            "campaign_id": campaign_id,
            "label": "Updated Label",
            "attribute_type": "text",
            "description": None,
            "weight": 1.0,
            "category": None,
            "numeric_min": None,
            "numeric_max": None,
            "options": None,
            "created_at": "2024-01-01T00:00:00",
        }

        with (
            patch("app.routers.attributes.db_get_campaign", new_callable=AsyncMock, return_value=fake_campaign),
            patch("app.routers.attributes.db_update_attribute", new_callable=AsyncMock, return_value=fake_attr),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/api/campaigns/{campaign_id}/attributes/{attr_id}",
                    json={"label": "Updated Label"},
                )
            assert resp.status_code == 200
            assert resp.json()["label"] == "Updated Label"

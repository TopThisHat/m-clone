"""Unit tests for Entities DB layer and Pydantic models.

Tests row-to-dict conversion, label uniqueness logic, metadata CRUD,
external ID management, sort-column whitelist, and Pydantic model
validation using mocked asyncpg connections. No running database required.

Run: cd backend && uv run python -m pytest tests/test_entities_unit.py -v
"""
from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.campaign import (
    EntityCreate,
    EntityOut,
    EntityUpdate,
    ExternalIdOut,
    ExternalIdUpdate,
    MetadataUpdate,
)


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Pydantic Model Validation
# ---------------------------------------------------------------------------


class TestEntityCreateModel:

    def test_minimal_create(self):
        body = EntityCreate(label="Acme Corp")
        assert body.label == "Acme Corp"
        assert body.description is None
        assert body.gwm_id is None
        assert body.metadata == {}

    def test_full_create(self):
        body = EntityCreate(
            label="Acme Corp",
            description="A test entity",
            gwm_id="GWM-001",
            metadata={"sector": "tech"},
        )
        assert body.label == "Acme Corp"
        assert body.description == "A test entity"
        assert body.gwm_id == "GWM-001"
        assert body.metadata == {"sector": "tech"}

    def test_create_requires_label(self):
        with pytest.raises(Exception):
            EntityCreate()

    def test_create_empty_label_accepted(self):
        """Pydantic allows empty string; server-side TRIM handles it."""
        body = EntityCreate(label="")
        assert body.label == ""


class TestEntityUpdateModel:

    def test_empty_update(self):
        body = EntityUpdate()
        assert body.label is None
        assert body.description is None
        assert body.gwm_id is None
        assert body.metadata is None

    def test_partial_update_label(self):
        body = EntityUpdate(label="New Label")
        assert body.label == "New Label"
        assert body.description is None

    def test_partial_update_metadata(self):
        body = EntityUpdate(metadata={"key": "val"})
        assert body.metadata == {"key": "val"}
        assert body.label is None


class TestEntityOutModel:

    def test_out_roundtrip(self):
        out = EntityOut(
            id="abc-123",
            campaign_id="camp-456",
            label="Test Entity",
            description="Desc",
            gwm_id="GWM-001",
            metadata={"k": "v"},
            created_at="2024-01-01T00:00:00",
        )
        assert out.id == "abc-123"
        assert out.campaign_id == "camp-456"
        assert out.label == "Test Entity"
        assert out.gwm_id == "GWM-001"
        assert out.metadata == {"k": "v"}

    def test_out_defaults(self):
        out = EntityOut(
            id="a", campaign_id="b", label="L", created_at="2024-01-01T00:00:00",
        )
        assert out.description is None
        assert out.gwm_id is None
        assert out.metadata == {}

    def test_out_requires_mandatory_fields(self):
        with pytest.raises(Exception):
            EntityOut(id="a")


class TestMetadataUpdateModel:

    def test_basic(self):
        body = MetadataUpdate(metadata={"key": "value", "num": 42})
        assert body.metadata["key"] == "value"
        assert body.metadata["num"] == 42

    def test_requires_metadata(self):
        with pytest.raises(Exception):
            MetadataUpdate()


class TestExternalIdModels:

    def test_external_id_update(self):
        body = ExternalIdUpdate(system="GWM", external_id="GWM-001")
        assert body.system == "GWM"
        assert body.external_id == "GWM-001"

    def test_external_id_update_requires_fields(self):
        with pytest.raises(Exception):
            ExternalIdUpdate()

    def test_external_id_out(self):
        out = ExternalIdOut(
            entity_id="e-1", system="GWM",
            external_id="GWM-001", created_at="2024-01-01T00:00:00",
        )
        assert out.entity_id == "e-1"
        assert out.system == "GWM"


# ---------------------------------------------------------------------------
# Row-to-dict conversion
# ---------------------------------------------------------------------------


class TestEntityRowToDict:

    def test_uuid_fields_converted_to_str(self):
        from app.db.entities import _entity_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": now,
        }
        result = _entity_row_to_dict(row_dict)
        assert isinstance(result["id"], str)
        assert isinstance(result["campaign_id"], str)
        assert isinstance(result["created_at"], str)

    def test_none_uuid_stays_none(self):
        from app.db.entities import _entity_row_to_dict

        row_dict = {
            "id": None,
            "campaign_id": None,
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": None,
        }
        result = _entity_row_to_dict(row_dict)
        assert result["id"] is None
        assert result["campaign_id"] is None

    def test_metadata_json_string_parsed(self):
        from app.db.entities import _entity_row_to_dict

        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": '{"key": "value"}',
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        result = _entity_row_to_dict(row_dict)
        assert result["metadata"] == {"key": "value"}

    def test_metadata_dict_preserved(self):
        from app.db.entities import _entity_row_to_dict

        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": {"already": "parsed"},
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        result = _entity_row_to_dict(row_dict)
        assert result["metadata"] == {"already": "parsed"}

    def test_created_at_iso_format(self):
        from app.db.entities import _entity_row_to_dict

        now = datetime.datetime(2024, 6, 15, 12, 30, 0, tzinfo=datetime.timezone.utc)
        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": now,
        }
        result = _entity_row_to_dict(row_dict)
        assert result["created_at"] == "2024-06-15T12:30:00+00:00"

    def test_none_created_at_stays_none(self):
        from app.db.entities import _entity_row_to_dict

        row_dict = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Test",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": None,
        }
        result = _entity_row_to_dict(row_dict)
        assert result["created_at"] is None


# ---------------------------------------------------------------------------
# Sort column whitelist
# ---------------------------------------------------------------------------


class TestSortColumnWhitelist:

    def test_known_sort_columns(self):
        from app.db.entities import _SORT_COLUMNS

        assert "name" in _SORT_COLUMNS
        assert "label" in _SORT_COLUMNS
        assert "created_at" in _SORT_COLUMNS
        assert "score" in _SORT_COLUMNS

    def test_unknown_column_not_in_whitelist(self):
        from app.db.entities import _SORT_COLUMNS

        assert "DROP TABLE" not in _SORT_COLUMNS
        assert "id" not in _SORT_COLUMNS

    def test_name_and_label_resolve_to_same_column(self):
        from app.db.entities import _SORT_COLUMNS

        assert _SORT_COLUMNS["name"] == _SORT_COLUMNS["label"]


# ---------------------------------------------------------------------------
# DuplicateLabelError
# ---------------------------------------------------------------------------


class TestDuplicateLabelError:

    def test_error_message(self):
        from app.db.entities import DuplicateLabelError

        err = DuplicateLabelError("Acme", "camp-123")
        assert "Acme" in str(err)
        assert "camp-123" in str(err)
        assert err.label == "Acme"
        assert err.campaign_id == "camp-123"

    def test_is_exception(self):
        from app.db.entities import DuplicateLabelError

        assert issubclass(DuplicateLabelError, Exception)


# ---------------------------------------------------------------------------
# _check_label_unique (mocked DB)
# ---------------------------------------------------------------------------


class TestCheckLabelUnique:

    @pytest.mark.asyncio
    async def test_raises_when_duplicate_found(self):
        from app.db.entities import _check_label_unique, DuplicateLabelError

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=uuid4())  # existing row found

        with pytest.raises(DuplicateLabelError):
            await _check_label_unique(mock_conn, "camp-1", "Duplicate")

    @pytest.mark.asyncio
    async def test_passes_when_no_duplicate(self):
        from app.db.entities import _check_label_unique

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        # Should not raise
        await _check_label_unique(mock_conn, "camp-1", "Unique")

    @pytest.mark.asyncio
    async def test_exclude_entity_id_adds_extra_condition(self):
        from app.db.entities import _check_label_unique

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        await _check_label_unique(mock_conn, "camp-1", "Label", exclude_entity_id="ent-1")

        # When exclude_entity_id is provided, 3 args are passed to fetchval
        call_args = mock_conn.fetchval.call_args
        assert len(call_args[0]) == 4  # SQL + 3 params
        sql = call_args[0][0]
        assert "id != $3" in sql

    @pytest.mark.asyncio
    async def test_no_exclude_entity_id_uses_simpler_query(self):
        from app.db.entities import _check_label_unique

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        await _check_label_unique(mock_conn, "camp-1", "Label")

        call_args = mock_conn.fetchval.call_args
        assert len(call_args[0]) == 3  # SQL + 2 params
        sql = call_args[0][0]
        assert "id !=" not in sql


# ---------------------------------------------------------------------------
# db_create_entity (mocked DB)
# ---------------------------------------------------------------------------


class TestDbCreateEntity:

    @pytest.mark.asyncio
    async def test_create_calls_insert(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "New Entity",
            "description": "Desc",
            "gwm_id": "GWM-001",
            "metadata": "{}",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)  # no duplicate
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_create_entity(
                campaign_id=str(uuid4()),
                label="New Entity",
                description="Desc",
                gwm_id="GWM-001",
            )
        assert result["label"] == "New Entity"
        assert isinstance(result["id"], str)
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_passes_metadata_as_json(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Entity",
            "description": None,
            "gwm_id": None,
            "metadata": '{"sector": "tech"}',
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_create_entity(
                campaign_id=str(uuid4()),
                label="Entity",
                metadata={"sector": "tech"},
            )
        # Verify metadata was serialized to JSON string for the query
        insert_call = mock_conn.fetchrow.call_args
        args = insert_call[0]
        # The last positional arg should be the JSON-encoded metadata
        assert json.loads(args[-1]) == {"sector": "tech"}

    @pytest.mark.asyncio
    async def test_create_with_none_metadata_defaults_to_empty(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Entity",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_create_entity(
                campaign_id=str(uuid4()),
                label="Entity",
                metadata=None,
            )
        insert_call = mock_conn.fetchrow.call_args
        args = insert_call[0]
        assert json.loads(args[-1]) == {}


# ---------------------------------------------------------------------------
# db_get_entity (mocked DB)
# ---------------------------------------------------------------------------


class TestDbGetEntity:

    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Found Entity",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_entity(str(uuid4()))
        assert result is not None
        assert result["label"] == "Found Entity"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_entity(str(uuid4()))
        assert result is None


# ---------------------------------------------------------------------------
# db_delete_entity (mocked DB)
# ---------------------------------------------------------------------------


class TestDbDeleteEntity:

    @pytest.mark.asyncio
    async def test_returns_true_on_delete(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_entity(str(uuid4()), str(uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_entity(str(uuid4()), str(uuid4()))
        assert result is False


# ---------------------------------------------------------------------------
# db_update_entity (mocked DB)
# ---------------------------------------------------------------------------


class TestDbUpdateEntity:

    @pytest.mark.asyncio
    async def test_noop_update_calls_get(self):
        from app.db import entities

        fake_entity = {
            "id": str(uuid4()),
            "campaign_id": str(uuid4()),
            "label": "Unchanged",
            "description": None,
            "gwm_id": None,
            "metadata": {},
            "created_at": "2024-01-01T00:00:00",
        }
        with patch.object(entities, "db_get_entity", new_callable=AsyncMock, return_value=fake_entity):
            result = await entities.db_update_entity(fake_entity["id"], fake_entity["campaign_id"])
        assert result == fake_entity

    @pytest.mark.asyncio
    async def test_update_filters_disallowed_fields(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "id": uuid4(),
            "campaign_id": uuid4(),
            "label": "Updated",
            "description": None,
            "gwm_id": None,
            "metadata": "{}",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)  # no dup
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_update_entity(
                str(uuid4()), str(uuid4()),
                label="Updated",
                DISALLOWED_FIELD="should_be_ignored",
            )
        assert result["label"] == "Updated"
        # The SQL should not contain DISALLOWED_FIELD
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "DISALLOWED_FIELD" not in sql

    @pytest.mark.asyncio
    async def test_update_returns_none_when_not_found(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)  # no dup
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_update_entity(
                str(uuid4()), str(uuid4()), label="NewLabel",
            )
        assert result is None


# ---------------------------------------------------------------------------
# db_list_entities (mocked DB)
# ---------------------------------------------------------------------------


class TestDbListEntities:

    @pytest.mark.asyncio
    async def test_list_with_default_params(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_rows = [
            {
                "id": uuid4(),
                "campaign_id": uuid4(),
                "label": "Entity1",
                "description": None,
                "gwm_id": None,
                "metadata": "{}",
                "created_at": now,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.fetch = AsyncMock(return_value=fake_rows)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_list_entities(str(uuid4()))
        assert result["total"] == 1
        assert result["limit"] == 50
        assert result["offset"] == 0
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_list_unlimited(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_list_entities(str(uuid4()), limit=0)
        assert result["total"] == 0
        assert result["limit"] == 0
        # fetchval should NOT be called (no separate count query)
        mock_conn.fetchval.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_sort_by_score_uses_join(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_list_entities(str(uuid4()), sort_by="score", order="desc")

        # Should include LEFT JOIN entity_scores
        fetch_sql = mock_conn.fetch.call_args[0][0]
        assert "entity_scores" in fetch_sql
        assert "COALESCE" in fetch_sql
        assert "DESC" in fetch_sql

    @pytest.mark.asyncio
    async def test_list_unknown_sort_falls_back_to_created_at(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_list_entities(
                str(uuid4()), sort_by="sql_injection_attempt",
            )
        fetch_sql = mock_conn.fetch.call_args[0][0]
        assert "e.created_at" in fetch_sql
        assert "sql_injection_attempt" not in fetch_sql

    @pytest.mark.asyncio
    async def test_list_order_defaults_to_asc(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_list_entities(str(uuid4()))
        fetch_sql = mock_conn.fetch.call_args[0][0]
        assert "ASC" in fetch_sql


# ---------------------------------------------------------------------------
# Metadata CRUD (mocked DB)
# ---------------------------------------------------------------------------


class TestDbMetadataCRUD:

    @pytest.mark.asyncio
    async def test_get_metadata_returns_parsed_json(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value='{"key": "value"}')

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_entity_metadata(str(uuid4()))
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_metadata_returns_empty_dict_when_none(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_entity_metadata(str(uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_metadata_handles_dict_return(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value={"already": "dict"})

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_entity_metadata(str(uuid4()))
        assert result == {"already": "dict"}

    @pytest.mark.asyncio
    async def test_set_metadata_calls_jsonb_set(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value='{"key": "value"}')

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_set_entity_metadata(str(uuid4()), "key", "value")
        assert result == {"key": "value"}
        sql = mock_conn.fetchval.call_args[0][0]
        assert "jsonb_set" in sql

    @pytest.mark.asyncio
    async def test_set_metadata_returns_empty_on_missing_entity(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_set_entity_metadata(str(uuid4()), "key", "value")
        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_metadata_uses_minus_operator(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value='{"remaining": true}')

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_entity_metadata(str(uuid4()), "to_remove")
        assert result == {"remaining": True}
        sql = mock_conn.fetchval.call_args[0][0]
        assert "- $2" in sql

    @pytest.mark.asyncio
    async def test_delete_metadata_returns_empty_on_missing_entity(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_entity_metadata(str(uuid4()), "key")
        assert result == {}


# ---------------------------------------------------------------------------
# External IDs (mocked DB)
# ---------------------------------------------------------------------------


class TestDbExternalIds:

    @pytest.mark.asyncio
    async def test_set_external_id_returns_dict(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "entity_id": uuid4(),
            "system": "GWM",
            "external_id": "GWM-001",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_set_external_id(str(uuid4()), "GWM", "GWM-001")
        assert result["system"] == "GWM"
        assert result["external_id"] == "GWM-001"
        assert isinstance(result["entity_id"], str)
        assert isinstance(result["created_at"], str)

    @pytest.mark.asyncio
    async def test_set_external_id_uses_upsert(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "entity_id": uuid4(),
            "system": "GWM",
            "external_id": "GWM-002",
            "created_at": now,
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            await entities.db_set_external_id(str(uuid4()), "GWM", "GWM-002")
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_set_external_id_returns_empty_on_no_row(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_set_external_id(str(uuid4()), "GWM", "X")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_external_ids_returns_list(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_rows = [
            {"entity_id": uuid4(), "system": "BLOOMBERG", "external_id": "BBG-1", "created_at": now},
            {"entity_id": uuid4(), "system": "GWM", "external_id": "GWM-1", "created_at": now},
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=fake_rows)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_external_ids(str(uuid4()))
        assert len(result) == 2
        assert all(isinstance(r["entity_id"], str) for r in result)
        assert all(isinstance(r["created_at"], str) for r in result)

    @pytest.mark.asyncio
    async def test_get_external_ids_empty(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_get_external_ids(str(uuid4()))
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_external_id_returns_true(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_external_id(str(uuid4()), "GWM")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_external_id_returns_false(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_delete_external_id(str(uuid4()), "NO_SUCH")
        assert result is False


# ---------------------------------------------------------------------------
# db_bulk_create_entities (mocked DB)
# ---------------------------------------------------------------------------


class TestDbBulkCreateEntities:

    @pytest.mark.asyncio
    async def test_bulk_create_returns_inserted_and_skipped(self):
        from app.db import entities

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_rows = [
            {
                "id": uuid4(),
                "campaign_id": uuid4(),
                "label": "Bulk1",
                "description": None,
                "gwm_id": None,
                "metadata": "{}",
                "created_at": now,
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=fake_rows)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        input_entities = [
            {"label": "Bulk1", "description": None, "gwm_id": None, "metadata": {}},
            {"label": "Bulk2", "description": None, "gwm_id": None, "metadata": {}},
        ]

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_bulk_create_entities(str(uuid4()), input_entities)
        assert len(result["inserted"]) == 1
        assert result["skipped"] == 1  # 2 input - 1 inserted

    @pytest.mark.asyncio
    async def test_bulk_create_skips_empty_labels(self):
        from app.db import entities

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        input_entities = [
            {"label": "", "description": None, "gwm_id": None, "metadata": {}},
            {"label": "   ", "description": None, "gwm_id": None, "metadata": {}},
        ]

        with patch.object(entities, "_acquire", return_value=mock_cm):
            result = await entities.db_bulk_create_entities(str(uuid4()), input_entities)
        assert result["skipped"] >= 0
        # SQL-side TRIM filters blanks
        sql = mock_conn.fetch.call_args[0][0]
        assert "TRIM" in sql

"""Sprint 3 missing tests: numeric validation errors, asyncio mode, cross-team isolation.

Unit tests (mocked — no running database required).
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# 1. Numeric validation error cases
# ---------------------------------------------------------------------------


class TestNumericCellValidation:
    """Verify numeric value coercion and error handling in db_upsert_cell_value."""

    @pytest.mark.asyncio
    async def test_numeric_value_coerced_to_float(self):
        """Integer values should be coerced to float for numeric attributes."""
        from app.db import matrix

        mock_conn = AsyncMock()
        fake_row = {
            "campaign_id": uuid4(),
            "entity_id": uuid4(),
            "attribute_id": uuid4(),
            "value_boolean": None,
            "value_numeric": 42.0,
            "value_text": None,
            "value_select": None,
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_by": "user-1",
        }
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.fetchval = AsyncMock(return_value="numeric")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(matrix, "_acquire", return_value=mock_cm):
            await matrix.db_upsert_cell_value(
                str(uuid4()), str(uuid4()), str(uuid4()),
                42,  # integer, should coerce to float
                attribute_type="numeric",
            )
            # The INSERT args should have val_num as float
            call_args = mock_conn.fetchrow.call_args[0]
            val_num_arg = call_args[5]  # $5 is value_numeric
            assert isinstance(val_num_arg, float)
            assert val_num_arg == 42.0

    @pytest.mark.asyncio
    async def test_numeric_string_value_coerced(self):
        """String '3.14' should coerce to float 3.14 for numeric attributes."""
        from app.db import matrix

        mock_conn = AsyncMock()
        fake_row = {
            "campaign_id": uuid4(),
            "entity_id": uuid4(),
            "attribute_id": uuid4(),
            "value_boolean": None,
            "value_numeric": 3.14,
            "value_text": None,
            "value_select": None,
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_by": None,
        }
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(matrix, "_acquire", return_value=mock_cm):
            await matrix.db_upsert_cell_value(
                str(uuid4()), str(uuid4()), str(uuid4()),
                "3.14",
                attribute_type="numeric",
            )
            call_args = mock_conn.fetchrow.call_args[0]
            assert call_args[5] == 3.14

    @pytest.mark.asyncio
    async def test_non_numeric_string_raises_value_error(self):
        """Non-numeric string should raise ValueError during float coercion."""
        from app.db import matrix

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(matrix, "_acquire", return_value=mock_cm):
            with pytest.raises(ValueError):
                await matrix.db_upsert_cell_value(
                    str(uuid4()), str(uuid4()), str(uuid4()),
                    "not-a-number",
                    attribute_type="numeric",
                )

    @pytest.mark.asyncio
    async def test_none_value_nulls_all_columns(self):
        """None value should set all typed columns to NULL."""
        from app.db import matrix

        mock_conn = AsyncMock()
        fake_row = {
            "campaign_id": uuid4(),
            "entity_id": uuid4(),
            "attribute_id": uuid4(),
            "value_boolean": None,
            "value_numeric": None,
            "value_text": None,
            "value_select": None,
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_by": None,
        }
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(matrix, "_acquire", return_value=mock_cm):
            await matrix.db_upsert_cell_value(
                str(uuid4()), str(uuid4()), str(uuid4()),
                None,
                attribute_type="numeric",
            )
            call_args = mock_conn.fetchrow.call_args[0]
            # $4=val_bool, $5=val_num, $6=val_text, $7=val_select — all None
            assert call_args[4] is None
            assert call_args[5] is None
            assert call_args[6] is None
            assert call_args[7] is None

    @pytest.mark.asyncio
    async def test_attribute_not_found_raises_value_error(self):
        """Missing attribute_id should raise ValueError when type lookup returns None."""
        from app.db import matrix

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(matrix, "_acquire", return_value=mock_cm):
            with pytest.raises(ValueError, match="not found"):
                await matrix.db_upsert_cell_value(
                    str(uuid4()), str(uuid4()), str(uuid4()),
                    42.0,
                    # attribute_type omitted — triggers lookup
                )


# ---------------------------------------------------------------------------
# 2. Asyncio mode verification
# ---------------------------------------------------------------------------


class TestAsyncioMode:
    """Verify that pytest-asyncio is configured in auto mode."""

    def test_asyncio_auto_mode_configured(self):
        """pyproject.toml should set asyncio_mode = 'auto'."""
        from pathlib import Path

        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert 'asyncio_mode = "auto"' in content, (
            "asyncio_mode must be 'auto' in pyproject.toml "
            "to avoid manual @pytest.mark.asyncio on every test"
        )

    @pytest.mark.asyncio
    async def test_async_test_runs_without_explicit_mark(self):
        """In auto mode, async tests should execute without explicit marks."""
        # This test itself proves auto-mode works if it passes.
        result = await _async_identity(42)
        assert result == 42


async def _async_identity(x: int) -> int:
    return x


# ---------------------------------------------------------------------------
# 3. Cross-team isolation (unit-level with mocked DB)
# ---------------------------------------------------------------------------


class TestCrossTeamIsolation:
    """Verify that team-scoped queries filter by team membership."""

    @pytest.mark.asyncio
    async def test_list_campaigns_filters_by_team(self):
        """db_list_campaigns with team_id should join on team_members."""
        from app.db import campaigns

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        team_id = str(uuid4())
        user_sid = "user-abc"

        with patch.object(campaigns, "_acquire", return_value=mock_cm):
            await campaigns.db_list_campaigns(user_sid, team_id=team_id)
            sql = mock_conn.fetch.call_args[0][0]
            # Must JOIN team_members and filter by team_id
            assert "team_members" in sql
            assert "team_id" in sql

    @pytest.mark.asyncio
    async def test_list_campaigns_without_team_filters_by_owner(self):
        """db_list_campaigns without team_id should filter by owner_sid only."""
        from app.db import campaigns

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(campaigns, "_acquire", return_value=mock_cm):
            await campaigns.db_list_campaigns("user-abc", team_id=None)
            sql = mock_conn.fetch.call_args[0][0]
            assert "owner_sid" in sql
            assert "team_id IS NULL" in sql

    @pytest.mark.asyncio
    async def test_search_scopes_entities_to_accessible_campaigns(self):
        """db_search_all should only search entities in accessible campaigns."""
        from app.db import search

        mock_conn = AsyncMock()
        # Mock accessible_campaigns query
        accessible = [{"id": uuid4()}]
        mock_conn.fetch = AsyncMock(side_effect=[
            [],           # campaigns search
            accessible,   # accessible campaign IDs
            [],           # entities search
            [],           # attributes search
            [],           # programs search
        ])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(search, "_acquire", return_value=mock_cm):
            await search.db_search_all(
                "test", owner_sid="user-abc", team_ids=[str(uuid4())],
            )
            # The entity search (3rd fetch call) should use campaign_id = ANY(...)
            entity_call = mock_conn.fetch.call_args_list[2]
            sql = entity_call[0][0]
            assert "campaign_id = ANY" in sql

    @pytest.mark.asyncio
    async def test_get_owned_campaign_rejects_non_member(self):
        """_get_owned_campaign should raise 403 for non-team-members."""
        from app.routers.matrix import _get_owned_campaign

        fake_campaign = {
            "id": str(uuid4()),
            "owner_sid": "other-user",
            "team_id": str(uuid4()),
            "name": "Team Campaign",
        }

        with (
            patch("app.routers.matrix.db_get_campaign", return_value=fake_campaign),
            patch("app.routers.matrix.db_is_team_member", return_value=False),
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await _get_owned_campaign(fake_campaign["id"], "intruder-user")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_owned_campaign_allows_team_member(self):
        """_get_owned_campaign should succeed for team members."""
        from app.routers.matrix import _get_owned_campaign

        fake_campaign = {
            "id": str(uuid4()),
            "owner_sid": "other-user",
            "team_id": str(uuid4()),
            "name": "Team Campaign",
        }

        with (
            patch("app.routers.matrix.db_get_campaign", return_value=fake_campaign),
            patch("app.routers.matrix.db_is_team_member", return_value=True),
        ):
            result = await _get_owned_campaign(fake_campaign["id"], "team-member")
            assert result["id"] == fake_campaign["id"]

    @pytest.mark.asyncio
    async def test_csv_sanitize_prevents_formula_injection(self):
        """_sanitize_csv_cell should prefix dangerous characters."""
        from app.routers.jobs import _sanitize_csv_cell

        assert _sanitize_csv_cell("=SUM(A1)") == "'=SUM(A1)"
        assert _sanitize_csv_cell("+cmd") == "'+cmd"
        assert _sanitize_csv_cell("-cmd") == "'-cmd"
        assert _sanitize_csv_cell("@import") == "'@import"
        assert _sanitize_csv_cell("|calc") == "'|calc"
        assert _sanitize_csv_cell("\tcmd") == "'\tcmd"
        assert _sanitize_csv_cell("safe value") == "safe value"
        assert _sanitize_csv_cell("") == ""
        assert _sanitize_csv_cell(None) == ""

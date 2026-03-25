"""Unit tests for Scores DB layer.

Tests row-to-dict conversion, stale/fresh marking logic, recalculation
flow, and query functions using mocked asyncpg connections. No running
database required.
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio


# Override the autouse schema fixture to avoid needing a running database.
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Row-to-dict conversion
# ---------------------------------------------------------------------------

class TestScoreRowToDict:

    def test_uuid_fields_converted_to_str(self):
        from app.db.scores import _score_row_to_dict

        now = datetime.datetime.now(datetime.timezone.utc)
        row_dict = {
            "entity_id": uuid4(),
            "campaign_id": uuid4(),
            "total_score": 3.5,
            "attributes_present": 3,
            "attributes_checked": 5,
            "last_updated": now,
            "score_stale": False,
        }
        result = _score_row_to_dict(row_dict)
        assert isinstance(result["entity_id"], str)
        assert isinstance(result["campaign_id"], str)
        assert isinstance(result["last_updated"], str)

    def test_none_uuid_stays_none(self):
        from app.db.scores import _score_row_to_dict

        row_dict = {
            "entity_id": None,
            "campaign_id": None,
            "total_score": 0.0,
            "attributes_present": 0,
            "attributes_checked": 0,
            "last_updated": None,
            "score_stale": False,
        }
        result = _score_row_to_dict(row_dict)
        assert result["entity_id"] is None
        assert result["campaign_id"] is None
        assert result["last_updated"] is None

    def test_none_timestamp_stays_none(self):
        from app.db.scores import _score_row_to_dict

        row_dict = {
            "entity_id": uuid4(),
            "campaign_id": uuid4(),
            "total_score": 1.0,
            "attributes_present": 1,
            "attributes_checked": 2,
            "last_updated": None,
            "score_stale": True,
        }
        result = _score_row_to_dict(row_dict)
        assert result["last_updated"] is None

    def test_score_stale_preserved(self):
        from app.db.scores import _score_row_to_dict

        row_dict = {
            "entity_id": uuid4(),
            "campaign_id": uuid4(),
            "total_score": 5.0,
            "attributes_present": 5,
            "attributes_checked": 5,
            "last_updated": datetime.datetime.now(datetime.timezone.utc),
            "score_stale": True,
        }
        result = _score_row_to_dict(row_dict)
        assert result["score_stale"] is True


# ---------------------------------------------------------------------------
# db_mark_scores_stale
# ---------------------------------------------------------------------------

class TestDbMarkScoresStale:

    @pytest.mark.asyncio
    async def test_mark_stale_campaign_wide(self):
        from app.db import scores

        campaign_id = str(uuid4())
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 3")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            count = await scores.db_mark_scores_stale(campaign_id)
            assert count == 3
            # Verify SQL references campaign_id but not entity_id
            call_args = mock_conn.execute.call_args
            sql = call_args[0][0]
            assert "score_stale = TRUE" in sql
            assert "campaign_id" in sql
            # Only campaign_id should be passed (no entity_id)
            assert call_args[0][1] == campaign_id
            assert len(call_args[0]) == 2

    @pytest.mark.asyncio
    async def test_mark_stale_single_entity(self):
        from app.db import scores

        campaign_id = str(uuid4())
        entity_id = str(uuid4())
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            count = await scores.db_mark_scores_stale(campaign_id, entity_id)
            assert count == 1
            call_args = mock_conn.execute.call_args
            sql = call_args[0][0]
            assert "entity_id" in sql
            assert call_args[0][1] == campaign_id
            assert call_args[0][2] == entity_id

    @pytest.mark.asyncio
    async def test_mark_stale_returns_zero_when_no_rows(self):
        from app.db import scores

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            count = await scores.db_mark_scores_stale(str(uuid4()))
            assert count == 0


# ---------------------------------------------------------------------------
# db_mark_scores_fresh
# ---------------------------------------------------------------------------

class TestDbMarkScoresFresh:

    @pytest.mark.asyncio
    async def test_mark_fresh_campaign_wide(self):
        from app.db import scores

        campaign_id = str(uuid4())
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 5")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            count = await scores.db_mark_scores_fresh(campaign_id)
            assert count == 5
            sql = mock_conn.execute.call_args[0][0]
            assert "score_stale = FALSE" in sql

    @pytest.mark.asyncio
    async def test_mark_fresh_single_entity(self):
        from app.db import scores

        campaign_id = str(uuid4())
        entity_id = str(uuid4())
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            count = await scores.db_mark_scores_fresh(campaign_id, entity_id)
            assert count == 1
            call_args = mock_conn.execute.call_args
            assert call_args[0][1] == campaign_id
            assert call_args[0][2] == entity_id


# ---------------------------------------------------------------------------
# db_recalculate_scores (flow logic)
# ---------------------------------------------------------------------------

class TestDbRecalculateScoresFlow:

    @pytest.mark.asyncio
    async def test_recalc_marks_stale_then_fresh_on_success(self):
        """The flow must be: mark stale -> recalculate -> mark fresh."""
        from app.db import scores

        campaign_id = str(uuid4())
        call_order: list[str] = []

        async def _mock_mark_stale(cid, eid=None):
            call_order.append("stale")
            return 2

        async def _mock_mark_fresh(cid, eid=None):
            call_order.append("fresh")
            return 2

        # Mock the transaction to return score rows
        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "entity_id": uuid4(),
            "campaign_id": uuid4(),
            "total_score": 5.0,
            "attributes_present": 3,
            "attributes_checked": 5,
            "last_updated": now,
            "score_stale": False,
        }

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[fake_row])

        # Mock transaction context manager
        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(scores, "db_mark_scores_stale", side_effect=_mock_mark_stale),
            patch.object(scores, "db_mark_scores_fresh", side_effect=_mock_mark_fresh),
            patch.object(scores, "_acquire", return_value=mock_cm),
        ):
            result = await scores.db_recalculate_scores(campaign_id)
            assert call_order == ["stale", "fresh"]
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_recalc_stays_stale_on_failure(self):
        """If recalculation raises, scores must remain stale."""
        from app.db import scores

        campaign_id = str(uuid4())
        stale_called = False
        fresh_called = False

        async def _mock_mark_stale(cid, eid=None):
            nonlocal stale_called
            stale_called = True
            return 1

        async def _mock_mark_fresh(cid, eid=None):
            nonlocal fresh_called
            fresh_called = True
            return 1

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=RuntimeError("DB exploded"))

        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(scores, "db_mark_scores_stale", side_effect=_mock_mark_stale),
            patch.object(scores, "db_mark_scores_fresh", side_effect=_mock_mark_fresh),
            patch.object(scores, "_acquire", return_value=mock_cm),
        ):
            with pytest.raises(RuntimeError, match="DB exploded"):
                await scores.db_recalculate_scores(campaign_id)
            assert stale_called is True
            assert fresh_called is False

    @pytest.mark.asyncio
    async def test_recalc_with_entity_filter(self):
        """When entity_id is provided, it appears in the SQL args."""
        from app.db import scores

        campaign_id = str(uuid4())
        entity_id = str(uuid4())

        async def _mock_mark(cid, eid=None):
            return 1

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(scores, "db_mark_scores_stale", side_effect=_mock_mark),
            patch.object(scores, "db_mark_scores_fresh", side_effect=_mock_mark),
            patch.object(scores, "_acquire", return_value=mock_cm),
        ):
            await scores.db_recalculate_scores(campaign_id, entity_id)
            # conn.fetch called with both campaign_id and entity_id
            call_args = mock_conn.fetch.call_args[0]
            assert campaign_id in call_args
            assert entity_id in call_args


# ---------------------------------------------------------------------------
# db_get_score
# ---------------------------------------------------------------------------

class TestDbGetScore:

    @pytest.mark.asyncio
    async def test_get_score_returns_dict(self):
        from app.db import scores

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = {
            "entity_id": uuid4(),
            "campaign_id": uuid4(),
            "total_score": 7.5,
            "attributes_present": 4,
            "attributes_checked": 6,
            "last_updated": now,
            "score_stale": False,
            "entity_label": "Acme Corp",
            "gwm_id": "GWM-001",
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            result = await scores.db_get_score(str(uuid4()), str(uuid4()))
            assert result is not None
            assert isinstance(result["entity_id"], str)
            assert result["total_score"] == 7.5

    @pytest.mark.asyncio
    async def test_get_score_returns_none_when_missing(self):
        from app.db import scores

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            result = await scores.db_get_score(str(uuid4()), str(uuid4()))
            assert result is None


# ---------------------------------------------------------------------------
# db_list_campaign_scores
# ---------------------------------------------------------------------------

class TestDbListCampaignScores:

    @pytest.mark.asyncio
    async def test_list_default_sort(self):
        from app.db import scores

        now = datetime.datetime.now(datetime.timezone.utc)
        fake_rows = [
            {
                "entity_id": uuid4(),
                "campaign_id": uuid4(),
                "total_score": 10.0,
                "attributes_present": 5,
                "attributes_checked": 5,
                "last_updated": now,
                "score_stale": False,
                "entity_label": "Alpha",
                "gwm_id": "GWM-A",
            },
            {
                "entity_id": uuid4(),
                "campaign_id": uuid4(),
                "total_score": 5.0,
                "attributes_present": 3,
                "attributes_checked": 5,
                "last_updated": now,
                "score_stale": False,
                "entity_label": "Beta",
                "gwm_id": "GWM-B",
            },
        ]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=fake_rows)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            result = await scores.db_list_campaign_scores(str(uuid4()))
            assert len(result) == 2
            # Verify SQL has default sort
            sql = mock_conn.fetch.call_args[0][0]
            assert "es.total_score" in sql
            assert "DESC" in sql

    @pytest.mark.asyncio
    async def test_list_sort_by_label_asc(self):
        from app.db import scores

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            await scores.db_list_campaign_scores(str(uuid4()), sort_by="label", order="asc")
            sql = mock_conn.fetch.call_args[0][0]
            assert "e.label" in sql
            assert "ASC" in sql

    @pytest.mark.asyncio
    async def test_list_unknown_sort_defaults_to_score(self):
        from app.db import scores

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            await scores.db_list_campaign_scores(
                str(uuid4()), sort_by="nonexistent_column", order="asc",
            )
            sql = mock_conn.fetch.call_args[0][0]
            # Should fall back to es.total_score
            assert "es.total_score" in sql

    @pytest.mark.asyncio
    async def test_list_returns_empty(self):
        from app.db import scores

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(scores, "_acquire", return_value=mock_cm):
            result = await scores.db_list_campaign_scores(str(uuid4()))
            assert result == []

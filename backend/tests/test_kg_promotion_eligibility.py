"""Tests for KG promotion eligibility query thresholds (bead m-clone-i0kx).

Verifies that ``run_promotion_for_team()`` enforces:
  - confidence >= PROMOTION_CONFIDENCE_THRESHOLD (0.85)
  - research_session_count >= PROMOTION_SESSION_MINIMUM (2)
  - already-promoted entities are excluded

All tests mock the DB layer so no running PostgreSQL is required.

Run: cd backend && uv run python -m pytest tests/test_kg_promotion_eligibility.py -v
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.workflows.kg_promotion import (
    PROMOTION_CONFIDENCE_THRESHOLD,
    PROMOTION_SESSION_MINIMUM,
    run_promotion_for_team,
)


# Override the autouse conftest fixture that requires a real database.
@pytest.fixture(autouse=True)
async def _ensure_schema():
    """No-op override: these unit tests mock the DB entirely."""
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_row(
    entity_id: str | None = None,
    name: str = "Acme Corp",
    entity_type: str = "company",
) -> dict[str, Any]:
    """Build a fake DB row matching the eligibility SELECT columns."""
    return {
        "id": entity_id or str(uuid.uuid4()),
        "name": name,
        "entity_type": entity_type,
    }


def _make_mock_conn(eligible_rows: list[dict[str, Any]]) -> MagicMock:
    """Return a mock connection whose ``fetch()`` returns *eligible_rows*.

    The mock ``promote_entity_to_master`` is patched separately so the conn
    is only used for the eligibility query inside ``run_promotion_for_team``.
    """
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=eligible_rows)
    return conn


@asynccontextmanager
async def _fake_acquire(conn: MagicMock):
    """Drop-in replacement for ``_acquire()`` that yields *conn*."""
    yield conn


# ---------------------------------------------------------------------------
# Unit tests: eligibility query enforces thresholds
# ---------------------------------------------------------------------------

class TestEligibilityQueryParameters:
    """Verify the SQL parameters passed to the eligibility query."""

    @pytest.mark.asyncio
    async def test_confidence_threshold_passed_as_parameter(self):
        """The eligibility query must bind PROMOTION_CONFIDENCE_THRESHOLD as $2."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        conn.fetch.assert_called_once()
        args = conn.fetch.call_args
        # positional args: (sql, team_id, confidence_threshold, session_minimum)
        pos = args[0]
        assert pos[1] == team_id
        assert pos[2] == PROMOTION_CONFIDENCE_THRESHOLD
        assert pos[3] == PROMOTION_SESSION_MINIMUM

    @pytest.mark.asyncio
    async def test_session_minimum_passed_as_parameter(self):
        """The eligibility query must bind PROMOTION_SESSION_MINIMUM as $3."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        conn.fetch.assert_called_once()
        pos = conn.fetch.call_args[0]
        assert pos[3] == PROMOTION_SESSION_MINIMUM

    @pytest.mark.asyncio
    async def test_sql_contains_confidence_filter(self):
        """The eligibility SQL must include an AVG(confidence) >= $2 filter."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        sql = conn.fetch.call_args[0][0]
        assert "AVG(kr.confidence)" in sql or "AVG( kr.confidence )" in sql
        assert ">= $2" in sql

    @pytest.mark.asyncio
    async def test_sql_contains_session_count_filter(self):
        """The eligibility SQL must include a COUNT(DISTINCT source_session_id) >= $3 filter."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        sql = conn.fetch.call_args[0][0]
        assert "COUNT(DISTINCT kr.source_session_id)" in sql
        assert ">= $3" in sql

    @pytest.mark.asyncio
    async def test_sql_still_excludes_already_promoted(self):
        """The eligibility SQL must retain the NOT EXISTS check against kg_promotions."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        sql = conn.fetch.call_args[0][0]
        assert "NOT EXISTS" in sql
        assert "kg_promotions" in sql

    @pytest.mark.asyncio
    async def test_sql_joins_relationships_table(self):
        """The eligibility SQL must join kg_relationships for confidence/session data."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        sql = conn.fetch.call_args[0][0]
        assert "kg_relationships" in sql
        assert "JOIN" in sql.upper()

    @pytest.mark.asyncio
    async def test_sql_filters_relationships_by_team_id(self):
        """The JOIN on kg_relationships must filter by team_id to enforce team isolation."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ):
            await run_promotion_for_team(team_id)

        sql = conn.fetch.call_args[0][0]
        assert "kr.team_id" in sql, "JOIN must filter relationships by team_id"


# ---------------------------------------------------------------------------
# Unit tests: entity filtering behaviour (mocked DB returns)
# ---------------------------------------------------------------------------

class TestEntityFiltering:
    """Simulate DB returning various entity sets and verify promotion calls."""

    @pytest.mark.asyncio
    async def test_low_confidence_entities_excluded(self):
        """When the DB correctly returns no rows (confidence too low), no promotions occur."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])  # DB returns nothing — all below threshold

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            new_callable=AsyncMock,
        ) as mock_promote:
            result = await run_promotion_for_team(team_id)

        mock_promote.assert_not_called()
        assert result["entities_promoted"] == 0
        assert result["entities_skipped"] == 0
        assert result["relationships_promoted"] == 0

    @pytest.mark.asyncio
    async def test_insufficient_sessions_excluded(self):
        """When no entity meets session minimum, none are promoted."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])  # DB filtered them out

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            new_callable=AsyncMock,
        ) as mock_promote:
            result = await run_promotion_for_team(team_id)

        mock_promote.assert_not_called()
        assert result["entities_promoted"] == 0

    @pytest.mark.asyncio
    async def test_eligible_entities_promoted(self):
        """Entities meeting both thresholds are forwarded to promote_entity_to_master."""
        team_id = str(uuid.uuid4())
        entity_id = str(uuid.uuid4())
        master_id = str(uuid.uuid4())
        eligible = [_entity_row(entity_id=entity_id)]
        conn = _make_mock_conn(eligible)

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            new_callable=AsyncMock,
            return_value={"action": "promoted", "master_entity_id": master_id},
        ) as mock_promote, patch(
            "worker.workflows.kg_promotion.promote_relationships_to_master",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await run_promotion_for_team(team_id)

        mock_promote.assert_called_once_with(entity_id, team_id)
        assert result["entities_promoted"] == 1

    @pytest.mark.asyncio
    async def test_already_promoted_entities_excluded(self):
        """Already-promoted entities are excluded by the NOT EXISTS clause (DB returns empty)."""
        team_id = str(uuid.uuid4())
        conn = _make_mock_conn([])  # DB excluded the already-promoted entity

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            new_callable=AsyncMock,
        ) as mock_promote:
            result = await run_promotion_for_team(team_id)

        mock_promote.assert_not_called()
        assert result["entities_promoted"] == 0


# ---------------------------------------------------------------------------
# Integration-style test: full pipeline with mocked DB
# ---------------------------------------------------------------------------

class TestRunPromotionForTeamIntegration:
    """End-to-end test of run_promotion_for_team with varied entity mixes."""

    @pytest.mark.asyncio
    async def test_mixed_eligibility_only_qualifying_promoted(self):
        """Only entities the DB deems eligible (after threshold filtering) are promoted.

        Simulates a scenario where the DB returns 2 eligible entities out of a
        hypothetically larger set.
        """
        team_id = str(uuid.uuid4())
        eid_1, eid_2 = str(uuid.uuid4()), str(uuid.uuid4())
        mid_1, mid_2 = str(uuid.uuid4()), str(uuid.uuid4())

        eligible = [
            _entity_row(entity_id=eid_1, name="High Confidence Corp"),
            _entity_row(entity_id=eid_2, name="Multi Session LLC"),
        ]
        conn = _make_mock_conn(eligible)

        promote_results = {
            eid_1: {"action": "promoted", "master_entity_id": mid_1},
            eid_2: {"action": "promoted", "master_entity_id": mid_2},
        }

        async def _mock_promote(entity_id: str, tid: str) -> dict:
            return promote_results[entity_id]

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            side_effect=_mock_promote,
        ), patch(
            "worker.workflows.kg_promotion.promote_relationships_to_master",
            new_callable=AsyncMock,
            return_value=3,
        ) as mock_rel:
            result = await run_promotion_for_team(team_id)

        assert result["entities_promoted"] == 2
        assert result["entities_skipped"] == 0
        assert result["relationships_promoted"] == 3

        # Relationship promotion was called with the correct entity map
        mock_rel.assert_called_once_with(
            team_id,
            {eid_1: mid_1, eid_2: mid_2},
        )

    @pytest.mark.asyncio
    async def test_promotion_with_skipped_entities(self):
        """Entities that pass the DB query but get skipped during promote_entity_to_master."""
        team_id = str(uuid.uuid4())
        eid_ok = str(uuid.uuid4())
        eid_skip = str(uuid.uuid4())
        mid_ok = str(uuid.uuid4())

        eligible = [
            _entity_row(entity_id=eid_ok, name="Good Entity"),
            _entity_row(entity_id=eid_skip, name="Vanished Entity"),
        ]
        conn = _make_mock_conn(eligible)

        async def _mock_promote(entity_id: str, tid: str) -> dict:
            if entity_id == eid_ok:
                return {"action": "promoted", "master_entity_id": mid_ok}
            return {"action": "skipped", "master_entity_id": None}

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            side_effect=_mock_promote,
        ), patch(
            "worker.workflows.kg_promotion.promote_relationships_to_master",
            new_callable=AsyncMock,
            return_value=1,
        ):
            result = await run_promotion_for_team(team_id)

        assert result["entities_promoted"] == 1
        assert result["entities_skipped"] == 1
        assert result["relationships_promoted"] == 1

    @pytest.mark.asyncio
    async def test_no_relationships_promoted_when_no_entity_map(self):
        """If all entities are skipped, relationship promotion is not called."""
        team_id = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        eligible = [_entity_row(entity_id=eid)]
        conn = _make_mock_conn(eligible)

        with patch(
            "app.db._pool._acquire",
            return_value=_fake_acquire(conn),
        ), patch(
            "worker.workflows.kg_promotion.promote_entity_to_master",
            new_callable=AsyncMock,
            return_value={"action": "skipped", "master_entity_id": None},
        ), patch(
            "worker.workflows.kg_promotion.promote_relationships_to_master",
            new_callable=AsyncMock,
        ) as mock_rel:
            result = await run_promotion_for_team(team_id)

        mock_rel.assert_not_called()
        assert result["relationships_promoted"] == 0

    @pytest.mark.asyncio
    async def test_threshold_constants_have_expected_values(self):
        """Guard against accidental changes to the threshold constants."""
        assert PROMOTION_CONFIDENCE_THRESHOLD == 0.85
        assert PROMOTION_SESSION_MINIMUM == 2

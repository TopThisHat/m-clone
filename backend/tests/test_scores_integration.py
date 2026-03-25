"""Integration tests for Scores DB layer.

Requires a running PostgreSQL instance (docker compose up -d).
Uses the app's own pool and schema initialization via conftest.py.

Tests the full DB-backed score lifecycle: stale marking, recalculation
with real transactions, and query functions against actual data.
"""
from __future__ import annotations

import uuid

import pytest_asyncio

from app.db._pool import _acquire
from app.db.scores import (
    db_get_score,
    db_list_campaign_scores,
    db_mark_scores_fresh,
    db_mark_scores_stale,
    db_recalculate_scores,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def campaign_with_scores(test_user_sid, test_campaign):
    """Create entities, attributes, a completed validation job with results,
    and pre-computed score rows. Returns a dict of IDs for use in tests."""
    async with _acquire() as conn:
        # Create two entities
        e1 = await conn.fetchrow(
            "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2) RETURNING id",
            test_campaign, "Entity Alpha",
        )
        e2 = await conn.fetchrow(
            "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2) RETURNING id",
            test_campaign, "Entity Beta",
        )
        entity_1 = str(e1["id"])
        entity_2 = str(e2["id"])

        # Create two attributes with different weights
        a1 = await conn.fetchrow(
            "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3) RETURNING id",
            test_campaign, "Revenue Growth", 2.0,
        )
        a2 = await conn.fetchrow(
            "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3) RETURNING id",
            test_campaign, "Market Share", 1.5,
        )
        attr_1 = str(a1["id"])
        attr_2 = str(a2["id"])

        # Create a completed validation job
        job = await conn.fetchrow(
            """
            INSERT INTO playbook.validation_jobs (campaign_id, triggered_by, status, completed_at)
            VALUES ($1::uuid, 'test', 'done', NOW()) RETURNING id
            """,
            test_campaign,
        )
        job_id = str(job["id"])

        # Insert validation results
        # Entity 1: both attributes present
        await conn.execute(
            """
            INSERT INTO playbook.validation_results (job_id, entity_id, attribute_id, present, confidence, evidence)
            VALUES ($1::uuid, $2::uuid, $3::uuid, TRUE, 0.95, 'Found in annual report')
            """,
            job_id, entity_1, attr_1,
        )
        await conn.execute(
            """
            INSERT INTO playbook.validation_results (job_id, entity_id, attribute_id, present, confidence, evidence)
            VALUES ($1::uuid, $2::uuid, $3::uuid, TRUE, 0.8, 'Market data shows growth')
            """,
            job_id, entity_1, attr_2,
        )
        # Entity 2: only first attribute present
        await conn.execute(
            """
            INSERT INTO playbook.validation_results (job_id, entity_id, attribute_id, present, confidence, evidence)
            VALUES ($1::uuid, $2::uuid, $3::uuid, TRUE, 0.7, 'Partial evidence')
            """,
            job_id, entity_2, attr_1,
        )
        await conn.execute(
            """
            INSERT INTO playbook.validation_results (job_id, entity_id, attribute_id, present, confidence, evidence)
            VALUES ($1::uuid, $2::uuid, $3::uuid, FALSE, 0.3, 'No evidence found')
            """,
            job_id, entity_2, attr_2,
        )

        # Pre-seed entity_scores so stale marking has rows to update
        await conn.execute(
            """
            INSERT INTO playbook.entity_scores (entity_id, campaign_id, total_score, attributes_present, attributes_checked, last_updated, score_stale)
            VALUES ($1::uuid, $2::uuid, 3.5, 2, 2, NOW(), FALSE)
            """,
            entity_1, test_campaign,
        )
        await conn.execute(
            """
            INSERT INTO playbook.entity_scores (entity_id, campaign_id, total_score, attributes_present, attributes_checked, last_updated, score_stale)
            VALUES ($1::uuid, $2::uuid, 2.0, 1, 2, NOW(), FALSE)
            """,
            entity_2, test_campaign,
        )

    yield {
        "campaign_id": test_campaign,
        "entity_1": entity_1,
        "entity_2": entity_2,
        "attr_1": attr_1,
        "attr_2": attr_2,
        "job_id": job_id,
    }

    # Cleanup is handled by test_campaign CASCADE delete


# ---------------------------------------------------------------------------
# Stale Marking
# ---------------------------------------------------------------------------

class TestMarkScoresStale:

    async def test_mark_all_stale(self, campaign_with_scores):
        """Mark all scores in a campaign as stale."""
        ids = campaign_with_scores
        count = await db_mark_scores_stale(ids["campaign_id"])
        assert count == 2

        # Verify both are stale
        async with _acquire() as conn:
            rows = await conn.fetch(
                "SELECT score_stale FROM playbook.entity_scores WHERE campaign_id = $1::uuid",
                ids["campaign_id"],
            )
        assert all(r["score_stale"] is True for r in rows)

    async def test_mark_single_entity_stale(self, campaign_with_scores):
        """Mark only one entity's score as stale."""
        ids = campaign_with_scores
        count = await db_mark_scores_stale(ids["campaign_id"], ids["entity_1"])
        assert count == 1

        # Verify only entity_1 is stale
        async with _acquire() as conn:
            row1 = await conn.fetchrow(
                "SELECT score_stale FROM playbook.entity_scores WHERE entity_id = $1::uuid AND campaign_id = $2::uuid",
                ids["entity_1"], ids["campaign_id"],
            )
            row2 = await conn.fetchrow(
                "SELECT score_stale FROM playbook.entity_scores WHERE entity_id = $1::uuid AND campaign_id = $2::uuid",
                ids["entity_2"], ids["campaign_id"],
            )
        assert row1["score_stale"] is True
        assert row2["score_stale"] is False

    async def test_mark_stale_nonexistent_campaign(self):
        """Marking stale on a campaign with no scores returns 0."""
        count = await db_mark_scores_stale(str(uuid.uuid4()))
        assert count == 0


# ---------------------------------------------------------------------------
# Fresh Marking
# ---------------------------------------------------------------------------

class TestMarkScoresFresh:

    async def test_mark_all_fresh(self, campaign_with_scores):
        """Mark stale then fresh: scores should be unstale."""
        ids = campaign_with_scores
        await db_mark_scores_stale(ids["campaign_id"])
        count = await db_mark_scores_fresh(ids["campaign_id"])
        assert count == 2

        async with _acquire() as conn:
            rows = await conn.fetch(
                "SELECT score_stale FROM playbook.entity_scores WHERE campaign_id = $1::uuid",
                ids["campaign_id"],
            )
        assert all(r["score_stale"] is False for r in rows)

    async def test_mark_single_entity_fresh(self, campaign_with_scores):
        """Mark all stale then mark only one entity fresh."""
        ids = campaign_with_scores
        await db_mark_scores_stale(ids["campaign_id"])
        count = await db_mark_scores_fresh(ids["campaign_id"], ids["entity_1"])
        assert count == 1

        async with _acquire() as conn:
            row1 = await conn.fetchrow(
                "SELECT score_stale FROM playbook.entity_scores WHERE entity_id = $1::uuid AND campaign_id = $2::uuid",
                ids["entity_1"], ids["campaign_id"],
            )
            row2 = await conn.fetchrow(
                "SELECT score_stale FROM playbook.entity_scores WHERE entity_id = $1::uuid AND campaign_id = $2::uuid",
                ids["entity_2"], ids["campaign_id"],
            )
        assert row1["score_stale"] is False
        assert row2["score_stale"] is True


# ---------------------------------------------------------------------------
# Recalculation
# ---------------------------------------------------------------------------

class TestRecalculateScores:

    async def test_recalculate_all(self, campaign_with_scores):
        """Recalculate scores from validation results."""
        ids = campaign_with_scores
        results = await db_recalculate_scores(ids["campaign_id"])

        # Should have two score rows
        assert len(results) == 2

        # Find scores by entity
        by_entity = {r["entity_id"]: r for r in results}

        # Entity 1: both attributes present (weight 2.0 + 1.5 = 3.5)
        e1 = by_entity[ids["entity_1"]]
        assert e1["total_score"] == 3.5
        assert e1["attributes_present"] == 2
        assert e1["attributes_checked"] == 2
        assert e1["score_stale"] is False

        # Entity 2: only attr_1 present (weight 2.0)
        e2 = by_entity[ids["entity_2"]]
        assert e2["total_score"] == 2.0
        assert e2["attributes_present"] == 1
        assert e2["attributes_checked"] == 2
        assert e2["score_stale"] is False

    async def test_recalculate_single_entity(self, campaign_with_scores):
        """Recalculate only one entity's score."""
        ids = campaign_with_scores
        results = await db_recalculate_scores(ids["campaign_id"], ids["entity_1"])

        # Should only recalculate entity_1
        assert len(results) == 1
        assert results[0]["entity_id"] == ids["entity_1"]
        assert results[0]["total_score"] == 3.5

    async def test_recalculate_marks_fresh_after_success(self, campaign_with_scores):
        """After successful recalculation, all scores should be fresh."""
        ids = campaign_with_scores
        await db_recalculate_scores(ids["campaign_id"])

        async with _acquire() as conn:
            rows = await conn.fetch(
                "SELECT score_stale FROM playbook.entity_scores WHERE campaign_id = $1::uuid",
                ids["campaign_id"],
            )
        assert all(r["score_stale"] is False for r in rows)

    async def test_recalculate_empty_campaign(self, test_user_sid, test_campaign):
        """Recalculating a campaign with no results returns empty list."""
        results = await db_recalculate_scores(test_campaign)
        assert results == []

    async def test_recalculate_idempotent(self, campaign_with_scores):
        """Running recalculate twice produces the same scores."""
        ids = campaign_with_scores
        first = await db_recalculate_scores(ids["campaign_id"])
        second = await db_recalculate_scores(ids["campaign_id"])

        by_entity_first = {r["entity_id"]: r["total_score"] for r in first}
        by_entity_second = {r["entity_id"]: r["total_score"] for r in second}
        assert by_entity_first == by_entity_second


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestGetScore:

    async def test_get_existing_score(self, campaign_with_scores):
        """Retrieve a single entity's score."""
        ids = campaign_with_scores
        score = await db_get_score(ids["campaign_id"], ids["entity_1"])
        assert score is not None
        assert score["entity_id"] == ids["entity_1"]
        assert score["campaign_id"] == ids["campaign_id"]
        assert isinstance(score["total_score"], float)
        assert "entity_label" in score

    async def test_get_nonexistent_score(self, test_campaign):
        """Fetching a score for a nonexistent entity returns None."""
        result = await db_get_score(test_campaign, str(uuid.uuid4()))
        assert result is None


class TestListCampaignScores:

    async def test_list_default_sort_desc(self, campaign_with_scores):
        """Default sort is by score descending."""
        ids = campaign_with_scores
        scores = await db_list_campaign_scores(ids["campaign_id"])
        assert len(scores) == 2
        # First should have higher score
        assert scores[0]["total_score"] >= scores[1]["total_score"]

    async def test_list_sort_by_label_asc(self, campaign_with_scores):
        """Sort by entity label ascending."""
        ids = campaign_with_scores
        scores = await db_list_campaign_scores(ids["campaign_id"], sort_by="label", order="asc")
        labels = [s["entity_label"] for s in scores]
        assert labels == sorted(labels)

    async def test_list_sort_by_label_desc(self, campaign_with_scores):
        """Sort by entity label descending."""
        ids = campaign_with_scores
        scores = await db_list_campaign_scores(ids["campaign_id"], sort_by="label", order="desc")
        labels = [s["entity_label"] for s in scores]
        assert labels == sorted(labels, reverse=True)

    async def test_list_empty_campaign(self, test_campaign):
        """A campaign with no scores returns empty list."""
        scores = await db_list_campaign_scores(test_campaign)
        assert scores == []

    async def test_list_contains_stale_flag(self, campaign_with_scores):
        """Score dicts include the score_stale field."""
        ids = campaign_with_scores
        scores = await db_list_campaign_scores(ids["campaign_id"])
        for s in scores:
            assert "score_stale" in s

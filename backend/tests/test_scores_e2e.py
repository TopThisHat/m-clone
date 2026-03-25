"""E2E tests for the score calculation pipeline.

Tests the complete end-to-end flow: creating a campaign with entities
and attributes, running validation, recalculating scores with stale
marking, and verifying the final state. Operates against a real
PostgreSQL database through the full DB layer.

Since there is no dedicated scores REST router (scores are accessed via
the validation and campaign endpoints), these tests exercise the full
lifecycle at the DB function level, including transactional guarantees.
"""
from __future__ import annotations

import uuid

from app.db._pool import _acquire
from app.db.scores import (
    db_get_score,
    db_list_campaign_scores,
    db_mark_scores_fresh,
    db_mark_scores_stale,
    db_recalculate_scores,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_campaign_data(
    conn,
    campaign_id: str,
    *,
    entity_count: int = 3,
    attribute_count: int = 2,
    job_status: str = "done",
) -> dict:
    """Create entities, attributes, a validation job, and results.

    Returns a dict with all created IDs.
    """
    entities = []
    for i in range(entity_count):
        row = await conn.fetchrow(
            "INSERT INTO playbook.entities (campaign_id, label) VALUES ($1::uuid, $2) RETURNING id",
            campaign_id, f"Entity-{i}",
        )
        entities.append(str(row["id"]))

    attributes = []
    for i in range(attribute_count):
        row = await conn.fetchrow(
            "INSERT INTO playbook.attributes (campaign_id, label, weight) VALUES ($1::uuid, $2, $3) RETURNING id",
            campaign_id, f"Attribute-{i}", float(i + 1),
        )
        attributes.append(str(row["id"]))

    job = await conn.fetchrow(
        """
        INSERT INTO playbook.validation_jobs (campaign_id, triggered_by, status, completed_at)
        VALUES ($1::uuid, 'e2e-test', $2, CASE WHEN $2 = 'done' THEN NOW() ELSE NULL END) RETURNING id
        """,
        campaign_id, job_status,
    )
    job_id = str(job["id"])

    # Insert results: alternate present/absent
    for ei, eid in enumerate(entities):
        for ai, aid in enumerate(attributes):
            present = (ei + ai) % 2 == 0
            await conn.execute(
                """
                INSERT INTO playbook.validation_results
                    (job_id, entity_id, attribute_id, present, confidence, evidence)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)
                """,
                job_id, eid, aid,
                present, 0.9 if present else 0.1, f"Evidence for E{ei}-A{ai}",
            )

    return {
        "entities": entities,
        "attributes": attributes,
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Full Pipeline: Create -> Validate -> Score -> Verify
# ---------------------------------------------------------------------------

class TestFullScorePipeline:

    async def test_complete_lifecycle(self, test_user_sid, test_campaign):
        """End-to-end: seed data -> recalculate -> verify scores -> mark stale -> verify."""
        async with _acquire() as conn:
            data = await _setup_campaign_data(conn, test_campaign)

        # Step 1: Recalculate scores
        scores = await db_recalculate_scores(test_campaign)
        assert len(scores) == 3  # 3 entities

        # Step 2: Verify individual score via db_get_score
        for eid in data["entities"]:
            score = await db_get_score(test_campaign, eid)
            assert score is not None
            assert score["score_stale"] is False
            assert score["attributes_checked"] == 2

        # Step 3: Verify listing
        listed = await db_list_campaign_scores(test_campaign)
        assert len(listed) == 3
        # Default desc order -- first score >= last
        assert listed[0]["total_score"] >= listed[-1]["total_score"]

        # Step 4: Mark stale
        stale_count = await db_mark_scores_stale(test_campaign)
        assert stale_count == 3

        # Step 5: Verify all are stale
        for eid in data["entities"]:
            score = await db_get_score(test_campaign, eid)
            assert score["score_stale"] is True

        # Step 6: Recalculate again (should mark fresh)
        scores = await db_recalculate_scores(test_campaign)
        for s in scores:
            assert s["score_stale"] is False

    async def test_recalculate_after_new_job(self, test_user_sid, test_campaign):
        """Adding a second job and recalculating updates scores correctly."""
        async with _acquire() as conn:
            # First job with entities and attributes
            data = await _setup_campaign_data(
                conn, test_campaign, entity_count=2, attribute_count=2,
            )

        await db_recalculate_scores(test_campaign)

        # Add a second job with all attributes present for all entities
        async with _acquire() as conn:
            job2 = await conn.fetchrow(
                """
                INSERT INTO playbook.validation_jobs (campaign_id, triggered_by, status, completed_at)
                VALUES ($1::uuid, 'e2e-test-2', 'done', NOW()) RETURNING id
                """,
                test_campaign,
            )
            job2_id = str(job2["id"])
            for eid in data["entities"]:
                for aid in data["attributes"]:
                    await conn.execute(
                        """
                        INSERT INTO playbook.validation_results
                            (job_id, entity_id, attribute_id, present, confidence, evidence)
                        VALUES ($1::uuid, $2::uuid, $3::uuid, TRUE, 0.99, 'Updated evidence')
                        """,
                        job2_id, eid, aid,
                    )

        # Recalculate -- uses latest results (job2), so all should be present
        second_scores = await db_recalculate_scores(test_campaign)
        for s in second_scores:
            # All attributes present now: weight 1.0 + 2.0 = 3.0
            assert s["attributes_present"] == 2
            assert s["total_score"] == 3.0  # sum of weights 1.0 + 2.0


# ---------------------------------------------------------------------------
# Stale/Fresh Lifecycle
# ---------------------------------------------------------------------------

class TestStaleLifecycle:

    async def test_stale_persists_across_queries(self, test_user_sid, test_campaign):
        """Stale flag is visible via both get and list queries."""
        async with _acquire() as conn:
            data = await _setup_campaign_data(
                conn, test_campaign, entity_count=1, attribute_count=1,
            )

        await db_recalculate_scores(test_campaign)
        await db_mark_scores_stale(test_campaign)

        # Via get
        score = await db_get_score(test_campaign, data["entities"][0])
        assert score["score_stale"] is True

        # Via list
        listed = await db_list_campaign_scores(test_campaign)
        assert all(s["score_stale"] is True for s in listed)

    async def test_partial_stale_marking(self, test_user_sid, test_campaign):
        """Mark one entity stale while others remain fresh."""
        async with _acquire() as conn:
            data = await _setup_campaign_data(
                conn, test_campaign, entity_count=3, attribute_count=1,
            )

        await db_recalculate_scores(test_campaign)

        # Mark only the first entity stale
        count = await db_mark_scores_stale(test_campaign, data["entities"][0])
        assert count == 1

        # Verify mixed staleness
        stale_score = await db_get_score(test_campaign, data["entities"][0])
        fresh_score = await db_get_score(test_campaign, data["entities"][1])
        assert stale_score["score_stale"] is True
        assert fresh_score["score_stale"] is False

    async def test_fresh_only_affects_target(self, test_user_sid, test_campaign):
        """Marking one entity fresh does not affect others."""
        async with _acquire() as conn:
            data = await _setup_campaign_data(
                conn, test_campaign, entity_count=2, attribute_count=1,
            )

        await db_recalculate_scores(test_campaign)
        await db_mark_scores_stale(test_campaign)

        # Mark only entity_0 fresh
        await db_mark_scores_fresh(test_campaign, data["entities"][0])

        s0 = await db_get_score(test_campaign, data["entities"][0])
        s1 = await db_get_score(test_campaign, data["entities"][1])
        assert s0["score_stale"] is False
        assert s1["score_stale"] is True


# ---------------------------------------------------------------------------
# Sort Variations
# ---------------------------------------------------------------------------

class TestSortVariations:

    async def test_sort_by_attributes_present(self, test_user_sid, test_campaign):
        """Sort by attributes_present produces valid ordering."""
        async with _acquire() as conn:
            await _setup_campaign_data(
                conn, test_campaign, entity_count=3, attribute_count=3,
            )

        await db_recalculate_scores(test_campaign)
        scores = await db_list_campaign_scores(
            test_campaign, sort_by="attributes_present", order="desc",
        )
        attrs_present = [s["attributes_present"] for s in scores]
        assert attrs_present == sorted(attrs_present, reverse=True)

    async def test_sort_by_last_updated(self, test_user_sid, test_campaign):
        """Sort by last_updated is accepted and returns results."""
        async with _acquire() as conn:
            await _setup_campaign_data(
                conn, test_campaign, entity_count=2, attribute_count=1,
            )

        await db_recalculate_scores(test_campaign)
        scores = await db_list_campaign_scores(
            test_campaign, sort_by="last_updated", order="desc",
        )
        assert len(scores) == 2


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    async def test_recalculate_nonexistent_campaign(self):
        """Recalculating a campaign that does not exist returns empty."""
        result = await db_recalculate_scores(str(uuid.uuid4()))
        assert result == []

    async def test_get_score_nonexistent(self, test_campaign):
        """Getting a score for a nonexistent entity returns None."""
        result = await db_get_score(test_campaign, str(uuid.uuid4()))
        assert result is None

    async def test_list_scores_empty_campaign(self, test_campaign):
        """Listing scores for a campaign with no entities returns empty."""
        result = await db_list_campaign_scores(test_campaign)
        assert result == []

    async def test_recalculate_ignores_noncompleted_jobs(self, test_user_sid, test_campaign):
        """Only results from 'done' jobs are used in recalculation."""
        async with _acquire() as conn:
            # Create data with a 'running' job (not 'done')
            await _setup_campaign_data(
                conn, test_campaign,
                entity_count=2, attribute_count=1,
                job_status="running",
            )

        # Recalculate should find no results from completed jobs
        result = await db_recalculate_scores(test_campaign)
        assert result == []

    async def test_concurrent_recalculations(self, test_user_sid, test_campaign):
        """Two sequential recalculations produce consistent results."""
        async with _acquire() as conn:
            await _setup_campaign_data(
                conn, test_campaign, entity_count=2, attribute_count=2,
            )

        first = await db_recalculate_scores(test_campaign)
        second = await db_recalculate_scores(test_campaign)

        first_scores = {s["entity_id"]: s["total_score"] for s in first}
        second_scores = {s["entity_id"]: s["total_score"] for s in second}
        assert first_scores == second_scores

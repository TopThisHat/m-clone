"""Performance test: 10k entities x 200 attributes.

Verifies that matrix fetch and score recalculation complete within 5 seconds
for a realistically large campaign.

Requires a running PostgreSQL: docker compose up -d
Run: cd backend && uv run python -m pytest tests/test_matrix_perf.py -v -s
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
import pytest_asyncio

from app.db._pool import _acquire
from app.db.matrix import db_get_matrix_data
from app.db.scores import db_recalculate_scores_from_matrix

ENTITY_COUNT = 10_000
ATTRIBUTE_COUNT = 200
# Limit cell population to keep setup feasible — 5 cells per entity covers
# the query hot-path without spending minutes on INSERT.
CELLS_PER_ENTITY = 5
PERF_LIMIT_SECONDS = 5.0


@pytest_asyncio.fixture
async def perf_campaign():
    """Create a large campaign with 10k entities and 200 attributes."""
    sid = f"perf-user-{uuid.uuid4().hex[:8]}"
    async with _acquire() as conn:
        await conn.execute(
            "INSERT INTO playbook.users (sid, display_name, email) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            sid, "Perf User", f"{sid}@test.local",
        )
        row = await conn.fetchrow(
            "INSERT INTO playbook.campaigns (name, owner_sid) "
            "VALUES ($1, $2) RETURNING id",
            f"perf-campaign-{uuid.uuid4().hex[:8]}", sid,
        )
    campaign_id = str(row["id"])

    # Bulk insert entities via jsonb_array_elements
    entities_json = json.dumps([
        {"label": f"Entity-{i:05d}", "gwm_id": f"GWM-{i:05d}"}
        for i in range(ENTITY_COUNT)
    ])
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.entities (campaign_id, label, gwm_id)
            SELECT $1::uuid, TRIM(e->>'label'), NULLIF(TRIM(e->>'gwm_id'), '')
            FROM jsonb_array_elements($2::jsonb) AS e
            ON CONFLICT DO NOTHING
            """,
            campaign_id, entities_json,
        )

    # Bulk insert attributes
    attributes_json = json.dumps([
        {
            "label": f"Attr-{i:03d}",
            "attribute_type": "boolean" if i % 3 == 0 else "numeric",
            "weight": round(1.0 + (i % 5) * 0.5, 1),
            "numeric_min": 0.0 if i % 3 != 0 else None,
            "numeric_max": 100.0 if i % 3 != 0 else None,
        }
        for i in range(ATTRIBUTE_COUNT)
    ])
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.attributes
                (campaign_id, label, attribute_type, weight, numeric_min, numeric_max)
            SELECT $1::uuid,
                   TRIM(a->>'label'),
                   COALESCE(NULLIF(TRIM(a->>'attribute_type'), ''), 'text'),
                   COALESCE((a->>'weight')::float, 1.0),
                   (a->>'numeric_min')::float,
                   (a->>'numeric_max')::float
            FROM jsonb_array_elements($2::jsonb) AS a
            ON CONFLICT DO NOTHING
            """,
            campaign_id, attributes_json,
        )

    # Populate a subset of cells to exercise the scoring path
    async with _acquire() as conn:
        entity_ids = [
            r["id"] for r in await conn.fetch(
                "SELECT id FROM playbook.entities WHERE campaign_id = $1::uuid "
                "ORDER BY label LIMIT $2",
                campaign_id, ENTITY_COUNT,
            )
        ]
        attr_rows = await conn.fetch(
            "SELECT id, attribute_type FROM playbook.attributes "
            "WHERE campaign_id = $1::uuid ORDER BY label LIMIT $2",
            campaign_id, ATTRIBUTE_COUNT,
        )

        # Build cell values — pick first CELLS_PER_ENTITY attributes per entity
        values = []
        attrs_to_use = attr_rows[:CELLS_PER_ENTITY]
        for eid in entity_ids:
            for ar in attrs_to_use:
                if ar["attribute_type"] == "boolean":
                    values.append((campaign_id, str(eid), str(ar["id"]), True, None, None, None))
                else:
                    values.append((campaign_id, str(eid), str(ar["id"]), None, 42.5, None, None))

        await conn.executemany(
            """
            INSERT INTO playbook.entity_attribute_assignments
                (campaign_id, entity_id, attribute_id,
                 value_boolean, value_numeric, value_text, value_select)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
            ON CONFLICT (entity_id, attribute_id, campaign_id) DO UPDATE SET
                value_boolean = EXCLUDED.value_boolean,
                value_numeric = EXCLUDED.value_numeric
            """,
            values,
        )

    yield {"campaign_id": campaign_id, "sid": sid}

    # Cleanup
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.campaigns WHERE id = $1::uuid", campaign_id,
        )
        await conn.execute("DELETE FROM playbook.users WHERE sid = $1", sid)


@pytest.mark.asyncio
async def test_matrix_fetch_performance(perf_campaign):
    """db_get_matrix_data should return 10k entities x 200 attrs under the time limit."""
    campaign_id = perf_campaign["campaign_id"]

    start = time.perf_counter()
    result = await db_get_matrix_data(campaign_id)
    elapsed = time.perf_counter() - start

    assert len(result["entities"]) == ENTITY_COUNT
    assert len(result["attributes"]) == ATTRIBUTE_COUNT
    assert elapsed < PERF_LIMIT_SECONDS, (
        f"Matrix fetch took {elapsed:.2f}s (limit: {PERF_LIMIT_SECONDS}s)"
    )


@pytest.mark.asyncio
async def test_score_recalculation_performance(perf_campaign):
    """db_recalculate_scores_from_matrix should handle 10k entities under the time limit."""
    campaign_id = perf_campaign["campaign_id"]

    start = time.perf_counter()
    scores = await db_recalculate_scores_from_matrix(campaign_id)
    elapsed = time.perf_counter() - start

    assert len(scores) == ENTITY_COUNT
    assert elapsed < PERF_LIMIT_SECONDS, (
        f"Score recalculation took {elapsed:.2f}s (limit: {PERF_LIMIT_SECONDS}s)"
    )

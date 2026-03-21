"""
Database operations for attribute clusters.
"""
from __future__ import annotations

from typing import Any

from ._pool import _acquire


def _cluster_row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    if "campaign_id" in d and d["campaign_id"] is not None:
        d["campaign_id"] = str(d["campaign_id"])
    if "attribute_ids" in d and d["attribute_ids"] is not None:
        d["attribute_ids"] = [str(uid) for uid in d["attribute_ids"]]
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_get_clusters(campaign_id: str) -> list[dict[str, Any]]:
    """Return all attribute clusters for a campaign."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM playbook.attribute_clusters WHERE campaign_id = $1::uuid ORDER BY created_at",
            campaign_id,
        )
    return [_cluster_row_to_dict(r) for r in rows]


async def db_save_clusters(
    campaign_id: str,
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert cluster records and return them with IDs."""
    if not clusters:
        return []
    results = []
    async with _acquire() as conn:
        for c in clusters:
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.attribute_clusters
                    (campaign_id, cluster_name, attribute_ids, research_question_template)
                VALUES ($1::uuid, $2, $3::uuid[], $4)
                RETURNING *
                """,
                campaign_id,
                c["cluster_name"],
                c["attribute_ids"],
                c["research_question_template"],
            )
            results.append(_cluster_row_to_dict(row))
    return results


async def db_delete_clusters(campaign_id: str) -> None:
    """Delete all clusters for a campaign (for full re-clustering)."""
    async with _acquire() as conn:
        await conn.execute(
            "DELETE FROM playbook.attribute_clusters WHERE campaign_id = $1::uuid",
            campaign_id,
        )

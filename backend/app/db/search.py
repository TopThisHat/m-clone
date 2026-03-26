"""Cross-table full-text search across entities, attributes, campaigns, and programs."""
from __future__ import annotations

from typing import Any

from ._pool import _acquire


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "hex"):  # UUID
            d[k] = str(v)
        elif hasattr(v, "isoformat"):  # datetime
            d[k] = v.isoformat()
    return d


async def db_search_all(
    query: str,
    *,
    owner_sid: str,
    team_ids: list[str] | None = None,
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Search across entities, attributes, campaigns, and programs.

    Results are scoped to campaigns the user owns or belongs to via team membership.
    Uses full-text search (GIN search_vector) for entities and attributes, and
    trigram-indexed ILIKE for campaigns and programs.

    Args:
        query: Search term.
        owner_sid: User SID for ownership filtering.
        team_ids: Team IDs the user is a member of.
        limit: Max results per category.

    Returns:
        Dict with keys: entities, attributes, campaigns, programs.
    """
    pattern = f"%{query}%"
    team_ids = team_ids or []
    # plainto_tsquery is safe for user input — converts free text to AND-joined terms
    ts_query = query.strip()

    async with _acquire() as conn:
        # Search campaigns using trigram-indexed ILIKE
        if team_ids:
            campaigns = await conn.fetch(
                """
                SELECT id, name, description, status, owner_sid, team_id, created_at
                FROM playbook.campaigns
                WHERE (owner_sid = $1 OR team_id = ANY($3::uuid[]))
                  AND (name ILIKE $2 OR description ILIKE $2)
                ORDER BY created_at DESC
                LIMIT $4
                """,
                owner_sid, pattern, team_ids, limit,
            )
        else:
            campaigns = await conn.fetch(
                """
                SELECT id, name, description, status, owner_sid, team_id, created_at
                FROM playbook.campaigns
                WHERE owner_sid = $1
                  AND (name ILIKE $2 OR description ILIKE $2)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                owner_sid, pattern, limit,
            )

        # Get accessible campaign IDs for entity/attribute search
        if team_ids:
            accessible_campaigns = await conn.fetch(
                """
                SELECT id FROM playbook.campaigns
                WHERE owner_sid = $1 OR team_id = ANY($2::uuid[])
                """,
                owner_sid, team_ids,
            )
        else:
            accessible_campaigns = await conn.fetch(
                "SELECT id FROM playbook.campaigns WHERE owner_sid = $1",
                owner_sid,
            )
        campaign_ids = [r["id"] for r in accessible_campaigns]

        if campaign_ids:
            # Use search_vector (GIN) for full-text + ILIKE fallback for partial matches
            entities = await conn.fetch(
                """
                SELECT e.id, e.campaign_id, e.label, e.description,
                       e.gwm_id, e.created_at,
                       c.name AS campaign_name
                FROM playbook.entities e
                JOIN playbook.campaigns c ON e.campaign_id = c.id
                WHERE e.campaign_id = ANY($1::uuid[])
                  AND (
                      (e.search_vector @@ plainto_tsquery('english', $3)
                       AND $3 <> '')
                      OR e.label ILIKE $2
                      OR e.description ILIKE $2
                      OR e.gwm_id ILIKE $2
                  )
                ORDER BY
                    (e.search_vector @@ plainto_tsquery('english', $3)
                     AND $3 <> '') DESC,
                    e.created_at DESC
                LIMIT $4
                """,
                campaign_ids, pattern, ts_query, limit,
            )

            attributes = await conn.fetch(
                """
                SELECT a.id, a.campaign_id, a.label, a.description,
                       a.attribute_type, a.category,
                       c.name AS campaign_name
                FROM playbook.attributes a
                JOIN playbook.campaigns c ON a.campaign_id = c.id
                WHERE a.campaign_id = ANY($1::uuid[])
                  AND (
                      (a.search_vector @@ plainto_tsquery('english', $3)
                       AND $3 <> '')
                      OR a.label ILIKE $2
                      OR a.description ILIKE $2
                      OR a.category ILIKE $2
                  )
                ORDER BY
                    (a.search_vector @@ plainto_tsquery('english', $3)
                     AND $3 <> '') DESC,
                    a.label
                LIMIT $4
                """,
                campaign_ids, pattern, ts_query, limit,
            )
        else:
            entities = []
            attributes = []

        # Search programs using trigram-indexed ILIKE
        if team_ids:
            programs = await conn.fetch(
                """
                SELECT id, name, description, team_id, created_at
                FROM playbook.programs
                WHERE team_id = ANY($2::uuid[])
                  AND (name ILIKE $1 OR description ILIKE $1)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                pattern, team_ids, limit,
            )
        else:
            programs = []

    return {
        "campaigns": [_row_to_dict(r) for r in campaigns],
        "entities": [_row_to_dict(r) for r in entities],
        "attributes": [_row_to_dict(r) for r in attributes],
        "programs": [_row_to_dict(r) for r in programs],
    }

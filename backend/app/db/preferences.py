from __future__ import annotations

import json
import logging
from typing import Any

from ._pool import _acquire

logger = logging.getLogger(__name__)


def _preference_row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    if "campaign_id" in d and d["campaign_id"] is not None:
        d["campaign_id"] = str(d["campaign_id"])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    if "preferences" in d and isinstance(d["preferences"], str):
        d["preferences"] = json.loads(d["preferences"])
    return d


async def db_get_preferences(
    user_sid: str, campaign_id: str | None = None
) -> dict[str, Any] | None:
    """Get user preferences, optionally scoped to a campaign.

    If *campaign_id* is provided, returns campaign-specific preferences.
    Otherwise returns the user's global preferences row.
    """
    async with _acquire() as conn:
        if campaign_id:
            row = await conn.fetchrow(
                """
                SELECT * FROM playbook.user_preferences
                WHERE user_sid = $1 AND campaign_id = $2::uuid
                """,
                user_sid,
                campaign_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT * FROM playbook.user_preferences
                WHERE user_sid = $1 AND campaign_id IS NULL
                """,
                user_sid,
            )
    return _preference_row_to_dict(row) if row else None


async def db_upsert_preferences(
    user_sid: str,
    campaign_id: str | None,
    preferences_dict: dict[str, Any],
) -> dict[str, Any]:
    """Insert or update user preferences (JSONB).

    Uses INSERT ... ON CONFLICT DO UPDATE to atomically upsert.
    """
    prefs_json = json.dumps(preferences_dict)
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.user_preferences (user_sid, campaign_id, preferences)
            VALUES ($1, $2::uuid, $3::jsonb)
            ON CONFLICT (user_sid, COALESCE(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid))
            DO UPDATE SET preferences = $3::jsonb, updated_at = NOW()
            RETURNING *
            """,
            user_sid,
            campaign_id,
            prefs_json,
        )
    return _preference_row_to_dict(row)

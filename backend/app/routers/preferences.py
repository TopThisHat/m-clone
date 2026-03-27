from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.db import DatabaseNotConfigured, db_get_preferences, db_upsert_preferences
from app.models.preference import PreferencesOut, PreferencesUpsert

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


@router.get("")
async def get_preferences(
    campaign_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the current user's preferences, optionally scoped to a campaign."""
    try:
        result = await db_get_preferences(
            user_sid=user["sub"], campaign_id=campaign_id
        )
    except DatabaseNotConfigured:
        raise _no_db()
    if result is None:
        return {"preferences": {}, "campaign_id": campaign_id}
    return result


@router.put("", response_model=PreferencesOut)
async def upsert_preferences(
    body: PreferencesUpsert,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create or update the current user's preferences."""
    try:
        return await db_upsert_preferences(
            user_sid=user["sub"],
            campaign_id=body.campaign_id,
            preferences_dict=body.preferences,
        )
    except DatabaseNotConfigured:
        raise _no_db()

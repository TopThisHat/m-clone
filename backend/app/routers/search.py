"""Global search endpoint: full-text search across campaigns, entities, attributes, programs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.db import DatabaseNotConfigured
from app.db.search import db_search_all
from app.db.teams import db_list_user_teams

router = APIRouter(prefix="/api", tags=["search"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    """Search across campaigns, entities, attributes, and programs.

    Results are scoped to the user's accessible campaigns and teams.
    """
    user_sid = user["sub"]
    try:
        teams = await db_list_user_teams(user_sid)
    except DatabaseNotConfigured:
        raise _no_db()
    team_ids = [t["id"] for t in teams]
    try:
        return await db_search_all(q, owner_sid=user_sid, team_ids=team_ids, limit=limit)
    except DatabaseNotConfigured:
        raise _no_db()

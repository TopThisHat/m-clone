"""FastAPI dependency for team-scoped database access (RLS).

Provides ``get_team_id`` dependency that extracts the active team_id from the
request.  Use with ``_acquire_team()`` in DB functions to set
``SET LOCAL app.current_team_id`` for row-level security enforcement.

Usage in routers::

    from app.team_context import get_team_id

    @router.get("/api/campaigns/{id}/matrix")
    async def get_matrix(
        id: str,
        user=Depends(get_current_user),
        team_id: str | None = Depends(get_team_id),
    ):
        ...
"""
from __future__ import annotations


from fastapi import Header


async def get_team_id(
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> str | None:
    """Extract team_id from the X-Team-Id request header.

    Returns None if no header is present (personal/non-team context).
    """
    return x_team_id

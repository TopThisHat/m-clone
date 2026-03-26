"""FastAPI dependency for team-scoped database access (RLS).

**DEPRECATED** — prefer ``get_request_context`` from ``app.dependencies``
which validates team membership. This module's ``get_team_id`` does NOT
validate membership and should only be used where the caller performs
its own access check (e.g. ``_get_owned_campaign``).

Usage in routers::

    from app.dependencies import RequestContext, get_request_context

    @router.get("/api/campaigns/{id}/matrix")
    async def get_matrix(
        id: str,
        ctx: RequestContext = Depends(get_request_context),
    ):
        # ctx.team_id is validated — user is confirmed member
        ...
"""
from __future__ import annotations


from fastapi import Header


async def get_team_id(
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> str | None:
    """Extract team_id from the X-Team-Id request header.

    **WARNING**: Does NOT validate team membership. Use
    ``get_request_context`` from ``app.dependencies`` instead for
    endpoints that trust the team_id for authorization.

    Returns None if no header is present (personal/non-team context).
    """
    return x_team_id

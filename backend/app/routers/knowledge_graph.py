from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import settings
from app.db import (
    DatabaseNotConfigured,
    db_delete_kg_entity,
    db_delete_kg_relationship,
    db_get_deal_partners,
    db_get_entity_relationships,
    db_get_kg_entity,
    db_get_kg_graph,
    db_get_kg_relationship,
    db_get_kg_stats,
    db_get_member_role,
    db_get_neighbors,
    db_is_super_admin,
    db_is_team_member,
    db_list_entity_flags,
    db_list_kg_conflicts,
    db_list_kg_entities,
    db_list_user_teams,
    db_merge_kg_entities,
    db_promote_entity_to_master,
    db_query_kg,
    db_resolve_entity_flag,
    db_search_kg,
    db_sync_entity_from_master,
    db_update_kg_entity,
    db_update_kg_relationship,
)

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])

ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


def _can(role: str | None, min_role: str) -> bool:
    return ROLE_ORDER.get(role or "", -1) >= ROLE_ORDER[min_role]


async def _resolve_team_access(user: dict[str, Any], team_id: str | None) -> str:
    """Resolve team_id for the current user.  Always returns a concrete team id.

    Logic:
    - If *team_id* equals the master team id → require super admin → return it.
    - If *team_id* is provided → verify team membership → return it.
    - If no *team_id* → auto-resolve to the user's first team.
    - If the user has no teams → 403 Forbidden.
    """
    sid = user["sub"]

    if team_id:
        # Master team gate
        if team_id == settings.kg_master_team_id:
            if not await db_is_super_admin(sid):
                raise HTTPException(status_code=403, detail="Super admin access required for master graph")
            return team_id

        # Regular team — verify membership (super admins are allowed everywhere)
        is_sa = await db_is_super_admin(sid)
        if not is_sa:
            is_member = await db_is_team_member(team_id, sid)
            if not is_member:
                raise HTTPException(status_code=403, detail="Not a member of this team")
        return team_id

    # No team_id supplied — auto-resolve to first team
    teams = await db_list_user_teams(sid)
    if teams:
        return str(teams[0]["id"])
    raise HTTPException(status_code=403, detail="You must be part of a team to view the knowledge graph")


async def _require_kg_edit(user: dict[str, Any], team_id: str) -> None:
    """Ensure user has admin+ role on the team (or is super admin)."""
    sid = user["sub"]
    if await db_is_super_admin(sid):
        return
    role = await db_get_member_role(team_id, sid)
    if not _can(role, "admin"):
        raise HTTPException(status_code=403, detail="Admin or owner role required to edit the knowledge graph")


# ── Read endpoints ───────────────────────────────────────────────────────────


@router.get("/master-team-id")
async def get_master_team_id() -> dict[str, str]:
    """Return the master team id.  No auth required."""
    return {"team_id": settings.kg_master_team_id}


@router.get("/entities")
async def list_entities(
    search: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_list_kg_entities(
            search=search, entity_type=entity_type,
            team_id=team_id,
            limit=limit, offset=offset,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/entities/flags")
async def list_entity_flags(
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """List unresolved entity flags for the resolved team."""
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_list_entity_flags(team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        entity = await db_get_kg_entity(entity_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    # Verify entity belongs to the resolved team
    entity_team = entity.get("team_id")
    if entity_team and entity_team != team_id:
        raise HTTPException(status_code=403, detail="Entity does not belong to the resolved team")
    return entity


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    direction: str = Query(default="both"),
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_get_entity_relationships(
            entity_id, direction,
            team_id=team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/entities/{entity_id}/neighbors")
async def get_entity_neighbors(
    entity_id: str,
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=50, ge=1, le=200),
    exclude_ids: str | None = Query(default=None, description="Comma-separated UUIDs to exclude"),
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        exclude = [eid.strip() for eid in exclude_ids.split(",")] if exclude_ids else []
        return await db_get_neighbors(
            entity_id,
            depth=depth,
            limit=limit,
            exclude_ids=exclude,
            team_id=team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/search")
async def search_entities(
    q: str = Query(),
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_search_kg(q, team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/stats")
async def get_stats(
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_get_kg_stats(team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/graph")
async def get_graph(
    entity_types: str | None = Query(default=None, description="Comma-separated entity types"),
    predicate_families: str | None = Query(default=None, description="Comma-separated predicate families"),
    team_id: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Search by name/alias/description"),
    metadata_key: str | None = Query(default=None),
    metadata_value: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        et = [t.strip() for t in entity_types.split(",")] if entity_types else None
        pf = [f.strip() for f in predicate_families.split(",")] if predicate_families else None
        return await db_get_kg_graph(
            entity_types=et, predicate_families=pf,
            team_id=team_id,
            search=search,
            metadata_key=metadata_key, metadata_value=metadata_value,
            limit=limit,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/deal-partners")
async def get_deal_partners(
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_get_deal_partners(
            team_id=team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/conflicts")
async def list_conflicts(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_list_kg_conflicts(
            limit=limit, offset=offset,
            team_id=team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


# ── Edit endpoints (admin/owner or super_admin only) ─────────────────────────

class EntityPatch(BaseModel):
    name: str | None = None
    entity_type: str | None = None
    aliases: list[str] | None = None
    metadata: dict[str, Any] | None = None
    description: str | None = None
    disambiguation_context: str | None = None


@router.patch("/entities/{entity_id}")
async def update_entity(
    entity_id: str,
    body: EntityPatch,
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        entity = await db_get_kg_entity(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        entity_team = entity.get("team_id")
        if not entity_team:
            raise HTTPException(status_code=400, detail="Cannot determine entity team")
        await _require_kg_edit(user, entity_team)
        patch = body.model_dump(exclude_none=True)
        if body.metadata is not None:
            patch["metadata"] = json.dumps(body.metadata)
        updated = await db_update_kg_entity(entity_id, patch)
        return updated
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: str, user: dict[str, Any] = Depends(get_current_user)):
    try:
        entity = await db_get_kg_entity(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        entity_team = entity.get("team_id")
        if not entity_team:
            raise HTTPException(status_code=400, detail="Cannot determine entity team")
        await _require_kg_edit(user, entity_team)
        deleted = await db_delete_kg_entity(entity_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Entity not found")
        return {"deleted": True}
    except DatabaseNotConfigured:
        raise _no_db()


# ── Entity promote / sync / merge ─────────────────────────────────────────────

@router.post("/entities/{entity_id}/promote")
async def promote_entity(
    entity_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Promote a team entity to the master knowledge graph.  Requires admin+ role."""
    try:
        team_id = await _resolve_team_access(user, team_id)
        await _require_kg_edit(user, team_id)
        master_id = await db_promote_entity_to_master(entity_id, team_id)
        if master_id is None:
            raise HTTPException(status_code=404, detail="Entity not found in this team")
        return {"master_entity_id": master_id}
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/entities/{entity_id}/sync-from-master")
async def sync_entity_from_master(
    entity_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Sync a team entity from its master entity.  Requires admin+ role."""
    try:
        team_id = await _resolve_team_access(user, team_id)
        await _require_kg_edit(user, team_id)
        updated = await db_sync_entity_from_master(entity_id, team_id)
        if updated is None:
            raise HTTPException(status_code=400, detail="Entity has no master link or was not found")
        return updated
    except DatabaseNotConfigured:
        raise _no_db()


class MergeEntitiesRequest(BaseModel):
    winner_id: str
    loser_id: str
    team_id: str


@router.post("/entities/merge")
async def merge_entities(
    body: MergeEntitiesRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Merge two entities within the same team.  Requires admin+ role."""
    try:
        team_id = await _resolve_team_access(user, body.team_id)
        await _require_kg_edit(user, team_id)
        result = await db_merge_kg_entities(body.winner_id, body.loser_id, team_id)
        if result is None:
            raise HTTPException(
                status_code=400,
                detail="Merge failed — both entities must belong to the same team",
            )
        return result
    except DatabaseNotConfigured:
        raise _no_db()


# ── Entity flags ──────────────────────────────────────────────────────────────

@router.patch("/entities/flags/{flag_id}")
async def resolve_flag(
    flag_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Resolve an entity flag.  Requires admin+ role."""
    try:
        team_id = await _resolve_team_access(user, team_id)
        await _require_kg_edit(user, team_id)
        sid = user["sub"]
        ok = await db_resolve_entity_flag(flag_id, sid)
        if not ok:
            raise HTTPException(status_code=404, detail="Flag not found")
        return {"resolved": True}
    except DatabaseNotConfigured:
        raise _no_db()


class RelationshipPatch(BaseModel):
    predicate: str | None = None
    predicate_family: str | None = None
    confidence: float | None = None
    evidence: str | None = None


@router.patch("/relationships/{rel_id}")
async def update_relationship(
    rel_id: str,
    body: RelationshipPatch,
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        rel = await db_get_kg_relationship(rel_id)
        if not rel:
            raise HTTPException(status_code=404, detail="Relationship not found")
        rel_team = rel.get("team_id")
        if not rel_team:
            raise HTTPException(status_code=400, detail="Cannot determine relationship team")
        await _require_kg_edit(user, rel_team)
        patch = body.model_dump(exclude_none=True)
        updated = await db_update_kg_relationship(rel_id, patch)
        if not updated:
            raise HTTPException(status_code=404, detail="Relationship not found")
        return updated
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/relationships/{rel_id}")
async def delete_relationship(rel_id: str, user: dict[str, Any] = Depends(get_current_user)):
    try:
        rel = await db_get_kg_relationship(rel_id)
        if not rel:
            raise HTTPException(status_code=404, detail="Relationship not found")
        rel_team = rel.get("team_id")
        if not rel_team:
            raise HTTPException(status_code=400, detail="Cannot determine relationship team")
        await _require_kg_edit(user, rel_team)
        deleted = await db_delete_kg_relationship(rel_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Relationship not found")
        return {"deleted": True}
    except DatabaseNotConfigured:
        raise _no_db()


# ── Query endpoint (for agent tool + direct use) ────────────────────────────

@router.get("/query")
async def query_graph(
    q: str = Query(description="Natural language or keyword query"),
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    try:
        team_id = await _resolve_team_access(user, team_id)
        return await db_query_kg(q, team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


# ── Super admin: view any team's graph ───────────────────────────────────────

@router.get("/admin/graph/{target_team_id}")
async def admin_get_team_graph(
    target_team_id: str,
    entity_types: str | None = Query(default=None),
    predicate_families: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Super admin endpoint to view any team's knowledge graph."""
    try:
        sid = user["sub"]
        is_sa = await db_is_super_admin(sid)
        if not is_sa:
            raise HTTPException(status_code=403, detail="Super admin access required")
        et = [t.strip() for t in entity_types.split(",")] if entity_types else None
        pf = [f.strip() for f in predicate_families.split(",")] if predicate_families else None
        return await db_get_kg_graph(
            entity_types=et, predicate_families=pf,
            team_id=target_team_id, search=search,
            limit=limit,
        )
    except DatabaseNotConfigured:
        raise _no_db()

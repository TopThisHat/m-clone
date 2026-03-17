from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_get_entity_relationships,
    db_get_kg_entity,
    db_get_kg_stats,
    db_list_kg_conflicts,
    db_list_kg_entities,
    db_search_kg,
)

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


@router.get("/entities")
async def list_entities(
    search: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    user=Depends(get_current_user),
):
    try:
        return await db_list_kg_entities(search=search, entity_type=entity_type, limit=limit, offset=offset)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, user=Depends(get_current_user)):
    try:
        entity = await db_get_kg_entity(entity_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    direction: str = Query(default="both"),
    user=Depends(get_current_user),
):
    try:
        return await db_get_entity_relationships(entity_id, direction)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/search")
async def search_entities(q: str = Query(), user=Depends(get_current_user)):
    try:
        return await db_search_kg(q)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/stats")
async def get_stats(user=Depends(get_current_user)):
    try:
        return await db_get_kg_stats()
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/conflicts")
async def list_conflicts(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    user=Depends(get_current_user),
):
    try:
        return await db_list_kg_conflicts(limit=limit, offset=offset)
    except DatabaseNotConfigured:
        raise _no_db()

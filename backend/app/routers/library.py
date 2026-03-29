from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_bulk_create_attribute_library,
    db_bulk_create_entity_library,
    db_bulk_delete_library_attributes,
    db_bulk_delete_library_entities,
    db_create_attribute_library,
    db_create_entity_library,
    db_delete_attribute_library,
    db_delete_entity_library,
    db_is_team_member,
    db_list_attribute_library,
    db_list_entity_library,
    db_update_attribute_library,
    db_update_entity_library,
)

router = APIRouter(prefix="/api/library", tags=["library"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


async def _assert_team_access(team_id: str | None, user_sid: str) -> None:
    """Raise 403 if team_id is provided and user is not a member."""
    if team_id:
        if not await db_is_team_member(team_id, user_sid):
            raise HTTPException(status_code=403, detail="Forbidden")


# ── Pydantic models ────────────────────────────────────────────────────────────

class LibraryEntityCreate(BaseModel):
    label: str
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] = {}
    team_id: str | None = None


class LibraryEntityUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] | None = None


class LibraryAttributeCreate(BaseModel):
    label: str
    description: str | None = None
    weight: float = 1.0
    team_id: str | None = None


class LibraryAttributeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    weight: float | None = None


class BulkLibraryEntityBody(BaseModel):
    items: list[LibraryEntityCreate]
    team_id: str | None = None


class BulkLibraryAttributeBody(BaseModel):
    items: list[LibraryAttributeCreate]
    team_id: str | None = None


class BulkDeleteBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


# ── Entity library endpoints ───────────────────────────────────────────────────

@router.get("/entities")
async def list_library_entities(
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=10000),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="asc"),
    user: dict[str, Any] = Depends(get_current_user),
):
    await _assert_team_access(team_id, user["sub"])
    try:
        return await db_list_entity_library(
            user["sub"], team_id, limit=limit, offset=offset, search=search, sort_by=sort_by, sort_dir=sort_dir
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/entities", status_code=201)
async def create_library_entity(body: LibraryEntityCreate, user: dict[str, Any] = Depends(get_current_user)):
    await _assert_team_access(body.team_id, user["sub"])
    try:
        return await db_create_entity_library(
            owner_sid=user["sub"],
            team_id=body.team_id,
            label=body.label,
            description=body.description,
            gwm_id=body.gwm_id,
            metadata=body.metadata,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/entities/bulk", status_code=201)
async def bulk_create_library_entities(body: BulkLibraryEntityBody, user: dict[str, Any] = Depends(get_current_user)):
    await _assert_team_access(body.team_id, user["sub"])
    items = [i.model_dump(exclude={"team_id"}) for i in body.items]
    try:
        return await db_bulk_create_entity_library(user["sub"], body.team_id, items)
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/entities/{item_id}")
async def update_library_entity(item_id: str, body: LibraryEntityUpdate, user: dict[str, Any] = Depends(get_current_user)):
    try:
        updated = await db_update_entity_library(item_id, user["sub"], **body.model_dump(exclude_none=True))
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Entity not found")
    return updated


@router.delete("/entities/bulk", status_code=200)
async def bulk_delete_library_entities(body: BulkDeleteBody, user: dict[str, Any] = Depends(get_current_user)):
    if not body.ids:
        return {"deleted": 0}
    try:
        deleted = await db_bulk_delete_library_entities(user["sub"], body.ids)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"deleted": deleted}


@router.delete("/entities/{item_id}", status_code=204)
async def delete_library_entity(item_id: str, user: dict[str, Any] = Depends(get_current_user)):
    try:
        deleted = await db_delete_entity_library(item_id, user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Entity not found")
    return Response(status_code=204)


# ── Attribute library endpoints ────────────────────────────────────────────────

@router.get("/attributes")
async def list_library_attributes(
    team_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=0, le=10000),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="asc"),
    user: dict[str, Any] = Depends(get_current_user),
):
    await _assert_team_access(team_id, user["sub"])
    try:
        return await db_list_attribute_library(
            user["sub"], team_id, limit=limit, offset=offset, search=search, sort_by=sort_by, sort_dir=sort_dir
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/attributes", status_code=201)
async def create_library_attribute(body: LibraryAttributeCreate, user: dict[str, Any] = Depends(get_current_user)):
    await _assert_team_access(body.team_id, user["sub"])
    try:
        return await db_create_attribute_library(
            owner_sid=user["sub"],
            team_id=body.team_id,
            label=body.label,
            description=body.description,
            weight=body.weight,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/attributes/bulk", status_code=201)
async def bulk_create_library_attributes(body: BulkLibraryAttributeBody, user: dict[str, Any] = Depends(get_current_user)):
    await _assert_team_access(body.team_id, user["sub"])
    items = [i.model_dump(exclude={"team_id"}) for i in body.items]
    try:
        return await db_bulk_create_attribute_library(user["sub"], body.team_id, items)
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/attributes/{item_id}")
async def update_library_attribute(item_id: str, body: LibraryAttributeUpdate, user: dict[str, Any] = Depends(get_current_user)):
    try:
        updated = await db_update_attribute_library(item_id, user["sub"], **body.model_dump(exclude_none=True))
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return updated


@router.delete("/attributes/bulk", status_code=200)
async def bulk_delete_library_attributes(body: BulkDeleteBody, user: dict[str, Any] = Depends(get_current_user)):
    if not body.ids:
        return {"deleted": 0}
    try:
        deleted = await db_bulk_delete_library_attributes(user["sub"], body.ids)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"deleted": deleted}


@router.delete("/attributes/{item_id}", status_code=204)
async def delete_library_attribute(item_id: str, user: dict[str, Any] = Depends(get_current_user)):
    try:
        deleted = await db_delete_attribute_library(item_id, user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return Response(status_code=204)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import get_current_user
from pydantic import BaseModel, Field

from app.db import (
    DatabaseNotConfigured,
    DuplicateLabelError,
    db_assign_entities_to_campaign,
    db_bulk_create_entities,
    db_create_entity,
    db_delete_entity,
    db_delete_entity_metadata,
    db_delete_external_id,
    db_get_campaign,
    db_get_entity,
    db_get_entity_metadata,
    db_get_external_ids,
    db_import_entities,
    db_import_entities_from_library,
    db_is_team_member,
    db_list_entities,
    db_set_entity_metadata,
    db_set_external_id,
    db_unassign_entities_from_campaign,
    db_update_entity,
)
from app.models.campaign import (
    BulkEntityResult,
    EntityAssignBody,
    EntityCreate,
    EntityOut,
    EntityUnassignBody,
    EntityUpdate,
    ExternalIdOut,
    ExternalIdUpdate,
    ImportBody,
    ImportResult,
    MetadataUpdate,
)


class ImportLibraryBody(BaseModel):
    ids: list[str] = Field(min_length=1)

router = APIRouter(prefix="/api/campaigns", tags=["entities"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


async def _get_owned_campaign(campaign_id: str, user_sid: str):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("team_id"):
        if not await db_is_team_member(campaign["team_id"], user_sid):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif campaign["owner_sid"] != user_sid:
        raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


async def _get_entity_or_404(entity_id: str) -> dict:
    """Fetch entity or raise 404."""
    try:
        entity = await db_get_entity(entity_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


# ── List entities with sorting ────────────────────────────────────────────────

@router.get("/{campaign_id}/entities")
async def list_entities(
    campaign_id: str,
    user=Depends(get_current_user),
    limit: int = Query(default=50, ge=0, le=10000),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at", pattern="^(name|label|created_at|score)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_entities(
            campaign_id, limit=limit, offset=offset, search=search,
            sort_by=sort_by, order=order,
        )
    except DatabaseNotConfigured:
        raise _no_db()


# ── Create entity ────────────────────────────────────────────────────────────

@router.post("/{campaign_id}/entities", response_model=EntityOut, status_code=201)
async def create_entity(campaign_id: str, body: EntityCreate, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_create_entity(
            campaign_id=campaign_id,
            label=body.label,
            description=body.description,
            gwm_id=body.gwm_id,
            metadata=body.metadata,
        )
    except DuplicateLabelError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DatabaseNotConfigured:
        raise _no_db()


# ── Bulk create entities ──────────────────────────────────────────────────────

@router.post("/{campaign_id}/entities/bulk", response_model=BulkEntityResult, status_code=201)
async def bulk_create_entities(campaign_id: str, body: list[EntityCreate], user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    if not body:
        return {"inserted": [], "skipped": 0}
    # Deduplicate within the request by both label and gwm_id
    seen_labels: set[str] = set()
    seen_gwm_ids: set[str] = set()
    deduped: list[dict] = []
    for e in body:
        label_key = e.label.strip().lower()
        if not label_key or label_key in seen_labels:
            continue
        gwm_id = (e.gwm_id or "").strip().lower() if e.gwm_id else None
        if gwm_id and gwm_id in seen_gwm_ids:
            continue
        seen_labels.add(label_key)
        if gwm_id:
            seen_gwm_ids.add(gwm_id)
        deduped.append(e.model_dump())
    skipped_in_request = len(body) - len(deduped)
    try:
        result = await db_bulk_create_entities(campaign_id, deduped)
        result["skipped"] = result.get("skipped", 0) + skipped_in_request
        return result
    except DatabaseNotConfigured:
        raise _no_db()
    except Exception:
        raise HTTPException(status_code=422, detail="Bulk insert failed due to a data conflict")


# ── Import entities ───────────────────────────────────────────────────────────

@router.post("/{campaign_id}/entities/import", response_model=ImportResult, status_code=201)
async def import_entities(campaign_id: str, body: ImportBody, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_owned_campaign(body.source_campaign_id, user["sub"])
    try:
        return await db_import_entities(
            target_campaign_id=campaign_id,
            source_campaign_id=body.source_campaign_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/entities/import-library", response_model=ImportResult, status_code=201)
async def import_entities_from_library(campaign_id: str, body: ImportLibraryBody, user=Depends(get_current_user)):
    campaign = await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_import_entities_from_library(
            campaign_id, body.ids, owner_sid=user["sub"], team_id=campaign.get("team_id"),
        )
    except DatabaseNotConfigured:
        raise _no_db()


# ── Assign / Unassign entities ────────────────────────────────────────────────

@router.post("/{campaign_id}/entities/assign", response_model=BulkEntityResult, status_code=201)
async def assign_entities(campaign_id: str, body: EntityAssignBody, user=Depends(get_current_user)):
    """Assign existing library entities to a campaign (copies them in)."""
    await _get_owned_campaign(campaign_id, user["sub"])
    if not body.entity_ids:
        return {"inserted": [], "skipped": 0}
    try:
        return await db_assign_entities_to_campaign(campaign_id, body.entity_ids)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/entities/unassign", status_code=200)
async def unassign_entities(campaign_id: str, body: EntityUnassignBody, user=Depends(get_current_user)):
    """Remove entities from a campaign."""
    await _get_owned_campaign(campaign_id, user["sub"])
    if not body.entity_ids:
        return {"removed": 0}
    try:
        removed = await db_unassign_entities_from_campaign(campaign_id, body.entity_ids)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"removed": removed}


# ── Update entity ────────────────────────────────────────────────────────────

@router.patch("/{campaign_id}/entities/{entity_id}", response_model=EntityOut)
async def update_entity(campaign_id: str, entity_id: str, body: EntityUpdate, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        updated = await db_update_entity(entity_id, campaign_id, **body.model_dump(exclude_none=True))
    except DuplicateLabelError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Entity not found")
    return updated


# ── Delete entity ────────────────────────────────────────────────────────────

@router.delete("/{campaign_id}/entities/{entity_id}", status_code=204)
async def delete_entity(campaign_id: str, entity_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        deleted = await db_delete_entity(entity_id=entity_id, campaign_id=campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Entity not found")
    return Response(status_code=204)


# ── Metadata endpoints ───────────────────────────────────────────────────────

@router.get("/{campaign_id}/entities/{entity_id}/metadata")
async def get_entity_metadata(
    campaign_id: str, entity_id: str, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        return await db_get_entity_metadata(entity_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.put("/{campaign_id}/entities/{entity_id}/metadata")
async def set_entity_metadata(
    campaign_id: str, entity_id: str, body: MetadataUpdate, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        result: dict = {}
        for key, value in body.metadata.items():
            result = await db_set_entity_metadata(entity_id, key, value)
        return result
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{campaign_id}/entities/{entity_id}/metadata/{key}", status_code=200)
async def delete_entity_metadata_key(
    campaign_id: str, entity_id: str, key: str, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        return await db_delete_entity_metadata(entity_id, key)
    except DatabaseNotConfigured:
        raise _no_db()


# ── External IDs endpoints ───────────────────────────────────────────────────

@router.get("/{campaign_id}/entities/{entity_id}/external-ids", response_model=list[ExternalIdOut])
async def get_external_ids(
    campaign_id: str, entity_id: str, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        return await db_get_external_ids(entity_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.put("/{campaign_id}/entities/{entity_id}/external-ids", response_model=ExternalIdOut)
async def set_external_id(
    campaign_id: str, entity_id: str, body: ExternalIdUpdate, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        return await db_set_external_id(entity_id, body.system, body.external_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{campaign_id}/entities/{entity_id}/external-ids/{system}", status_code=204)
async def delete_external_id(
    campaign_id: str, entity_id: str, system: str, user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_entity_or_404(entity_id)
    try:
        deleted = await db_delete_external_id(entity_id, system)
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail=f"External ID for system '{system}' not found")
    return Response(status_code=204)

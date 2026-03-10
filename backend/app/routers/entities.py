from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_bulk_create_entities,
    db_create_entity,
    db_delete_entity,
    db_get_campaign,
    db_import_entities,
    db_list_entities,
)
from app.models.campaign import EntityCreate, EntityOut, ImportBody

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
    if campaign["owner_sid"] != user_sid:
        raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


@router.get("/{campaign_id}/entities", response_model=list[EntityOut])
async def list_entities(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_entities(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


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
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/entities/bulk", response_model=list[EntityOut], status_code=201)
async def bulk_create_entities(campaign_id: str, body: list[EntityCreate], user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        entities = [e.model_dump() for e in body]
        return await db_bulk_create_entities(campaign_id, entities)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/entities/import", response_model=list[EntityOut], status_code=201)
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

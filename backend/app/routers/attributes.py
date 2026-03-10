from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_create_attribute,
    db_delete_attribute,
    db_get_campaign,
    db_import_attributes,
    db_list_attributes,
    db_update_attribute,
)
from app.models.campaign import AttributeCreate, AttributeOut, AttributeUpdate, ImportBody

router = APIRouter(prefix="/api/campaigns", tags=["attributes"])


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


@router.get("/{campaign_id}/attributes", response_model=list[AttributeOut])
async def list_attributes(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_attributes(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/attributes", response_model=AttributeOut, status_code=201)
async def create_attribute(campaign_id: str, body: AttributeCreate, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_create_attribute(
            campaign_id=campaign_id,
            label=body.label,
            description=body.description,
            weight=body.weight,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{campaign_id}/attributes/{attribute_id}", response_model=AttributeOut)
async def update_attribute(campaign_id: str, attribute_id: str, body: AttributeUpdate,
                           user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    patch = body.model_dump(exclude_none=True)
    try:
        updated = await db_update_attribute(attribute_id, campaign_id, patch)
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return updated


@router.post("/{campaign_id}/attributes/import", response_model=list[AttributeOut], status_code=201)
async def import_attributes(campaign_id: str, body: ImportBody, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_owned_campaign(body.source_campaign_id, user["sub"])
    try:
        return await db_import_attributes(
            target_campaign_id=campaign_id,
            source_campaign_id=body.source_campaign_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{campaign_id}/attributes/{attribute_id}", status_code=204)
async def delete_attribute(campaign_id: str, attribute_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        deleted = await db_delete_attribute(attribute_id=attribute_id, campaign_id=campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return Response(status_code=204)

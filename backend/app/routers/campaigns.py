from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_create_campaign,
    db_delete_campaign,
    db_get_campaign,
    db_list_campaigns,
    db_update_campaign,
)
from app.models.campaign import CampaignCreate, CampaignOut, CampaignUpdate

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Campaign not found")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="Forbidden")


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(user=Depends(get_current_user)):
    try:
        return await db_list_campaigns(owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(body: CampaignCreate, user=Depends(get_current_user)):
    try:
        return await db_create_campaign(
            owner_sid=user["sub"],
            name=body.name,
            description=body.description,
            schedule=body.schedule,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: str, user=Depends(get_current_user)):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    if campaign["owner_sid"] != user["sub"]:
        raise _forbidden()
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: str, body: CampaignUpdate, user=Depends(get_current_user)):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    if campaign["owner_sid"] != user["sub"]:
        raise _forbidden()
    patch = body.model_dump(exclude_none=True)
    updated = await db_update_campaign(campaign_id, patch)
    return updated


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user=Depends(get_current_user)):
    try:
        deleted = await db_delete_campaign(campaign_id=campaign_id, owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise _not_found()
    return Response(status_code=204)

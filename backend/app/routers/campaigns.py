from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_clone_campaign,
    db_compare_entities,
    db_create_campaign,
    db_delete_campaign,
    db_get_campaign,
    db_get_campaign_stats,
    db_get_campaign_status_audit,
    db_is_team_member,
    db_list_campaigns,
    db_transition_campaign_status,
    db_update_campaign,
)
from app.models.campaign import (
    CampaignCreate,
    CampaignOut,
    CampaignStatsOut,
    CampaignStatusAuditOut,
    CampaignStatusUpdate,
    CampaignUpdate,
    CompareRequest,
    ComparisonOut,
)

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


async def _assert_campaign_access(campaign: dict, user_sid: str) -> None:
    """Raise 403 if user cannot access this campaign."""
    if campaign.get("team_id"):
        if not await db_is_team_member(campaign["team_id"], user_sid):
            raise _forbidden()
    elif campaign["owner_sid"] != user_sid:
        raise _forbidden()


@router.get("/stats", response_model=CampaignStatsOut)
async def get_campaign_stats(
    team_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    try:
        return await db_get_campaign_stats(owner_sid=user["sub"], team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    team_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    try:
        return await db_list_campaigns(owner_sid=user["sub"], team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(body: CampaignCreate, user=Depends(get_current_user)):
    if body.team_id:
        if not await db_is_team_member(body.team_id, user["sub"]):
            raise _forbidden()
    try:
        return await db_create_campaign(
            owner_sid=user["sub"],
            name=body.name,
            description=body.description,
            schedule=body.schedule,
            team_id=body.team_id,
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
    await _assert_campaign_access(campaign, user["sub"])
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: str, body: CampaignUpdate, user=Depends(get_current_user)
):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    await _assert_campaign_access(campaign, user["sub"])
    patch = body.model_dump(exclude_none=True)
    updated = await db_update_campaign(campaign_id, patch)
    return updated


@router.patch("/{campaign_id}/status", response_model=CampaignOut)
async def transition_campaign_status(
    campaign_id: str,
    body: CampaignStatusUpdate,
    user=Depends(get_current_user),
):
    """Transition a campaign's lifecycle status.

    Valid transitions:
      draft -> active
      active -> completed | archived
      completed -> archived
    """
    try:
        # Access check, state read, and write are all atomic inside
        # db_transition_campaign_status (FOR UPDATE lock eliminates TOCTOU).
        updated = await db_transition_campaign_status(
            campaign_id=campaign_id,
            new_status=body.status,
            user_sid=user["sub"],
        )
    except DatabaseNotConfigured:
        raise _no_db()
    return updated


@router.get("/{campaign_id}/status-history", response_model=list[CampaignStatusAuditOut])
async def get_campaign_status_history(
    campaign_id: str,
    user=Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Return the status audit trail for a campaign, newest first."""
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    await _assert_campaign_access(campaign, user["sub"])
    try:
        results = await db_get_campaign_status_audit(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    return results[offset : offset + limit]


@router.post("/{campaign_id}/clone", response_model=CampaignOut, status_code=201)
async def clone_campaign(campaign_id: str, user=Depends(get_current_user)):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    await _assert_campaign_access(campaign, user["sub"])
    try:
        return await db_clone_campaign(campaign_id, user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user=Depends(get_current_user)):
    try:
        deleted = await db_delete_campaign(
            campaign_id=campaign_id, owner_sid=user["sub"]
        )
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise _not_found()
    return Response(status_code=204)


@router.post("/{campaign_id}/compare", response_model=ComparisonOut)
async def compare_entities(
    campaign_id: str,
    body: CompareRequest,
    user=Depends(get_current_user),
):
    """Compare 2-5 entities side-by-side within a campaign.

    Returns a matrix with attributes as rows and entities as columns,
    including each entity's overall score and per-attribute validation results.
    """
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise _not_found()
    await _assert_campaign_access(campaign, user["sub"])
    try:
        return await db_compare_entities(
            campaign_id=campaign_id,
            entity_ids=body.entity_ids,
        )
    except DatabaseNotConfigured:
        raise _no_db()

"""Attribute template CRUD — save/load reusable attribute sets."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_apply_template_to_campaign,
    db_create_attribute_template,
    db_delete_attribute_template,
    db_get_attribute_template,
    db_get_campaign,
    db_is_team_member,
    db_list_attribute_templates,
    db_save_template_from_campaign,
)
from app.models.campaign import AttributeTemplateCreate, AttributeTemplateOut

router = APIRouter(prefix="/api/attribute-templates", tags=["templates"])


class SaveTemplateBody(BaseModel):
    name: str
    campaign_id: str
    team_id: str | None = None


class ApplyTemplateBody(BaseModel):
    campaign_id: str


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


async def _get_owned_campaign(campaign_id: str, user_sid: str) -> dict:
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


async def _assert_team_membership(team_id: str | None, user_sid: str) -> None:
    """Validate user is a member of the specified team. Raises 403 on failure."""
    if team_id:
        try:
            if not await db_is_team_member(team_id, user_sid):
                raise HTTPException(status_code=403, detail="Not a member of the specified team")
        except DatabaseNotConfigured:
            raise _no_db()


@router.get("", response_model=list[AttributeTemplateOut])
async def list_templates(user=Depends(get_current_user)):
    try:
        return await db_list_attribute_templates(owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("", response_model=AttributeTemplateOut, status_code=201)
async def create_template(body: AttributeTemplateCreate, user=Depends(get_current_user)):
    await _assert_team_membership(body.team_id, user["sub"])
    try:
        return await db_create_attribute_template(
            owner_sid=user["sub"],
            name=body.name,
            attributes=body.attributes,
            team_id=body.team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/save-from-campaign", response_model=AttributeTemplateOut, status_code=201)
async def save_template_from_campaign(body: SaveTemplateBody, user=Depends(get_current_user)):
    """Snapshot a campaign's attributes into a reusable template."""
    await _get_owned_campaign(body.campaign_id, user["sub"])
    await _assert_team_membership(body.team_id, user["sub"])
    try:
        return await db_save_template_from_campaign(
            campaign_id=body.campaign_id,
            name=body.name,
            owner_sid=user["sub"],
            team_id=body.team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{template_id}/apply", status_code=201)
async def apply_template_to_campaign(
    template_id: str, body: ApplyTemplateBody, user=Depends(get_current_user),
):
    """Apply a template's attributes to a campaign, skipping duplicates."""
    await _get_owned_campaign(body.campaign_id, user["sub"])
    try:
        template = await db_get_attribute_template(template_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    # Verify user can access this template (owner or team member)
    if template["owner_sid"] != user["sub"]:
        await _assert_team_membership(template.get("team_id"), user["sub"])
        if not template.get("team_id"):
            raise HTTPException(status_code=403, detail="Forbidden")
    try:
        return await db_apply_template_to_campaign(template_id, body.campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: str, user=Depends(get_current_user)):
    try:
        deleted = await db_delete_attribute_template(template_id, user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=204)

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_assign_attribute_to_campaign,
    db_bulk_create_attributes,
    db_bulk_delete_attributes,
    db_create_attribute,
    db_delete_attribute,
    db_get_attribute,
    db_get_campaign,
    db_import_attributes,
    db_import_attributes_from_library,
    db_is_team_member,
    db_list_attributes,
    db_list_campaign_attributes,
    db_recalculate_scores_from_matrix,
    db_reorder_campaign_attributes,
    db_unassign_attribute_from_campaign,
    db_update_attribute,
    db_update_campaign_attribute,
)
from app.models.campaign import (
    AttributeCreate,
    AttributeOut,
    AttributeUpdate,
    BulkAttributeResult,
    ImportAttributeResult,
    ImportBody,
)

logger = logging.getLogger(__name__)


class ImportLibraryBody(BaseModel):
    ids: list[str] = Field(min_length=1)


class BulkDeleteBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


class CampaignAttributeAssign(BaseModel):
    attribute_id: str
    weight_override: float | None = None
    display_order: int = 0


class CampaignAttributePatch(BaseModel):
    weight_override: float | None = None
    display_order: int | None = None


class CampaignAttributeReorder(BaseModel):
    ordering: list[dict] = Field(
        ..., description="List of {attribute_id: str, display_order: int}"
    )


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
    if campaign.get("team_id"):
        if not await db_is_team_member(campaign["team_id"], user_sid):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif campaign["owner_sid"] != user_sid:
        raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


@router.get("/{campaign_id}/attributes")
async def list_attributes(
    campaign_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    limit: int = Query(default=50, ge=0, le=10000),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort_by: str = Query(default="created_at", pattern="^(label|weight|created_at)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_attributes(
            campaign_id, limit=limit, offset=offset, search=search, category=category,
            sort_by=sort_by, order=order,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/attributes", response_model=AttributeOut, status_code=201)
async def create_attribute(campaign_id: str, body: AttributeCreate, user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_create_attribute(
            campaign_id=campaign_id,
            label=body.label,
            description=body.description,
            weight=body.weight,
            attribute_type=body.attribute_type.value,
            category=body.category,
            numeric_min=body.numeric_min,
            numeric_max=body.numeric_max,
            options=body.options,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{campaign_id}/attributes/{attribute_id}", response_model=AttributeOut)
async def get_attribute(campaign_id: str, attribute_id: str, user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        attr = await db_get_attribute(attribute_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not attr or attr.get("campaign_id") != campaign_id:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return attr


@router.post("/{campaign_id}/attributes/import-library", response_model=ImportAttributeResult, status_code=201)
async def import_attributes_from_library(campaign_id: str, body: ImportLibraryBody, user: dict[str, Any] = Depends(get_current_user)):
    campaign = await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_import_attributes_from_library(
            campaign_id, body.ids, owner_sid=user["sub"], team_id=campaign.get("team_id"),
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{campaign_id}/attributes/{attribute_id}", response_model=AttributeOut)
async def update_attribute(campaign_id: str, attribute_id: str, body: AttributeUpdate,
                           user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])

    # Prohibit attribute_type changes on existing attributes
    if body.attribute_type is not None:
        try:
            existing = await db_get_attribute(attribute_id)
        except DatabaseNotConfigured:
            raise _no_db()
        if not existing or existing.get("campaign_id") != campaign_id:
            raise HTTPException(status_code=404, detail="Attribute not found")
        if existing.get("attribute_type", "text") != body.attribute_type.value:
            raise HTTPException(
                status_code=400,
                detail="Changing attribute type is not allowed. Delete and recreate the attribute instead.",
            )

    patch = body.model_dump(exclude_none=True)
    # Convert enum to its string value for the DB layer
    if "attribute_type" in patch:
        patch["attribute_type"] = patch["attribute_type"].value
    try:
        updated = await db_update_attribute(attribute_id, campaign_id, patch)
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Attribute not found")
    # Recalculate all entity scores if weight changed
    if "weight" in patch:
        try:
            await db_recalculate_scores_from_matrix(campaign_id)
        except Exception:
            logger.exception("Batch score recalculation failed after attribute weight change")
    return updated


@router.post("/{campaign_id}/attributes/bulk", response_model=BulkAttributeResult, status_code=201)
async def bulk_create_attributes(campaign_id: str, body: list[AttributeCreate], user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    if not body:
        return {"inserted": [], "skipped": 0}
    # Deduplicate within the request itself (keep first occurrence)
    seen: set[str] = set()
    deduped: list[dict] = []
    for a in body:
        key = a.label.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(a.model_dump())
    skipped_in_request = len(body) - len(deduped)
    # Convert enum values to strings for the JSONB insert
    for attr_dict in deduped:
        if "attribute_type" in attr_dict and hasattr(attr_dict["attribute_type"], "value"):
            attr_dict["attribute_type"] = attr_dict["attribute_type"].value
    try:
        result = await db_bulk_create_attributes(campaign_id, deduped)
        result["skipped"] = result.get("skipped", 0) + skipped_in_request
        return result
    except DatabaseNotConfigured:
        raise _no_db()
    except Exception:
        raise HTTPException(status_code=422, detail="Bulk insert failed due to a data conflict")


@router.post("/{campaign_id}/attributes/import", response_model=ImportAttributeResult, status_code=201)
async def import_attributes(campaign_id: str, body: ImportBody, user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    await _get_owned_campaign(body.source_campaign_id, user["sub"])
    try:
        return await db_import_attributes(
            target_campaign_id=campaign_id,
            source_campaign_id=body.source_campaign_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{campaign_id}/attributes/bulk", status_code=200)
async def bulk_delete_attributes(campaign_id: str, body: BulkDeleteBody, user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    if not body.ids:
        return {"deleted": 0}
    try:
        deleted = await db_bulk_delete_attributes(campaign_id, body.ids)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"deleted": deleted}


@router.delete("/{campaign_id}/attributes/{attribute_id}", status_code=204)
async def delete_attribute(campaign_id: str, attribute_id: str, user: dict[str, Any] = Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        deleted = await db_delete_attribute(attribute_id=attribute_id, campaign_id=campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Attribute not found")
    return Response(status_code=204)


# ── Campaign-Attribute Assignment (weight override + display order) ───────────

@router.get("/{campaign_id}/attribute-assignments")
async def list_campaign_attribute_assignments(
    campaign_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """List all attribute assignments for a campaign with effective weights."""
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_campaign_attributes(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{campaign_id}/attribute-assignments", status_code=201)
async def assign_attribute_to_campaign(
    campaign_id: str,
    body: CampaignAttributeAssign,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Assign an attribute to a campaign with optional weight override."""
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_assign_attribute_to_campaign(
            campaign_id,
            body.attribute_id,
            weight_override=body.weight_override,
            display_order=body.display_order,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{campaign_id}/attribute-assignments/{attribute_id}")
async def update_campaign_attribute_assignment(
    campaign_id: str,
    attribute_id: str,
    body: CampaignAttributePatch,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update weight_override and/or display_order for a campaign-attribute assignment."""
    await _get_owned_campaign(campaign_id, user["sub"])
    kwargs: dict = {}
    if body.weight_override is not None:
        kwargs["weight_override"] = body.weight_override
    if body.display_order is not None:
        kwargs["display_order"] = body.display_order
    try:
        updated = await db_update_campaign_attribute(campaign_id, attribute_id, **kwargs)
    except DatabaseNotConfigured:
        raise _no_db()
    if not updated:
        raise HTTPException(status_code=404, detail="Assignment not found")
    # Recalculate all entity scores if weight changed
    if body.weight_override is not None:
        try:
            await db_recalculate_scores_from_matrix(campaign_id)
        except Exception:
            logger.exception("Batch score recalculation failed after weight override change")
    return updated


@router.delete("/{campaign_id}/attribute-assignments/{attribute_id}", status_code=204)
async def unassign_attribute_from_campaign(
    campaign_id: str,
    attribute_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Remove an attribute assignment from a campaign."""
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        removed = await db_unassign_attribute_from_campaign(campaign_id, attribute_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not removed:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return Response(status_code=204)


@router.put("/{campaign_id}/attribute-assignments/reorder")
async def reorder_campaign_attributes(
    campaign_id: str,
    body: CampaignAttributeReorder,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update display_order for multiple attribute assignments at once."""
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_reorder_campaign_attributes(campaign_id, body.ordering)
    except DatabaseNotConfigured:
        raise _no_db()

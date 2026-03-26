from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import logging

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_get_campaign,
    db_get_matrix_data,
    db_is_team_member,
    db_upsert_cell_value,
    db_delete_cell_value,
    db_bulk_upsert_cells,
    db_recalculate_scores_from_matrix,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["matrix"])


# ── Request / Response models ─────────────────────────────────────────────────


class CellUpsert(BaseModel):
    entity_id: str
    attribute_id: str
    value: Any = None
    attribute_type: str | None = None


class BulkCellUpsert(BaseModel):
    cells: list[CellUpsert]


class CellDelete(BaseModel):
    entity_id: str
    attribute_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


async def _get_owned_campaign(campaign_id: str, user_sid: str) -> dict[str, Any]:
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


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/{campaign_id}/matrix")
async def get_matrix(campaign_id: str, user=Depends(get_current_user)):
    """Return the full entity x attribute matrix for a campaign."""
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_get_matrix_data(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.put("/{campaign_id}/matrix/cells")
async def upsert_cell(
    campaign_id: str,
    body: CellUpsert,
    user=Depends(get_current_user),
):
    """Upsert a single cell value and recalculate the entity's score."""
    campaign = await _get_owned_campaign(campaign_id, user["sub"])
    team_id: str | None = campaign.get("team_id")
    try:
        result = await db_upsert_cell_value(
            campaign_id,
            body.entity_id,
            body.attribute_id,
            body.value,
            attribute_type=body.attribute_type,
            updated_by=user["sub"],
            team_id=team_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DatabaseNotConfigured:
        raise _no_db()
    try:
        await db_recalculate_scores_from_matrix(
            campaign_id, entity_id=body.entity_id, team_id=team_id,
        )
    except Exception:
        logger.exception("Score recalculation failed after cell upsert")
    return result


@router.put("/{campaign_id}/matrix/cells/bulk")
async def bulk_upsert_cells(
    campaign_id: str,
    body: BulkCellUpsert,
    user=Depends(get_current_user),
):
    """Bulk upsert cell values and recalculate affected entities' scores."""
    campaign = await _get_owned_campaign(campaign_id, user["sub"])
    team_id: str | None = campaign.get("team_id")
    if not body.cells:
        return []
    cells = [c.model_dump() for c in body.cells]
    try:
        result = await db_bulk_upsert_cells(
            campaign_id, cells, updated_by=user["sub"], team_id=team_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DatabaseNotConfigured:
        raise _no_db()
    # Recalculate scores for each affected entity
    affected_entity_ids = {c.entity_id for c in body.cells}
    for eid in affected_entity_ids:
        try:
            await db_recalculate_scores_from_matrix(
                campaign_id, entity_id=eid, team_id=team_id,
            )
        except Exception:
            logger.exception("Score recalculation failed for entity %s", eid)
    return result


@router.delete("/{campaign_id}/matrix/cells")
async def delete_cell(
    campaign_id: str,
    body: CellDelete,
    user=Depends(get_current_user),
):
    """Clear a cell value and recalculate the entity's score."""
    campaign = await _get_owned_campaign(campaign_id, user["sub"])
    team_id: str | None = campaign.get("team_id")
    try:
        deleted = await db_delete_cell_value(
            campaign_id, body.entity_id, body.attribute_id, team_id=team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Cell not found")
    try:
        await db_recalculate_scores_from_matrix(
            campaign_id, entity_id=body.entity_id, team_id=team_id,
        )
    except Exception:
        logger.exception("Score recalculation failed after cell delete")
    return {"deleted": True}

"""Attribute template CRUD — save/load reusable attribute sets."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_create_attribute_template,
    db_delete_attribute_template,
    db_list_attribute_templates,
)
from app.models.campaign import AttributeTemplateCreate, AttributeTemplateOut

router = APIRouter(prefix="/api/attribute-templates", tags=["templates"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


@router.get("", response_model=list[AttributeTemplateOut])
async def list_templates(user=Depends(get_current_user)):
    try:
        return await db_list_attribute_templates(owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("", response_model=AttributeTemplateOut, status_code=201)
async def create_template(body: AttributeTemplateCreate, user=Depends(get_current_user)):
    try:
        return await db_create_attribute_template(
            owner_sid=user["sub"],
            name=body.name,
            attributes=body.attributes,
            team_id=body.team_id,
        )
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

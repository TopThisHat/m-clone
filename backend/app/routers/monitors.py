from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_create_monitor,
    db_delete_monitor,
    db_list_monitors,
)
from app.models.monitor import MonitorCreate, MonitorOut

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


@router.get("", response_model=list[MonitorOut])
async def list_monitors(user=Depends(get_current_user)):
    try:
        return await db_list_monitors(owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("", response_model=MonitorOut, status_code=201)
async def create_monitor(body: MonitorCreate, user=Depends(get_current_user)):
    try:
        return await db_create_monitor(
            owner_sid=user["sub"],
            label=body.label,
            query=body.query,
            frequency=body.frequency,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{monitor_id}", status_code=204)
async def delete_monitor(monitor_id: str, user=Depends(get_current_user)):
    try:
        deleted = await db_delete_monitor(monitor_id=monitor_id, owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return Response(status_code=204)

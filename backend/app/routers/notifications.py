"""
Notifications router: list, mark-read, mark-all-read.
Polled by frontend every 30 seconds.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_list_notifications,
    db_mark_all_notifications_read,
    db_mark_notification_read,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(user: dict[str, Any] = Depends(get_current_user)):
    try:
        return await db_list_notifications(user["sub"])
    except DatabaseNotConfigured:
        return []  # no DB → empty list, polling should not error


@router.patch("/{notification_id}/read")
async def mark_read(notification_id: str, user: dict[str, Any] = Depends(get_current_user)):
    try:
        ok = await db_mark_notification_read(notification_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"ok": True}
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.post("/read-all")
async def mark_all_read(user: dict[str, Any] = Depends(get_current_user)):
    try:
        await db_mark_all_notifications_read(user["sub"])
        return {"ok": True}
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

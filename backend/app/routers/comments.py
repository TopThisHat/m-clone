"""
Comments router: CRUD + @mention notification trigger.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_create_comment,
    db_create_notification,
    db_delete_comment,
    db_get_comment,
    db_get_session,
    db_get_user,
    db_list_comments,
)

router = APIRouter(tags=["comments"])

MENTION_RE = re.compile(r"@([A-Za-z0-9_.\-]+)")


class CommentCreate(BaseModel):
    body: str
    parent_id: str | None = None


@router.get("/api/sessions/{session_id}/comments")
async def list_comments(session_id: str, user=Depends(get_current_user)):
    try:
        return await db_list_comments(session_id)
    except DatabaseNotConfigured:
        return []


@router.post("/api/sessions/{session_id}/comments", status_code=201)
async def create_comment(session_id: str, body: CommentCreate, user=Depends(get_current_user)):
    try:
        session = await db_get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Parse @mentions
        mentions = MENTION_RE.findall(body.body)
        mentions = list(set(mentions))  # deduplicate

        comment = await db_create_comment(
            session_id=session_id,
            author_sid=user["sub"],
            body=body.body,
            mentions=mentions,
            parent_id=body.parent_id,
        )

        # Create notifications for each mentioned SID that exists
        for mentioned_sid in mentions:
            if mentioned_sid == user["sub"]:
                continue  # don't notify self
            try:
                target = await db_get_user(mentioned_sid)
                if target:
                    await db_create_notification(
                        recipient_sid=mentioned_sid,
                        type_="mention",
                        payload={
                            "session_id": session_id,
                            "session_title": session.get("title", ""),
                            "comment_id": comment["id"],
                            "author_sid": user["sub"],
                            "author_name": user.get("display_name", user["sub"]),
                            "body_preview": body.body[:100],
                        },
                    )
            except Exception:
                pass  # never block comment creation due to notification failure

        return comment
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.delete("/api/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str, user=Depends(get_current_user)):
    try:
        comment = await db_get_comment(comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment["author_sid"] != user["sub"]:
            raise HTTPException(status_code=403, detail="Not your comment")
        await db_delete_comment(comment_id)
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

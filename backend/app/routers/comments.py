"""
Comments router: CRUD + @mention notification trigger + reply notifications.
"""
from __future__ import annotations

import re
from typing import Any

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
    db_get_session_mentionable_users,
    db_get_subscriber_sids,
    db_get_user,
    db_list_comments,
    db_resolve_suggestion,
    db_toggle_reaction,
    db_update_comment,
)

router = APIRouter(tags=["comments"])

MENTION_RE = re.compile(r"@([A-Za-z0-9_.\-]+)")

VALID_EMOJIS = {"👍", "❤️", "🔥", "💡", "✅", "❓"}


class HighlightAnchor(BaseModel):
    quote: str
    context_before: str = ""
    context_after: str = ""


class CommentCreate(BaseModel):
    body: str
    parent_id: str | None = None
    highlight_anchor: HighlightAnchor | None = None
    comment_type: str = "comment"
    proposed_text: str | None = None


class CommentUpdate(BaseModel):
    body: str


class ReactionBody(BaseModel):
    emoji: str


class SuggestionResolve(BaseModel):
    status: str  # 'accepted' | 'rejected'


@router.get("/api/sessions/{session_id}/mentionable-users")
async def list_mentionable_users(session_id: str, user=Depends(get_current_user)):
    """Users that can be @mentioned — members of teams this session is shared with."""
    try:
        return await db_get_session_mentionable_users(session_id)
    except DatabaseNotConfigured:
        return []


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
        mentions = list(set(MENTION_RE.findall(body.body)))

        anchor_dict = body.highlight_anchor.model_dump() if body.highlight_anchor else None

        comment = await db_create_comment(
            session_id=session_id,
            author_sid=user["sub"],
            body=body.body,
            mentions=mentions,
            parent_id=body.parent_id,
            highlight_anchor=anchor_dict,
            comment_type=body.comment_type,
            proposed_text=body.proposed_text,
        )

        author_name = user.get("display_name", user["sub"])
        session_title = session.get("title", "")

        # Notify @mentions
        for mentioned_sid in mentions:
            if mentioned_sid == user["sub"]:
                continue
            try:
                target = await db_get_user(mentioned_sid)
                if target:
                    await db_create_notification(
                        recipient_sid=mentioned_sid,
                        type_="mention",
                        payload={
                            "session_id": session_id,
                            "session_title": session_title,
                            "comment_id": comment["id"],
                            "author_sid": user["sub"],
                            "author_name": author_name,
                            "body_preview": body.body[:100],
                        },
                    )
            except Exception:
                pass

        # Notify parent comment author on reply
        if body.parent_id:
            try:
                parent = await db_get_comment(body.parent_id)
                if parent and parent["author_sid"] != user["sub"]:
                    await db_create_notification(
                        recipient_sid=parent["author_sid"],
                        type_="reply",
                        payload={
                            "session_id": session_id,
                            "session_title": session_title,
                            "comment_id": comment["id"],
                            "parent_id": body.parent_id,
                            "author_sid": user["sub"],
                            "author_name": author_name,
                            "body_preview": body.body[:100],
                        },
                    )
            except Exception:
                pass

        # Notify subscribers (except commenter)
        try:
            subscriber_sids = await db_get_subscriber_sids(session_id)
            for sub_sid in subscriber_sids:
                if sub_sid == user["sub"]:
                    continue
                if sub_sid in mentions:
                    continue  # already notified via mention
                await db_create_notification(
                    recipient_sid=sub_sid,
                    type_="new_comment",
                    payload={
                        "session_id": session_id,
                        "session_title": session_title,
                        "comment_id": comment["id"],
                        "author_sid": user["sub"],
                        "author_name": author_name,
                        "body_preview": body.body[:100],
                    },
                )
        except Exception:
            pass

        return comment
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.patch("/api/comments/{comment_id}")
async def update_comment(comment_id: str, body: CommentUpdate, user=Depends(get_current_user)):
    try:
        comment = await db_get_comment(comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment["author_sid"] != user["sub"]:
            raise HTTPException(status_code=403, detail="Not your comment")
        mentions = list(set(MENTION_RE.findall(body.body)))
        updated = await db_update_comment(comment_id, body.body, mentions)
        return updated
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


@router.post("/api/comments/{comment_id}/reactions")
async def toggle_reaction(comment_id: str, body: ReactionBody, user=Depends(get_current_user)):
    try:
        if body.emoji not in VALID_EMOJIS:
            raise HTTPException(status_code=400, detail=f"Invalid emoji. Must be one of: {', '.join(VALID_EMOJIS)}")
        comment = await db_get_comment(comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        reactions = await db_toggle_reaction(comment_id, user["sub"], body.emoji)
        return reactions
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.patch("/api/comments/{comment_id}/suggestion")
async def resolve_suggestion(comment_id: str, body: SuggestionResolve, user=Depends(get_current_user)):
    try:
        if body.status not in ("accepted", "rejected"):
            raise HTTPException(status_code=400, detail="status must be 'accepted' or 'rejected'")
        comment = await db_get_comment(comment_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        if comment.get("comment_type") != "suggestion":
            raise HTTPException(status_code=400, detail="Comment is not a suggestion")
        # Only session owner can resolve
        session = await db_get_session(comment["session_id"])
        if session is None or session.get("owner_sid") != user["sub"]:
            raise HTTPException(status_code=403, detail="Only the session owner can resolve suggestions")
        updated = await db_resolve_suggestion(comment_id, body.status)
        return updated
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

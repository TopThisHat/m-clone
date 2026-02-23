from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth import get_current_user, get_optional_user
from app.db import (
    DatabaseNotConfigured,
    db_create_session,
    db_delete_session,
    db_get_public_session,
    db_get_session,
    db_get_team,
    db_get_member_role,
    db_list_sessions,
    db_pin_session,
    db_share_session_to_team,
    db_unpin_session,
    db_unshare_session,
    db_update_session,
    db_record_activity,
)
from app.models.session import SessionCreate, SessionFull, SessionSummary, SessionUpdate

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _no_db() -> HTTPException:
    return HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(user=Depends(get_optional_user)):
    try:
        owner_sid = user["sub"] if user else None
        return await db_list_sessions(owner_sid=owner_sid)
    except DatabaseNotConfigured:
        return []


@router.get("/{session_id}", response_model=SessionFull)
async def get_session(session_id: str, user=Depends(get_optional_user)):
    try:
        row = await db_get_session(session_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    # Allow access if: public, no owner, or owner matches
    if row.get("visibility") == "private":
        if not user or row.get("owner_sid") != user.get("sub"):
            raise HTTPException(status_code=403, detail="Access denied")
    return row


@router.post("", response_model=SessionFull, status_code=201)
async def create_session(body: SessionCreate, user=Depends(get_optional_user)):
    try:
        data = body.model_dump()
        if user:
            data["owner_sid"] = user["sub"]
        return await db_create_session(data)
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{session_id}", response_model=SessionFull)
async def update_session(session_id: str, body: SessionUpdate, user=Depends(get_optional_user)):
    try:
        row = await db_update_session(session_id, body.model_dump(exclude_none=True))
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, user=Depends(get_optional_user)):
    try:
        deleted = await db_delete_session(session_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)


# ── Share endpoints ───────────────────────────────────────────────────────────

@router.post("/{session_id}/share")
async def share_session(session_id: str, request: Request):
    """Make a session publicly accessible via a share link."""
    try:
        row = await db_update_session(session_id, {"is_public": True})
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"share_url": f"/share/{session_id}"}


@router.delete("/{session_id}/share", status_code=204)
async def unshare_session(session_id: str):
    """Revoke public access to a session."""
    try:
        row = await db_update_session(session_id, {"is_public": False})
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)


# ── Team sharing ──────────────────────────────────────────────────────────────

class TeamShareBody(BaseModel):
    team_id: str


@router.post("/{session_id}/teams", status_code=201)
async def share_to_team(session_id: str, body: TeamShareBody, user=Depends(get_current_user)):
    try:
        session = await db_get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        # Look up team by id
        from app.db import db_get_team_by_id
        team = await db_get_team_by_id(body.team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        role = await db_get_member_role(body.team_id, user["sub"])
        if role not in ("owner", "admin", "member"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        result = await db_share_session_to_team(session_id, body.team_id)
        # Make session visible to team
        await db_update_session(session_id, {"visibility": "team"})
        try:
            await db_record_activity(body.team_id, user["sub"], "shared_session", {
                "session_id": session_id,
                "session_title": session.get("title", ""),
            })
        except Exception:
            pass
        return result
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{session_id}/teams/{team_id}", status_code=204)
async def unshare_from_team(session_id: str, team_id: str, user=Depends(get_current_user)):
    try:
        session = await db_get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.get("owner_sid") != user["sub"]:
            role = await db_get_member_role(team_id, user["sub"])
            if role not in ("owner", "admin"):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
        await db_unshare_session(session_id, team_id)
    except DatabaseNotConfigured:
        raise _no_db()


# ── Pin endpoints ─────────────────────────────────────────────────────────────

class PinBody(BaseModel):
    team_id: str


@router.post("/{session_id}/pin", status_code=201)
async def pin_session(session_id: str, body: PinBody, user=Depends(get_current_user)):
    try:
        result = await db_pin_session(user["sub"], session_id, body.team_id)
        try:
            await db_record_activity(body.team_id, user["sub"], "pinned", {
                "session_id": session_id,
            })
        except Exception:
            pass
        return result
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{session_id}/pin", status_code=204)
async def unpin_session(session_id: str, team_id: str, user=Depends(get_current_user)):
    try:
        await db_unpin_session(user["sub"], session_id, team_id)
    except DatabaseNotConfigured:
        raise _no_db()


# ── Public share read endpoint ────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/share", tags=["share"])


@router_public.get("/{session_id}", response_model=SessionFull)
async def get_public_session(session_id: str):
    """Retrieve a publicly shared session (read-only)."""
    try:
        row = await db_get_public_session(session_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found or not public")
    return row

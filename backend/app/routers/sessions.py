from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.export import markdown_to_docx

from app.auth import get_current_user, get_optional_user
from app.db import (
    DatabaseNotConfigured,
    db_create_notification,
    db_create_session,
    db_delete_session,
    db_fork_session,
    db_get_active_viewers,
    db_get_public_session,
    db_get_session,
    db_get_session_diff,
    db_get_session_teams,
    db_get_team,
    db_get_team_by_id,
    db_get_member_role,
    db_heartbeat_presence,
    db_is_subscribed,
    db_list_sessions,
    db_list_team_member_sids,
    db_list_user_teams,
    db_pin_session,
    db_share_session_to_team,
    db_subscribe,
    db_unpin_session,
    db_unshare_session,
    db_unsubscribe,
    db_update_session,
    db_record_activity,
)
from app.models.session import SessionCreate, SessionFull, SessionSummary, SessionUpdate

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _no_db() -> HTTPException:
    return HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(q: str | None = Query(None), user=Depends(get_optional_user)):
    try:
        owner_sid = user["sub"] if user else None
        return await db_list_sessions(owner_sid=owner_sid, search=q if q else None)
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
    visibility = row.get("visibility", "private")
    if visibility == "private":
        if not user or row.get("owner_sid") != user.get("sub"):
            raise HTTPException(status_code=403, detail="Access denied")
    elif visibility == "team":
        if not user:
            raise HTTPException(status_code=403, detail="Access denied")
        session_team_ids = set(await db_get_session_teams(session_id))
        user_team_ids = {t["id"] for t in await db_list_user_teams(user["sub"])}
        if not session_team_ids & user_team_ids:
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
        team = await db_get_team_by_id(body.team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        role = await db_get_member_role(body.team_id, user["sub"])
        if role not in ("owner", "admin", "member"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        result = await db_share_session_to_team(session_id, body.team_id)
        await db_update_session(session_id, {"visibility": "team"})
        try:
            await db_record_activity(body.team_id, user["sub"], "shared_session", {
                "session_id": session_id,
                "session_title": session.get("title", ""),
            })
        except Exception:
            pass
        # Notify all team members except sharer
        try:
            sharer_name = user.get("display_name", user["sub"])
            member_sids = await db_list_team_member_sids(body.team_id)
            for member_sid in member_sids:
                if member_sid == user["sub"]:
                    continue
                await db_create_notification(
                    recipient_sid=member_sid,
                    type_="shared_session",
                    payload={
                        "session_id": session_id,
                        "session_title": session.get("title", ""),
                        "team_name": team.get("display_name", ""),
                        "shared_by_name": sharer_name,
                    },
                )
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


# ── Fork ──────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/fork", status_code=201)
async def fork_session(session_id: str, user=Depends(get_current_user)):
    """Fork a session into a new private session owned by the current user."""
    try:
        row = await db_get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        visibility = row.get("visibility", "private")
        # Must be owner, public, or a team member
        if visibility == "private" and row.get("owner_sid") != user["sub"]:
            raise HTTPException(status_code=403, detail="Access denied")
        if visibility == "team":
            session_team_ids = set(await db_get_session_teams(session_id))
            user_team_ids = {t["id"] for t in await db_list_user_teams(user["sub"])}
            if not session_team_ids & user_team_ids and row.get("owner_sid") != user["sub"]:
                raise HTTPException(status_code=403, detail="Access denied")
        new_session = await db_fork_session(session_id, user["sub"])
        return {"id": new_session["id"], "title": new_session["title"]}
    except DatabaseNotConfigured:
        raise _no_db()


# ── Subscribe ─────────────────────────────────────────────────────────────────

@router.post("/{session_id}/subscribe", status_code=201)
async def subscribe_session(session_id: str, user=Depends(get_current_user)):
    try:
        await db_subscribe(session_id, user["sub"])
        return Response(status_code=201)
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{session_id}/subscribe", status_code=204)
async def unsubscribe_session(session_id: str, user=Depends(get_current_user)):
    try:
        await db_unsubscribe(session_id, user["sub"])
        return Response(status_code=204)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{session_id}/subscribe")
async def get_subscription(session_id: str, user=Depends(get_current_user)):
    try:
        subscribed = await db_is_subscribed(session_id, user["sub"])
        return {"subscribed": subscribed}
    except DatabaseNotConfigured:
        raise _no_db()


# ── Presence ──────────────────────────────────────────────────────────────────

@router.post("/{session_id}/presence", status_code=204)
async def heartbeat_presence(session_id: str, user=Depends(get_current_user)):
    try:
        await db_heartbeat_presence(session_id, user["sub"])
        return Response(status_code=204)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{session_id}/presence")
async def get_presence(session_id: str, user=Depends(get_current_user)):
    try:
        viewers = await db_get_active_viewers(session_id, window_seconds=30)
        return viewers
    except DatabaseNotConfigured:
        raise _no_db()


# ── Diff ──────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/diff")
async def get_session_diff(session_id: str, user=Depends(get_optional_user)):
    try:
        diff = await db_get_session_diff(session_id)
        if diff is None:
            raise HTTPException(status_code=404, detail="No previous version found")
        return diff
    except DatabaseNotConfigured:
        raise _no_db()


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/export")
async def export_session(
    session_id: str,
    format: str = Query(default="md"),
    user=Depends(get_current_user),
):
    try:
        row = await db_get_session(session_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.get("owner_sid") != user["sub"]:
        raise HTTPException(status_code=403, detail="Access denied")

    report = row.get("report_markdown", "")
    title = row.get("title", "Research Report")

    if format == "docx":
        docx_bytes = markdown_to_docx(title, report)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{title}.docx"'},
        )

    # Default: markdown
    return Response(
        content=report,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{title}.md"'},
    )


# ── Public share read endpoint ────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/share", tags=["share"])


@router_public.get("/{session_id}", response_model=SessionFull)
async def get_public_session(session_id: str, user=Depends(get_optional_user)):
    """Retrieve a publicly shared session (read-only)."""
    try:
        # Case 1: publicly shared — no auth required
        row = await db_get_public_session(session_id)
        if row:
            return row

        # Case 2: team-shared — requires auth + team membership
        row = await db_get_session(session_id)
        if row and row.get("visibility") == "team":
            if not user:
                raise HTTPException(status_code=401, detail="Authentication required to view this team-shared report")
            session_team_ids = set(await db_get_session_teams(session_id))
            user_team_ids = {t["id"] for t in await db_list_user_teams(user["sub"])}
            if session_team_ids & user_team_ids:
                return row
            raise HTTPException(status_code=403, detail="You do not have access to this team-shared report")
    except DatabaseNotConfigured:
        raise _no_db()

    raise HTTPException(status_code=404, detail="Session not found or not accessible")

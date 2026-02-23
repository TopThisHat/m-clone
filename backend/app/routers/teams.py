"""
Teams router: team CRUD + membership management.
Role hierarchy: owner > admin > member > viewer
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_add_member,
    db_create_team,
    db_delete_team,
    db_get_team,
    db_get_user,
    db_get_member_role,
    db_list_team_members,
    db_list_user_teams,
    db_remove_member,
    db_update_member_role,
    db_update_team,
    db_record_activity,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])

ROLE_ORDER = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def _no_db():
    return HTTPException(status_code=503, detail="Teams require a database connection. Please configure DATABASE_URL.")


def _can(role: str | None, min_role: str) -> bool:
    return ROLE_ORDER.get(role or "", -1) >= ROLE_ORDER[min_role]


async def _require_role(slug: str, sid: str, min_role: str) -> dict:
    team = await db_get_team(slug)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    role = await db_get_member_role(team["id"], sid)
    if not _can(role, min_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return team


# ── Models ────────────────────────────────────────────────────────────────────

class TeamCreate(BaseModel):
    slug: str
    display_name: str
    description: str = ""


class TeamUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None


class MemberInvite(BaseModel):
    sid: str
    role: str = "member"


class RoleUpdate(BaseModel):
    role: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_team(body: TeamCreate, user=Depends(get_current_user)):
    try:
        team = await db_create_team(body.slug, body.display_name, body.description, user["sub"])
        # Record activity (team just created, no team_id needed for the join activity)
        return team
    except DatabaseNotConfigured:
        raise _no_db()
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Team slug already taken")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("")
async def list_teams(user=Depends(get_current_user)):
    try:
        return await db_list_user_teams(user["sub"])
    except DatabaseNotConfigured:
        return []  # no DB → treat as empty list, don't error


@router.get("/{slug}")
async def get_team(slug: str, user=Depends(get_current_user)):
    try:
        team = await db_get_team(slug)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        role = await db_get_member_role(team["id"], user["sub"])
        if role is None:
            raise HTTPException(status_code=403, detail="Not a team member")
        members = await db_list_team_members(team["id"])
        return {**team, "members": members, "your_role": role}
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{slug}")
async def update_team(slug: str, body: TeamUpdate, user=Depends(get_current_user)):
    try:
        team = await _require_role(slug, user["sub"], "admin")
        patch = body.model_dump(exclude_none=True)
        updated = await db_update_team(slug, patch)
        return updated
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{slug}", status_code=204)
async def delete_team(slug: str, user=Depends(get_current_user)):
    try:
        await _require_role(slug, user["sub"], "owner")
        await db_delete_team(slug)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/{slug}/members", status_code=201)
async def invite_member(slug: str, body: MemberInvite, user=Depends(get_current_user)):
    try:
        team = await _require_role(slug, user["sub"], "admin")
        # SID must exist in users table
        target = await db_get_user(body.sid)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found — they must log in at least once")
        # Protect owner role assignment
        if body.role == "owner":
            raise HTTPException(status_code=400, detail="Cannot assign owner role via invite")
        await db_add_member(team["id"], body.sid, body.role)
        try:
            await db_record_activity(team["id"], user["sub"], "joined", {
                "invited_sid": body.sid,
                "role": body.role,
            })
        except Exception:
            pass
        return {"team_id": team["id"], "sid": body.sid, "role": body.role}
    except DatabaseNotConfigured:
        raise _no_db()


@router.patch("/{slug}/members/{sid}")
async def update_member_role(slug: str, sid: str, body: RoleUpdate, user=Depends(get_current_user)):
    try:
        team = await _require_role(slug, user["sub"], "admin")
        # Protect owner role
        if body.role == "owner":
            raise HTTPException(status_code=400, detail="Cannot promote to owner via this endpoint")
        current_role = await db_get_member_role(team["id"], sid)
        if current_role == "owner":
            raise HTTPException(status_code=400, detail="Cannot change owner role")
        ok = await db_update_member_role(team["id"], sid, body.role)
        if not ok:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"sid": sid, "role": body.role}
    except DatabaseNotConfigured:
        raise _no_db()


@router.delete("/{slug}/members/{sid}", status_code=204)
async def remove_member(slug: str, sid: str, user=Depends(get_current_user)):
    try:
        team = await db_get_team(slug)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        caller_role = await db_get_member_role(team["id"], user["sub"])
        # Can remove self (leave) or admin+ can remove others
        if sid != user["sub"] and not _can(caller_role, "admin"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        target_role = await db_get_member_role(team["id"], sid)
        if target_role == "owner":
            raise HTTPException(status_code=400, detail="Cannot remove the team owner")
        await db_remove_member(team["id"], sid)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{slug}/activity")
async def get_team_activity(slug: str, limit: int = 50, offset: int = 0, user=Depends(get_current_user)):
    try:
        team = await db_get_team(slug)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        role = await db_get_member_role(team["id"], user["sub"])
        if role is None:
            raise HTTPException(status_code=403, detail="Not a team member")
        from app.db import db_list_team_activity
        return await db_list_team_activity(team["id"], limit=limit, offset=offset)
    except DatabaseNotConfigured:
        return []


@router.get("/{slug}/sessions")
async def get_team_sessions(slug: str, limit: int = 50, offset: int = 0, user=Depends(get_current_user)):
    try:
        team = await db_get_team(slug)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        role = await db_get_member_role(team["id"], user["sub"])
        if role is None:
            raise HTTPException(status_code=403, detail="Not a team member")
        from app.db import db_get_team_sessions
        return await db_get_team_sessions(team["id"], limit=limit, offset=offset)
    except DatabaseNotConfigured:
        return []

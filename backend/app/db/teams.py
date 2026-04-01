from __future__ import annotations

import json
from typing import Any

import asyncpg

from ._pool import _acquire


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("message_history", "trace_steps", "mentions", "payload", "facts"):
        if field in d and isinstance(d[field], str):
            d[field] = json.loads(d[field])
    for field in ("id", "session_id", "team_id", "parent_id", "comment_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    if "updated_at" in d and d["updated_at"] is not None:
        d["updated_at"] = d["updated_at"].isoformat()
    if "joined_at" in d and d["joined_at"] is not None:
        d["joined_at"] = d["joined_at"].isoformat()
    if "shared_at" in d and d["shared_at"] is not None:
        d["shared_at"] = d["shared_at"].isoformat()
    if "pinned_at" in d and d["pinned_at"] is not None:
        d["pinned_at"] = d["pinned_at"].isoformat()
    if "last_login" in d and d["last_login"] is not None:
        d["last_login"] = d["last_login"].isoformat()
    return d


async def db_create_team(slug: str, display_name: str, description: str, created_by: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.teams (slug, display_name, description, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            slug, display_name, description, created_by,
        )
        team = _row_to_dict(row)
        # Creator becomes owner
        await conn.execute(
            "INSERT INTO playbook.team_members (team_id, sid, role) VALUES ($1, $2, 'owner')",
            row["id"], created_by,
        )
    return team


async def db_get_team(slug: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.teams WHERE slug = $1", slug)
    return _row_to_dict(row) if row else None


async def db_get_team_by_id(team_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM playbook.teams WHERE id = $1::uuid", team_id)
    return _row_to_dict(row) if row else None


async def db_list_user_teams(sid: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.*, tm.role, tm.joined_at
            FROM playbook.teams t
            JOIN playbook.team_members tm ON t.id = tm.team_id
            WHERE tm.sid = $1
            ORDER BY t.display_name
            """,
            sid,
        )
    return [_row_to_dict(r) for r in rows]


async def db_update_team(slug: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"display_name", "description"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_team(slug)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [slug]
    sql = f"UPDATE playbook.teams SET {', '.join(set_parts)} WHERE slug = ${len(values)} RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else None


async def db_delete_team(slug: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM playbook.teams WHERE slug = $1", slug)
    return result.endswith("1")


# ── Team Members ───────────────────────────────────────────────────────────────

async def db_list_team_members(team_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.sid, u.display_name, u.email, u.avatar_url,
                   tm.role, tm.joined_at
            FROM playbook.team_members tm
            JOIN playbook.users u ON tm.sid = u.sid
            WHERE tm.team_id = $1::uuid
            ORDER BY tm.role, u.display_name
            """,
            team_id,
        )
    return [_row_to_dict(r) for r in rows]


async def db_get_member_role(team_id: str, sid: str) -> str | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM playbook.team_members WHERE team_id = $1::uuid AND sid = $2",
            team_id, sid,
        )
    return row["role"] if row else None


async def db_add_member(team_id: str, sid: str, role: str = "member") -> dict[str, Any]:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.team_members (team_id, sid, role)
            VALUES ($1::uuid, $2, $3)
            ON CONFLICT (team_id, sid) DO UPDATE SET role = EXCLUDED.role
            """,
            team_id, sid, role,
        )
    return {"team_id": team_id, "sid": sid, "role": role}


async def db_update_member_role(team_id: str, sid: str, role: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "UPDATE playbook.team_members SET role = $1 WHERE team_id = $2::uuid AND sid = $3",
            role, team_id, sid,
        )
    return result.endswith("1")


async def db_remove_member(team_id: str, sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.team_members WHERE team_id = $1::uuid AND sid = $2",
            team_id, sid,
        )
    return result.endswith("1")


# ── Session ↔ Team sharing ─────────────────────────────────────────────────────

async def db_share_session_to_team(session_id: str, team_id: str) -> dict[str, Any]:
    async with _acquire() as conn:
        await conn.fetchrow(
            """
            INSERT INTO playbook.session_teams (session_id, team_id)
            VALUES ($1::uuid, $2::uuid)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            session_id, team_id,
        )
    return {"session_id": session_id, "team_id": team_id}


async def db_unshare_session(session_id: str, team_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.session_teams WHERE session_id = $1::uuid AND team_id = $2::uuid",
            session_id, team_id,
        )
    return result.endswith("1")


async def db_get_team_sessions(team_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.title, s.query, s.created_at, s.updated_at,
                   COALESCE(s.is_public, FALSE) AS is_public,
                   COALESCE(s.usage_tokens, 0) AS usage_tokens,
                   s.owner_sid, COALESCE(s.visibility, 'private') AS visibility,
                   st.shared_at
            FROM playbook.sessions s
            JOIN playbook.session_teams st ON s.id = st.session_id
            WHERE st.team_id = $1::uuid AND s.visibility != 'private'
            ORDER BY st.shared_at DESC
            LIMIT $2 OFFSET $3
            """,
            team_id, limit, offset,
        )
    return [_row_to_dict(r) for r in rows]


async def db_get_session_teams(session_id: str) -> list[str]:
    """Return list of team_ids this session is shared to."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT team_id::text FROM playbook.session_teams WHERE session_id = $1::uuid",
            session_id,
        )
    return [r["team_id"] for r in rows]


async def db_get_session_team_names(session_id: str) -> list[str]:
    """Return list of team display_names this session is shared to."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.display_name
            FROM playbook.session_teams st
            JOIN playbook.teams t ON t.id = st.team_id
            WHERE st.session_id = $1::uuid
            ORDER BY t.display_name
            """,
            session_id,
        )
    return [r["display_name"] for r in rows]


async def db_get_session_mentionable_users(session_id: str) -> list[dict[str, Any]]:
    """Return all unique members across teams this session is shared with."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (u.sid) u.sid, u.display_name, u.avatar_url
            FROM playbook.session_teams st
            JOIN playbook.team_members tm ON tm.team_id = st.team_id
            JOIN playbook.users u ON u.sid = tm.sid
            WHERE st.session_id = $1::uuid
            ORDER BY u.sid, u.display_name
            """,
            session_id,
        )
    return [_row_to_dict(r) for r in rows]


# ── Pinned sessions ────────────────────────────────────────────────────────────

async def db_pin_session(sid: str, session_id: str, team_id: str) -> dict[str, Any]:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.pinned_sessions (sid, session_id, team_id)
            VALUES ($1, $2::uuid, $3::uuid)
            ON CONFLICT DO NOTHING
            """,
            sid, session_id, team_id,
        )
    return {"sid": sid, "session_id": session_id, "team_id": team_id}


async def db_unpin_session(sid: str, session_id: str, team_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.pinned_sessions WHERE sid = $1 AND session_id = $2::uuid AND team_id = $3::uuid",
            sid, session_id, team_id,
        )
    return result.endswith("1")


# ── Team membership helpers ────────────────────────────────────────────────────

async def db_list_team_member_sids(team_id: str) -> list[str]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT sid FROM playbook.team_members WHERE team_id = $1::uuid",
            team_id,
        )
    return [r["sid"] for r in rows]


async def db_is_team_member(team_id: str, sid: str) -> bool:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM playbook.team_members WHERE team_id = $1::uuid AND sid = $2",
            team_id, sid,
        )
    return row is not None


# ── Team activity ──────────────────────────────────────────────────────────────

async def db_record_activity(team_id: str, actor_sid: str, action: str, payload: dict[str, Any]) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO playbook.team_activity (team_id, actor_sid, action, payload)
            VALUES ($1::uuid, $2, $3, $4::jsonb)
            """,
            team_id, actor_sid, action, json.dumps(payload),
        )


async def db_list_team_activity(team_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ta.*, u.display_name AS actor_name, u.avatar_url AS actor_avatar
            FROM playbook.team_activity ta
            LEFT JOIN playbook.users u ON ta.actor_sid = u.sid
            WHERE ta.team_id = $1::uuid
            ORDER BY ta.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            team_id, limit, offset,
        )
    result = []
    for r in rows:
        d = dict(r)
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        if "team_id" in d and d["team_id"] is not None:
            d["team_id"] = str(d["team_id"])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result

from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _program_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a programs row to a plain dict with serialised UUID/timestamps."""
    d = dict(row)
    for field in ("id", "team_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_create_program(
    name: str,
    description: str | None,
    owner_sid: str,
    team_id: str | None = None,
) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.programs (name, description, owner_sid, team_id)
            VALUES ($1, $2, $3, $4::uuid)
            RETURNING *
            """,
            name, description, owner_sid, team_id,
        )
    return _program_row_to_dict(row)


async def db_list_programs(
    owner_sid: str,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        if team_id:
            rows = await conn.fetch(
                """
                SELECT p.*
                FROM playbook.programs p
                JOIN playbook.team_members tm ON tm.team_id = p.team_id
                WHERE p.team_id = $1::uuid AND tm.sid = $2
                ORDER BY p.updated_at DESC
                """,
                team_id, owner_sid,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT p.*
                FROM playbook.programs p
                WHERE p.owner_sid = $1 AND p.team_id IS NULL
                ORDER BY p.updated_at DESC
                """,
                owner_sid,
            )
    return [_program_row_to_dict(r) for r in rows]


async def db_get_program(program_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*
            FROM playbook.programs p
            WHERE p.id = $1::uuid
            """,
            program_id,
        )
    return _program_row_to_dict(row) if row else None


async def db_update_program(
    program_id: str,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    allowed: dict[str, Any] = {}
    if name is not None:
        allowed["name"] = name
    if description is not None:
        allowed["description"] = description
    if not allowed:
        return await db_get_program(program_id)

    set_parts = [f"{k} = ${i + 1}" for i, k in enumerate(allowed)]
    values = list(allowed.values()) + [program_id]
    sql = (
        f"UPDATE playbook.programs SET {', '.join(set_parts)}, updated_at = NOW() "
        f"WHERE id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _program_row_to_dict(row) if row else None


async def db_delete_program(program_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.programs WHERE id = $1::uuid",
            program_id,
        )
    return result.endswith("1")


# ── Program-Campaign Assignment ───────────────────────────────────────────────


class CampaignAlreadyAssignedError(Exception):
    """Raised when a campaign is already assigned to another program."""

    def __init__(self, campaign_id: str, existing_program_id: str) -> None:
        self.campaign_id = campaign_id
        self.existing_program_id = existing_program_id
        super().__init__(
            f"Campaign {campaign_id} is already assigned to program {existing_program_id}"
        )


async def db_assign_campaign_to_program(
    program_id: str,
    campaign_id: str,
) -> dict[str, Any]:
    """Assign a campaign to a program.

    A campaign can belong to at most one program (enforced in application layer).
    Raises CampaignAlreadyAssignedError if the campaign is already in another program.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            # Lock existing rows for this campaign to prevent TOCTOU race
            existing = await conn.fetchval(
                """
                SELECT program_id FROM playbook.program_campaigns
                WHERE campaign_id = $1::uuid
                FOR UPDATE
                """,
                campaign_id,
            )
            if existing is not None and str(existing) != program_id:
                raise CampaignAlreadyAssignedError(campaign_id, str(existing))
            row = await conn.fetchrow(
                """
                INSERT INTO playbook.program_campaigns (program_id, campaign_id)
                VALUES ($1::uuid, $2::uuid)
                ON CONFLICT (program_id, campaign_id) DO NOTHING
                RETURNING *
                """,
                program_id, campaign_id,
            )
    if row is None:
        # Already assigned to this program — return existing
        return {"program_id": program_id, "campaign_id": campaign_id}
    d = dict(row)
    d["program_id"] = str(d["program_id"])
    d["campaign_id"] = str(d["campaign_id"])
    if d.get("assigned_at") is not None:
        d["assigned_at"] = d["assigned_at"].isoformat()
    return d


async def db_unassign_campaign_from_program(
    program_id: str,
    campaign_id: str,
) -> bool:
    """Remove a campaign from a program. Returns True if removed."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM playbook.program_campaigns
            WHERE program_id = $1::uuid AND campaign_id = $2::uuid
            """,
            program_id, campaign_id,
        )
    return result.endswith("1")


async def db_list_program_campaigns(program_id: str) -> list[dict[str, Any]]:
    """List all campaigns assigned to a program."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*, pc.assigned_at AS program_assigned_at
            FROM playbook.campaigns c
            JOIN playbook.program_campaigns pc ON pc.campaign_id = c.id
            WHERE pc.program_id = $1::uuid
            ORDER BY c.updated_at DESC
            """,
            program_id,
        )
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        for field in ("id", "team_id"):
            if field in d and d[field] is not None:
                d[field] = str(d[field])
        for ts in ("created_at", "updated_at", "last_run_at", "next_run_at",
                    "last_completed_at", "program_assigned_at"):
            if ts in d and d[ts] is not None:
                d[ts] = d[ts].isoformat()
        results.append(d)
    return results


async def db_get_campaign_program(campaign_id: str) -> dict[str, Any] | None:
    """Get the program a campaign belongs to, or None."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*
            FROM playbook.programs p
            JOIN playbook.program_campaigns pc ON pc.program_id = p.id
            WHERE pc.campaign_id = $1::uuid
            """,
            campaign_id,
        )
    return _program_row_to_dict(row) if row else None

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import get_current_user
from app.db import DatabaseNotConfigured, db_is_team_member
from app.db.programs import (
    db_create_program,
    db_delete_program,
    db_get_program,
    db_list_programs,
    db_update_program,
)
from app.models.program import ProgramCreate, ProgramOut, ProgramUpdate

router = APIRouter(prefix="/api/programs", tags=["programs"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Program not found")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="Forbidden")


async def _assert_program_access(program: dict, user_sid: str) -> None:
    """Raise 403 if user cannot access this program."""
    if program.get("team_id"):
        if not await db_is_team_member(program["team_id"], user_sid):
            raise _forbidden()
    elif program["owner_sid"] != user_sid:
        raise _forbidden()


@router.post("", response_model=ProgramOut, status_code=201)
async def create_program(body: ProgramCreate, user=Depends(get_current_user)):
    if body.team_id:
        if not await db_is_team_member(body.team_id, user["sub"]):
            raise _forbidden()
    try:
        return await db_create_program(
            name=body.name,
            description=body.description,
            owner_sid=user["sub"],
            team_id=body.team_id,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("", response_model=list[ProgramOut])
async def list_programs(
    team_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    try:
        return await db_list_programs(owner_sid=user["sub"], team_id=team_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/{program_id}", response_model=ProgramOut)
async def get_program(program_id: str, user=Depends(get_current_user)):
    try:
        program = await db_get_program(program_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not program:
        raise _not_found()
    await _assert_program_access(program, user["sub"])
    return program


@router.put("/{program_id}", response_model=ProgramOut)
async def update_program(program_id: str, body: ProgramUpdate, user=Depends(get_current_user)):
    try:
        program = await db_get_program(program_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not program:
        raise _not_found()
    await _assert_program_access(program, user["sub"])
    updated = await db_update_program(
        program_id,
        name=body.name,
        description=body.description,
    )
    return updated


@router.delete("/{program_id}", status_code=204)
async def delete_program(program_id: str, user=Depends(get_current_user)):
    try:
        program = await db_get_program(program_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not program:
        raise _not_found()
    await _assert_program_access(program, user["sub"])
    await db_delete_program(program_id)
    return Response(status_code=204)

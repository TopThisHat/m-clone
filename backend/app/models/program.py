from __future__ import annotations

from pydantic import BaseModel


# -- Program -------------------------------------------------------------------

class ProgramCreate(BaseModel):
    name: str
    description: str | None = None
    team_id: str | None = None


class ProgramUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProgramOut(BaseModel):
    id: str
    owner_sid: str
    team_id: str | None = None
    name: str
    description: str | None = None
    created_at: str
    updated_at: str

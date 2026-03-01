from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MonitorCreate(BaseModel):
    label: str
    query: str
    frequency: Literal["daily", "weekly"] = "daily"


class MonitorOut(BaseModel):
    id: str
    owner_sid: str
    label: str
    query: str
    frequency: str
    last_run_at: str | None = None
    next_run_at: str
    created_at: str

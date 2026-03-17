from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MonitorCreate(BaseModel):
    label: str
    query: str
    frequency: Literal["daily", "weekly"] = "daily"


class MonitorUpdate(BaseModel):
    label: str | None = None
    query: str | None = None
    frequency: Literal["daily", "weekly"] | None = None
    is_active: bool | None = None


class MonitorOut(BaseModel):
    id: str
    owner_sid: str
    label: str
    query: str
    frequency: str
    is_active: bool = True
    last_run_at: str | None = None
    next_run_at: str
    created_at: str


class MonitorRunOut(BaseModel):
    id: str
    title: str | None = None
    query: str | None = None
    created_at: str

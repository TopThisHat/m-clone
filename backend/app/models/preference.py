from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PreferencesOut(BaseModel):
    id: str
    user_sid: str
    campaign_id: str | None = None
    preferences: dict[str, Any]
    created_at: str
    updated_at: str


class PreferencesUpsert(BaseModel):
    campaign_id: str | None = None
    preferences: dict[str, Any]

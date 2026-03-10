from __future__ import annotations

from typing import Any
from pydantic import BaseModel


# ── Campaign ───────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    description: str | None = None
    schedule: str | None = None  # cron expression e.g. "0 9 * * 1"


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule: str | None = None
    is_active: bool | None = None


class CampaignOut(BaseModel):
    id: str
    owner_sid: str
    name: str
    description: str | None = None
    schedule: str | None = None
    is_active: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str
    updated_at: str


# ── Entity ─────────────────────────────────────────────────────────────────────

class EntityCreate(BaseModel):
    label: str
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] = {}


class EntityOut(BaseModel):
    id: str
    campaign_id: str
    label: str
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] = {}
    created_at: str


# ── Attribute ──────────────────────────────────────────────────────────────────

class AttributeCreate(BaseModel):
    label: str
    description: str | None = None
    weight: float = 1.0


class AttributeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    weight: float | None = None


class AttributeOut(BaseModel):
    id: str
    campaign_id: str
    label: str
    description: str | None = None
    weight: float = 1.0
    created_at: str


# ── Validation Job ─────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    entity_ids: list[str] | None = None
    attribute_ids: list[str] | None = None


class JobOut(BaseModel):
    id: str
    campaign_id: str
    triggered_by: str | None = None
    triggered_sid: str | None = None
    status: str
    entity_filter: list[str] | None = None
    attribute_filter: list[str] | None = None
    total_pairs: int = 0
    completed_pairs: int = 0
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


# ── Validation Result ──────────────────────────────────────────────────────────

class ResultOut(BaseModel):
    id: str
    job_id: str
    entity_id: str
    attribute_id: str
    present: bool
    confidence: float | None = None
    evidence: str | None = None
    report_md: str | None = None
    entity_label: str | None = None
    attribute_label: str | None = None
    created_at: str


# ── Entity Score ───────────────────────────────────────────────────────────────

class ScoreOut(BaseModel):
    entity_id: str
    campaign_id: str
    entity_label: str | None = None
    gwm_id: str | None = None
    total_score: float = 0
    attributes_present: int = 0
    attributes_checked: int = 0
    last_updated: str | None = None


# ── Knowledge Store ────────────────────────────────────────────────────────────

class KnowledgeOut(BaseModel):
    gwm_id: str
    attribute_label: str
    present: bool
    confidence: float | None = None
    evidence: str | None = None
    source_job_id: str | None = None
    source_campaign_id: str | None = None
    source_campaign_name: str | None = None
    entity_label: str | None = None
    last_updated: str | None = None


# ── Import ─────────────────────────────────────────────────────────────────────

class ImportBody(BaseModel):
    source_campaign_id: str

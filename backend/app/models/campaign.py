from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel


# ── Campaign Status ────────────────────────────────────────────────────────────

class CampaignStatus(str, Enum):
    """Lifecycle status for campaigns."""
    draft = "draft"
    active = "active"
    completed = "completed"
    archived = "archived"


# Valid status transitions: {from_status: {allowed_to_statuses}}
VALID_STATUS_TRANSITIONS: dict[CampaignStatus, set[CampaignStatus]] = {
    CampaignStatus.draft: {CampaignStatus.active},
    CampaignStatus.active: {CampaignStatus.completed, CampaignStatus.archived},
    CampaignStatus.completed: {CampaignStatus.archived},
    CampaignStatus.archived: set(),
}


class CampaignStatusUpdate(BaseModel):
    """Request body for PATCH /api/campaigns/{id}/status."""
    status: CampaignStatus


# ── Campaign ───────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    description: str | None = None
    schedule: str | None = None  # cron expression e.g. "0 9 * * 1"
    team_id: str | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule: str | None = None
    is_active: bool | None = None


class CampaignOut(BaseModel):
    id: str
    owner_sid: str
    team_id: str | None = None
    name: str
    description: str | None = None
    schedule: str | None = None
    is_active: bool = True
    status: CampaignStatus = CampaignStatus.draft
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_completed_at: str | None = None
    entity_count: int = 0
    attribute_count: int = 0
    result_count: int = 0
    created_at: str
    updated_at: str


class CampaignStatsOut(BaseModel):
    campaigns: int = 0
    entities: int = 0
    results: int = 0
    jobs_last_7_days: int = 0
    knowledge_entries: int = 0


class AttributeTemplateCreate(BaseModel):
    name: str
    team_id: str | None = None
    attributes: list[dict] = []


class AttributeTemplateOut(BaseModel):
    id: str
    owner_sid: str
    team_id: str | None = None
    name: str
    attributes: list[dict] = []
    created_at: str


# ── Entity ─────────────────────────────────────────────────────────────────────

class EntityCreate(BaseModel):
    label: str
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] = {}


class EntityUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] | None = None


class EntityOut(BaseModel):
    id: str
    campaign_id: str
    label: str
    description: str | None = None
    gwm_id: str | None = None
    metadata: dict[str, Any] = {}
    created_at: str


class MetadataUpdate(BaseModel):
    """Request body for PUT /metadata: set one or more key/value pairs."""
    metadata: dict[str, Any]


class ExternalIdUpdate(BaseModel):
    """Request body for PUT /external-ids: set an external ID for a system."""
    system: str
    external_id: str


class ExternalIdOut(BaseModel):
    entity_id: str
    system: str
    external_id: str
    created_at: str


# ── Attribute ──────────────────────────────────────────────────────────────────

class AttributeType(str, Enum):
    """Supported attribute value types."""
    text = "text"
    numeric = "numeric"
    boolean = "boolean"
    select = "select"


class AttributeCreate(BaseModel):
    label: str
    description: str | None = None
    weight: float = 1.0
    attribute_type: AttributeType = AttributeType.text
    category: str | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    options: list[str] | None = None


class AttributeUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    weight: float | None = None
    attribute_type: AttributeType | None = None  # validated at router level
    category: str | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    options: list[str] | None = None


class AttributeOut(BaseModel):
    id: str
    campaign_id: str
    label: str
    description: str | None = None
    weight: float = 1.0
    attribute_type: AttributeType = AttributeType.text
    category: str | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    options: list[str] | None = None
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


# ── Bulk operation results ──────────────────────────────────────────────────────

class BulkEntityResult(BaseModel):
    inserted: list[EntityOut]
    skipped: int


class BulkAttributeResult(BaseModel):
    inserted: list[AttributeOut]
    skipped: int


class ImportResult(BaseModel):
    inserted: list[EntityOut]
    skipped: int
    total_requested: int


class ImportAttributeResult(BaseModel):
    inserted: list[AttributeOut]
    skipped: int
    total_requested: int

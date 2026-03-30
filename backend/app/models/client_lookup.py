from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────


class AdjudicationMethod(str, Enum):
    """How the final match decision was reached."""

    LLM = "llm"
    FAST_PATH = "fast_path"    # single high-confidence candidate; LLM skipped
    RULE_BASED = "rule_based"  # LLM failed; deterministic fallback used


# ── Candidate ─────────────────────────────────────────────────────────────────


class CandidateResult(BaseModel):
    """A single candidate returned by the DB search layer.

    Used internally during resolution and surfaced in the response when the
    result is ambiguous (so callers can inspect ranked alternatives).
    """

    gwm_id: str
    name: str                         # display name for this candidate
    source: Literal["fuzzy_client", "high_priority_queue_client"]
    db_score: float                   # raw similarity() or word_similarity() score
    companies: str | None = None      # populated from fuzzy_client only
    label_excerpt: str | None = None  # first 200 chars of label; hpq only


# ── Search summary ────────────────────────────────────────────────────────────


class SearchSummary(BaseModel):
    """Hit counts from the two DB sources, for observability."""

    fuzzy_client_hits: int
    hpq_client_hits: int


# ── Lookup result (external response) ────────────────────────────────────────


class LookupResult(BaseModel):
    """Single-name client ID lookup response.

    This is the canonical external response type shared by the agent tool,
    the REST endpoint, and (when extended) the bulk endpoint.
    """

    match_found: bool
    gwm_id: str | None = None
    matched_name: str | None = None
    source: Literal["fuzzy_client", "high_priority_queue_client"] | None = None
    confidence: float                         # 0.0–1.0; always present (0.0 on no match)
    adjudication: AdjudicationMethod
    resolution_factors: list[str] = []
    conflict: bool = False                    # same person, different gwm_ids across sources
    ambiguous: bool = False                   # multiple plausible candidates, no clear winner
    candidates: list[CandidateResult] = []   # populated when ambiguous=True
    candidates_evaluated: int = 0
    warnings: list[str] = []                 # partial DB failures, LLM fallback, etc.
    search_summary: SearchSummary


# ── LLM decision (internal) ───────────────────────────────────────────────────


class LLMDecision(BaseModel):
    """Structured output parsed directly from the LLM JSON response.

    Intentionally minimal: it does not include warnings or search_summary,
    which are added by the Python orchestration layer when assembling
    the final LookupResult.
    """

    match_found: bool
    gwm_id: str | None = None
    matched_name: str | None = None
    source: Literal["fuzzy_client", "high_priority_queue_client"] | None = None
    confidence: float                  # LLM self-assessed 0.0–1.0
    conflict: bool = False
    conflict_gwm_ids: list[str] = []   # populated when conflict=True
    ambiguous: bool = False
    resolution_factors: list[str] = []
    candidates_considered: int = 0


# ── Request ───────────────────────────────────────────────────────────────────


class ClientLookupRequest(BaseModel):
    """Request body for POST /api/client-lookup and the agent tool."""

    name: str = Field(..., min_length=1, max_length=200)
    company: str | None = None   # strong disambiguating signal when provided
    context: str | None = None   # additional free-text context for the LLM

"""LLM-backed client ID resolver.

Orchestrates the full resolution pipeline:
  1. normalize_name()
  2. Parallel DB queries (fuzzy_client + high_priority_queue_client)
  3. Deduplication within each source
  4. Fast-path check (skip LLM for obvious single-candidate matches)
  5. LLM adjudication (gpt-4o-mini, json_object mode)
  6. Levenshtein rule-based fallback when LLM is unavailable
  7. Business-rule application on top of the LLM decision

Reference: openspec/changes/client-id-lookup-tool/llm-strategy-v2.md
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.db.client_lookup import normalize_name, search_fuzzy_client, search_queue_client
from app.models.client_lookup import (
    AdjudicationMethod,
    CandidateResult,
    LLMDecision,
    LookupResult,
    SearchSummary,
)
from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

# ── Thresholds and tunables (see llm-strategy-v2.md Sections 6, 8, 11) ───────

DISAMBIGUATION_GAP_THRESHOLD = 0.15
MIN_MATCH_CONFIDENCE = 0.70
FAST_PATH_FUZZY_THRESHOLD = 0.85
FAST_PATH_HPQ_THRESHOLD = 0.75
FALLBACK_CONFIDENCE_CAP = 0.60
NORMALIZATION_FACTOR_HPQ = 1.20
LLM_TIMEOUT = 15.0

# ── System prompt (llm-strategy-v2.md Section 9.1) ────────────────────────────

_SYSTEM_PROMPT = """\
You are a client identity specialist. Your job is to determine whether a given
person's name matches any candidate in a list drawn from two internal databases.

You will receive:
1. A query: the name to look up, with optional company and additional context
2. Candidates from two sources with different similarity scoring systems

UNDERSTANDING THE CANDIDATE SCORES:
- Candidates from "fuzzy_client" have a "db_score" from PostgreSQL similarity(),
  which measures full-string overlap. A score of 0.8 means strong name similarity.
- Candidates from "high_priority_queue_client" have a "db_score" from
  word_similarity(), which measures how well the query appears as a contiguous
  segment within the label text. Scores here are typically lower; treat 0.6
  from this source as roughly equivalent to 0.8 from fuzzy_client.

LABEL FIELD FORMAT:
The "label" field in high_priority_queue_client contains free-form bio text
where the person's name typically appears near the beginning, often followed by
a delimiter (pipe, dash, comma) and their title or firm. Example formats:
  "Smith, John A. | Managing Director | Goldman Sachs"
  "John Smith - Senior Advisor at Morgan Stanley"
Extract the person's name from the label for comparison purposes.
The full label text also gives you company and title context.

NAME VARIATION RULES:
Apply these equivalences when comparing names:
- Common nicknames: Bob=Robert, Bill=William, Dick/Rick=Richard, Jim=James,
  Jack=John, Chuck=Charles, Mike=Michael, Tom=Thomas, Dave=David, Joe=Joseph,
  Ted=Edward, Ben=Benjamin, Liz=Elizabeth, Maggie=Margaret, Patty=Patricia
- Initials: "R. Smith" may match "Robert Smith" or "Richard Smith"
- Suffixes: Jr., Sr., III do not disqualify a match
- Hyphenated names: "Smith-Jones" may appear as "Smith" or "Jones"
- Middle names: "John A. Smith" matches "John Smith"

COMPANY MATCHING:
If the query includes a company, use it as a strong disambiguating signal.
A name match with matching company should have significantly higher confidence
than a name match alone. A name match with contradicting company should have
significantly lower confidence.

CONFLICT RULE:
If the same person appears in both sources with DIFFERENT gwm_ids, set
"conflict": true, list both ids in "conflict_gwm_ids", and set "match_found"
to false. Do not pick between conflicting gwm_ids.

AMBIGUITY RULE:
If multiple candidates could plausibly match and you cannot confidently select
one with confidence >= 0.7, set "ambiguous": true and "match_found": false.
Report your confidence in the best candidate you found.

RESPONSE FORMAT:
Respond with ONLY valid JSON. No markdown fences, no explanation outside the JSON.
{
  "match_found": true or false,
  "gwm_id": "the gwm_id string or null",
  "matched_name": "the candidate's name as it appears in the source, or null",
  "source": "fuzzy_client" or "high_priority_queue_client" or null,
  "confidence": 0.0 to 1.0,
  "conflict": true or false,
  "conflict_gwm_ids": [],
  "ambiguous": true or false,
  "resolution_factors": ["factor 1", "factor 2"],
  "candidates_considered": integer
}"""


# ── User message builder (llm-strategy-v2.md Section 9.2) ────────────────────

def _build_user_prompt(
    name: str,
    company: str | None,
    context: str | None,
    fuzzy_candidates: list[CandidateResult],
    hpq_candidates: list[CandidateResult],
) -> str:
    """Format the query and candidate lists into the LLM user message."""
    lines = ["QUERY:"]
    lines.append(f"  Name: {name}")
    lines.append(f"  Company: {company or 'not provided'}")
    lines.append(f"  Additional context: {context or 'none'}")
    lines.append("")

    if fuzzy_candidates:
        lines.append("CANDIDATES FROM CLIENT DIRECTORY (galileo.fuzzy_client):")
        lines.append("  [Score type: similarity() — higher is stronger, max 1.0]")
        for c in fuzzy_candidates:
            companies_str = ", ".join(c.companies) if c.companies else "none listed"
            lines.append(
                f"  - gwm_id: {c.gwm_id} | name: {c.name} | "
                f"companies: {companies_str} | db_score: {c.db_score:.3f}"
            )
    else:
        lines.append("CANDIDATES FROM CLIENT DIRECTORY: none found above threshold")
    lines.append("")

    if hpq_candidates:
        lines.append("CANDIDATES FROM PRIORITY QUEUE (galileo.high_priority_queue_client):")
        lines.append("  [Score type: word_similarity() — lower scale; treat 0.6 as strong]")
        for c in hpq_candidates:
            excerpt = (c.label_excerpt or "")[:200]
            lines.append(
                f"  - gwm_id: {c.gwm_id} | label: {excerpt!r} | db_score: {c.db_score:.3f}"
            )
    else:
        lines.append("CANDIDATES FROM PRIORITY QUEUE: none found above threshold")

    return "\n".join(lines)


# ── Deduplication (llm-strategy-v2.md Section 10) ────────────────────────────

def _dedup_candidates(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
) -> tuple[list[CandidateResult], list[CandidateResult]]:
    """Deduplicate within each source by gwm_id, keeping highest db_score.

    Cross-source duplicates (same gwm_id in both tables) are intentionally
    preserved — showing the LLM that a gwm_id appears in both sources is
    meaningful corroborating evidence.
    """
    def _dedup_within(candidates: list[CandidateResult]) -> list[CandidateResult]:
        seen: dict[str, CandidateResult] = {}
        for c in sorted(candidates, key=lambda x: x.db_score, reverse=True):
            if c.gwm_id not in seen:
                seen[c.gwm_id] = c
        return list(seen.values())

    return _dedup_within(fuzzy), _dedup_within(hpq)


# ── Conflict detection ────────────────────────────────────────────────────────

def _detect_gwm_id_conflicts(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
) -> list[str]:
    """Return distinct gwm_ids when the same apparent person maps to different ids.

    A conflict is signalled when the top fuzzy candidate and top HPQ candidate
    both have gwm_ids but those ids differ.  The LLM prompt already instructs
    the model to detect conflicts; this Python check is an early-warning signal
    passed into the fast-path guard.
    """
    fuzzy_ids = {c.gwm_id for c in fuzzy}
    hpq_ids = {c.gwm_id for c in hpq}
    # Conflict: each source has at least one id, and the sets are disjoint
    if fuzzy_ids and hpq_ids and not fuzzy_ids.intersection(hpq_ids):
        return sorted(fuzzy_ids | hpq_ids)
    return []


# ── Fast path (llm-strategy-v2.md Section 6) ─────────────────────────────────

def _fast_path(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
    company: str | None,
    search_summary: SearchSummary,
) -> LookupResult | None:
    """Skip the LLM when conditions for an unambiguous match are met.

    Rules (all must hold):
      1. Exactly one unique gwm_id across both deduplicated lists.
      2. Score >= FAST_PATH_FUZZY_THRESHOLD (fuzzy) or >= FAST_PATH_HPQ_THRESHOLD (hpq).
      3. No company was provided in the query.
    """
    if company:
        return None  # always invoke LLM when company context is present

    all_candidates = fuzzy + hpq
    unique_ids = {c.gwm_id for c in all_candidates}
    if len(unique_ids) != 1:
        return None  # zero or multiple candidates — cannot fast-path

    candidate = all_candidates[0]
    # Use the highest-scoring candidate when the same gwm_id comes from both sources
    if len(all_candidates) > 1:
        candidate = max(all_candidates, key=lambda c: c.db_score)

    threshold = (
        FAST_PATH_FUZZY_THRESHOLD
        if candidate.source == "fuzzy_client"
        else FAST_PATH_HPQ_THRESHOLD
    )
    if candidate.db_score < threshold:
        return None

    return LookupResult(
        match_found=True,
        gwm_id=candidate.gwm_id,
        matched_name=candidate.name,
        source=candidate.source,
        confidence=min(candidate.db_score, 0.95),  # cap at 0.95; 1.0 reserved
        adjudication=AdjudicationMethod.FAST_PATH,
        resolution_factors=[
            f"Single high-confidence candidate (score: {candidate.db_score:.2f})",
            f"Source: {candidate.source}",
            "LLM adjudication skipped: unambiguous match",
        ],
        candidates_evaluated=1,
        search_summary=search_summary,
    )


# ── LLM call (llm-strategy-v2.md Section 9.3) ────────────────────────────────

async def _call_llm(
    name: str,
    company: str | None,
    context: str | None,
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
) -> LLMDecision | None:
    """Call gpt-4o-mini and parse the structured JSON response.

    Returns None on timeout, API error, or unparseable response so the
    caller can activate the Levenshtein fallback.
    """
    user_msg = _build_user_prompt(name, company, context, fuzzy, hpq)
    client = get_openai_client()

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=512,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            ),
            timeout=LLM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("client_resolver: LLM call timed out after %.1fs", LLM_TIMEOUT)
        return None
    except Exception as exc:
        logger.warning("client_resolver: LLM call failed: %s", exc)
        return None

    raw = response.choices[0].message.content or ""
    # Strip markdown fences as a defence-in-depth measure (json_object mode
    # should prevent this, but corrupted responses have been seen in practice)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`").strip()

    try:
        data: dict[str, Any] = json.loads(raw)
        return LLMDecision(**data)
    except Exception as exc:
        logger.warning(
            "client_resolver: could not parse LLM response (%s). Raw: %.200s",
            exc,
            raw,
        )
        return None


# ── LLM response → LookupResult (business rules) ─────────────────────────────

def _parse_llm_response(
    decision: LLMDecision,
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
    search_summary: SearchSummary,
    warnings: list[str],
) -> LookupResult:
    """Translate LLMDecision to LookupResult, applying business rules.

    Rules applied (llm-strategy-v2.md Sections 7, 8):
      - conflict=True  → cap confidence at 0.5, match_found=False
      - ambiguous=True → match_found=False
      - confidence < MIN_MATCH_CONFIDENCE → match_found=False
      - Gap check: multiple candidates, gap between best and next < 0.15 → ambiguous
    """
    all_candidates = fuzzy + hpq
    total_evaluated = len(all_candidates)

    # --- Conflict rule (Section 7) ---
    if decision.conflict:
        conflict_candidates = [
            c for c in all_candidates
            if c.gwm_id in decision.conflict_gwm_ids
        ]
        factors = list(decision.resolution_factors) + [
            "Manual verification required: conflicting gwm_ids in source tables"
        ]
        return LookupResult(
            match_found=False,
            confidence=min(decision.confidence, 0.5),
            adjudication=AdjudicationMethod.LLM,
            conflict=True,
            resolution_factors=factors,
            candidates=conflict_candidates,
            candidates_evaluated=total_evaluated,
            search_summary=search_summary,
            warnings=warnings,
        )

    # --- Ambiguity rule ---
    if decision.ambiguous:
        top_candidates = sorted(all_candidates, key=lambda c: c.db_score, reverse=True)[:5]
        return LookupResult(
            match_found=False,
            confidence=decision.confidence,
            adjudication=AdjudicationMethod.LLM,
            ambiguous=True,
            resolution_factors=list(decision.resolution_factors),
            candidates=top_candidates,
            candidates_evaluated=total_evaluated,
            search_summary=search_summary,
            warnings=warnings,
        )

    # --- Low confidence ---
    if decision.confidence < MIN_MATCH_CONFIDENCE:
        top_candidates = sorted(all_candidates, key=lambda c: c.db_score, reverse=True)[:5]
        return LookupResult(
            match_found=False,
            gwm_id=decision.gwm_id,
            matched_name=decision.matched_name,
            source=decision.source,
            confidence=decision.confidence,
            adjudication=AdjudicationMethod.LLM,
            resolution_factors=list(decision.resolution_factors) + [
                "Candidate found but confidence below threshold"
            ],
            candidates=top_candidates,
            candidates_evaluated=total_evaluated,
            search_summary=search_summary,
            warnings=warnings,
        )

    # --- Gap check (Section 8): ambiguous if no clear winner among candidates ---
    # The LLM reports a single confidence for the matched candidate.  If there
    # are other candidates whose db_scores are within the gap threshold of the
    # matched candidate's db_score, treat the result as ambiguous.
    if decision.match_found and decision.gwm_id:
        matched_candidate = next(
            (c for c in all_candidates if c.gwm_id == decision.gwm_id),
            None,
        )
        if matched_candidate:
            rivals = [
                c for c in all_candidates
                if c.gwm_id != decision.gwm_id
            ]
            if rivals:
                best_rival_score = max(c.db_score for c in rivals)
                matched_score = matched_candidate.db_score
                if (
                    matched_score - best_rival_score < DISAMBIGUATION_GAP_THRESHOLD
                    and decision.confidence < 0.85  # only gap-check when LLM isn't highly confident
                ):
                    top_candidates = sorted(
                        all_candidates, key=lambda c: c.db_score, reverse=True
                    )[:5]
                    return LookupResult(
                        match_found=False,
                        confidence=decision.confidence,
                        adjudication=AdjudicationMethod.LLM,
                        ambiguous=True,
                        resolution_factors=list(decision.resolution_factors) + [
                            f"Gap between top candidates ({matched_score:.2f} vs "
                            f"{best_rival_score:.2f}) below disambiguation threshold"
                        ],
                        candidates=top_candidates,
                        candidates_evaluated=total_evaluated,
                        search_summary=search_summary,
                        warnings=warnings,
                    )

    # --- Successful match ---
    return LookupResult(
        match_found=decision.match_found,
        gwm_id=decision.gwm_id,
        matched_name=decision.matched_name,
        source=decision.source,
        confidence=decision.confidence,
        adjudication=AdjudicationMethod.LLM,
        resolution_factors=list(decision.resolution_factors),
        candidates_evaluated=total_evaluated,
        search_summary=search_summary,
        warnings=warnings,
    )


# ── Levenshtein fallback (llm-strategy-v2.md Section 11) ─────────────────────

def _levenshtein_fallback(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
    search_summary: SearchSummary,
    warnings: list[str],
) -> LookupResult:
    """Deterministic rule-based fallback when the LLM is unavailable.

    HPQ scores are normalized upward by NORMALIZATION_FACTOR_HPQ to compensate
    for the lower scale of word_similarity() vs similarity().
    Confidence is capped at FALLBACK_CONFIDENCE_CAP regardless of raw score.
    """
    normalized: list[tuple[float, CandidateResult]] = []
    for c in fuzzy:
        normalized.append((c.db_score, c))
    for c in hpq:
        normalized.append((min(c.db_score * NORMALIZATION_FACTOR_HPQ, 1.0), c))

    if not normalized:
        return LookupResult(
            match_found=False,
            confidence=0.0,
            adjudication=AdjudicationMethod.RULE_BASED,
            candidates_evaluated=0,
            search_summary=search_summary,
            warnings=warnings + [
                "LLM adjudication failed; rule-based fallback found no candidates"
            ],
        )

    best_score, best_candidate = max(normalized, key=lambda x: x[0])
    effective_confidence = min(best_score, FALLBACK_CONFIDENCE_CAP)

    if effective_confidence < 0.40:
        return LookupResult(
            match_found=False,
            confidence=effective_confidence,
            adjudication=AdjudicationMethod.RULE_BASED,
            candidates_evaluated=len(normalized),
            search_summary=search_summary,
            warnings=warnings + [
                "LLM adjudication failed; best rule-based candidate below threshold"
            ],
        )

    return LookupResult(
        match_found=True,
        gwm_id=best_candidate.gwm_id,
        matched_name=best_candidate.name,
        source=best_candidate.source,
        confidence=effective_confidence,
        adjudication=AdjudicationMethod.RULE_BASED,
        resolution_factors=[
            f"LLM unavailable; rule-based selection by db_score ({best_score:.3f})",
            f"Source: {best_candidate.source}",
        ],
        candidates_evaluated=len(normalized),
        search_summary=search_summary,
        warnings=warnings + [
            "LLM adjudication failed; result is rule-based and may be less accurate"
        ],
    )


# ── Main entry point (llm-strategy-v2.md Section 12) ─────────────────────────

async def resolve_client(
    name: str,
    company: str | None = None,
    context: str | None = None,
) -> LookupResult:
    """Resolve a person's name to a GWM client ID.

    Full pipeline:
      1. normalize_name()
      2. asyncio.gather() both DB queries with independent exception handling
      3. Handle zero candidates
      4. Dedup within each source
      5. Fast-path check
      6. LLM call with Levenshtein fallback
      7. Apply business rules
      8. Return LookupResult

    This function never raises — all errors are caught and surfaced via
    LookupResult.warnings or a no-match response.
    """
    warnings: list[str] = []

    # 1. Normalize
    normalized = normalize_name(name)
    if not normalized:
        return LookupResult(
            match_found=False,
            confidence=0.0,
            adjudication=AdjudicationMethod.RULE_BASED,
            candidates_evaluated=0,
            search_summary=SearchSummary(fuzzy_client_hits=0, hpq_client_hits=0),
            warnings=["Input name is empty after normalization"],
        )

    # 2. Parallel DB queries with independent error handling
    fuzzy_result, hpq_result = await asyncio.gather(
        search_fuzzy_client(normalized, company=company),
        search_queue_client(normalized),
        return_exceptions=True,
    )

    fuzzy: list[CandidateResult]
    hpq: list[CandidateResult]

    if isinstance(fuzzy_result, BaseException):
        logger.warning("resolve_client: fuzzy_client query raised: %s", fuzzy_result)
        warnings.append(f"fuzzy_client search unavailable: {fuzzy_result}")
        fuzzy = []
    else:
        fuzzy = fuzzy_result  # type: ignore[assignment]

    if isinstance(hpq_result, BaseException):
        logger.warning("resolve_client: hpq query raised: %s", hpq_result)
        warnings.append(f"high_priority_queue_client search unavailable: {hpq_result}")
        hpq = []
    else:
        hpq = hpq_result  # type: ignore[assignment]

    search_summary = SearchSummary(
        fuzzy_client_hits=len(fuzzy),
        hpq_client_hits=len(hpq),
    )

    # 3. Handle zero candidates (Section 12: no LLM call needed)
    if not fuzzy and not hpq:
        return LookupResult(
            match_found=False,
            confidence=0.0,
            adjudication=AdjudicationMethod.RULE_BASED,
            candidates_evaluated=0,
            search_summary=search_summary,
            warnings=warnings + ["No candidates found in either source"],
        )

    # 4. Dedup within each source
    fuzzy, hpq = _dedup_candidates(fuzzy, hpq)

    # 5. Fast-path check
    fast_result = _fast_path(fuzzy, hpq, company, search_summary)
    if fast_result is not None:
        fast_result.warnings.extend(warnings)
        return fast_result

    # 6. LLM call
    llm_decision = await _call_llm(normalized, company, context, fuzzy, hpq)

    if llm_decision is None:
        # LLM unavailable — activate Levenshtein fallback
        return _levenshtein_fallback(fuzzy, hpq, search_summary, warnings)

    # 7. Apply business rules on top of LLM decision
    return _parse_llm_response(llm_decision, fuzzy, hpq, search_summary, warnings)

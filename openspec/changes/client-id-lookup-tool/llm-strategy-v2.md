# LLM Strategy v2: GWM Client ID Resolution

**Version:** 2.0 (Iteration 2 of 3 cross-review)
**Date:** 2026-03-30
**Status:** Draft — Supersedes any v1 LLM strategy notes
**Author:** LLM Architect

---

## 1. Summary of Changes from v1

v1 defined LLM adjudication in broad strokes against the wrong table definitions.
This document corrects the schema, reconciles the three expert perspectives, and
settles every open architectural question in one canonical document.

Key changes:

- Correct table schemas applied throughout (playbook.fuzzy_client, galileo.high_priority_queue_client)
- Label parsing decision made: LLM handles name extraction from label bio text, not pre-parse
- One canonical Pydantic schema defined; Python expert's models updated to match
- Model selection decision: gpt-4o-mini confirmed sufficient, with reasoning
- Fast-path (skip LLM) integrated from Python expert's design
- Conflicting gwm_id handling added as an explicit LLM instruction
- Disambiguation thresholds tightened and given concrete rules
- Scoring difference between the two tables is communicated to the LLM

---

## 2. Table Structure Reference (Corrected)

These are the exact tables this strategy is designed against.

### 2.1 playbook.fuzzy_client

| Column    | Type | Notes                                        |
|-----------|------|----------------------------------------------|
| gwm_id    | TEXT | GWM client identifier                        |
| name      | TEXT | Full client name. GIN trigram index.         |
| companies | TEXT | Associated companies, may be NULL            |

DB query uses `similarity(name, $1)`. Returns a score in [0..1] where 1.0 is
an exact string match. Scores above 0.3 are worth surfacing to the LLM.

### 2.2 galileo.high_priority_queue_client

| Column         | Type | Notes                                              |
|----------------|------|----------------------------------------------------|
| entity_id      | TEXT | GWM ID when entity_id_type = 'Client'              |
| entity_id_type | TEXT | Must be filtered: `entity_id_type = 'Client'`      |
| label          | TEXT | Name + short bio in one text field. GIN index.     |

DB query uses `word_similarity($1, label)`. This measures how well the query
appears as a contiguous substring of the label, rather than overall string
overlap. Score semantics differ from `similarity()`. A score of 0.4 here is
meaningfully different from 0.4 in fuzzy_client.

---

## 3. Label Parsing Decision

### The Problem

The `label` field in the queue table contains structured bio text such as:

```
Smith, John A. | Managing Director | Goldman Sachs | New York
```

or less structured text like:

```
John Smith - Senior Advisor at Morgan Stanley. Previously at JPMorgan.
```

The Postgres expert correctly flagged that a naive comma-split to extract the
name is brittle and will fail on the second format. The question is whether
to pre-parse the name server-side or let the LLM handle it.

### Decision: LLM Handles Name Extraction

Pre-parsing is rejected for the following reasons:

1. There is no single reliable delimiter pattern across all label values. Any
   regex will fail on edge cases and silently degrade quality.
2. The LLM already receives the raw label text. Parsing a name out of it is
   exactly the kind of natural language understanding LLMs do well.
3. Adding a pre-parse step introduces a new code path that can fail
   independently, adding latency and a new failure mode for zero benefit.
4. The word_similarity() score already confirms that the query name appears
   somewhere in the label text. The LLM's job is to judge whether that
   appearance is a name match or incidental (e.g., "Goldman" contains "old").

### Prompt Instruction

The prompt explicitly tells the LLM what format to expect and how to interpret it:

> The `label` field contains free-form bio text where the person's name typically
> appears near the beginning, often followed by a pipe or dash delimiter and
> their title/firm. Extract the person's name from the label for comparison.
> The full label text is shown so you can use company and title as corroborating
> context.

This keeps the logic in one place (the prompt) and benefits from LLM robustness
to format variation without any code changes.

---

## 4. Canonical Pydantic Schema

One schema is defined here. The Python expert's implementation must use these
exact models. No divergence is acceptable because the agent tool, REST endpoint,
and bulk endpoint all share the same response type.

### 4.1 Candidate (used internally and surfaced in ambiguous responses)

```python
class CandidateResult(BaseModel):
    gwm_id: str
    name: str                        # display name for this candidate
    source: Literal["fuzzy_client", "high_priority_queue_client"]
    db_score: float                  # raw similarity or word_similarity score from DB
    companies: str | None = None     # only populated from fuzzy_client
    label_excerpt: str | None = None # first 200 chars of label, only from hpq
```

The `db_score` field uses the raw score from whichever DB function produced
it. The LLM is told which score type each candidate carries (see Section 6).

### 4.2 LookupResult (single lookup response)

```python
class AdjudicationMethod(str, Enum):
    LLM = "llm"
    FAST_PATH = "fast_path"        # single high-confidence match, LLM skipped
    RULE_BASED = "rule_based"      # LLM failed, highest-score candidate returned

class LookupResult(BaseModel):
    match_found: bool
    gwm_id: str | None = None
    matched_name: str | None = None
    source: Literal["fuzzy_client", "high_priority_queue_client"] | None = None
    confidence: float              # 0.0..1.0, always present (0.0 on no match)
    adjudication: AdjudicationMethod
    resolution_factors: list[str] = []
    conflict: bool = False
    ambiguous: bool = False
    candidates: list[CandidateResult] = []  # populated when ambiguous=True
    candidates_evaluated: int = 0
    warnings: list[str] = []      # partial DB failures, etc.
    search_summary: SearchSummary

class SearchSummary(BaseModel):
    fuzzy_client_hits: int
    hpq_client_hits: int
```

### 4.3 LLM Response Schema (internal — what the LLM returns)

This is the JSON the LLM is instructed to produce. It is NOT the same as
LookupResult. The Python layer translates from this to LookupResult.

```python
class LLMDecision(BaseModel):
    match_found: bool
    gwm_id: str | None
    matched_name: str | None
    source: Literal["fuzzy_client", "high_priority_queue_client"] | None
    confidence: float              # LLM's self-assessed confidence 0.0..1.0
    conflict: bool
    conflict_gwm_ids: list[str]    # populated when conflict=True
    ambiguous: bool
    resolution_factors: list[str]
    candidates_considered: int
```

The separation between LLMDecision and LookupResult matters because:
- The Python layer applies business rules on top of the LLM decision (e.g.,
  capping confidence on conflict to 0.5, enforcing the fast-path override)
- LookupResult carries fields the LLM does not generate (warnings, search_summary)
- This keeps the LLM's output minimal and parseable

### 4.4 Bulk Models

```python
class BulkLookupItem(BaseModel):
    name: str
    company: str | None = None
    context: str | None = None

class BulkLookupRequest(BaseModel):
    lookups: list[BulkLookupItem] = Field(..., max_length=50)

class BulkResultItem(LookupResult):
    index: int
    input: BulkLookupItem
    error: str | None = None

class BulkLookupResponse(BaseModel):
    results: list[BulkResultItem]
    summary: BulkSummary

class BulkSummary(BaseModel):
    total: int
    matched: int
    unmatched: int
    errored: int
```

---

## 5. Model Selection: gpt-4o-mini Confirmed

### The Question

The Postgres expert's word_similarity() and similarity() handle the hard fuzzy
matching. By the time the LLM is invoked, it receives a short ranked list (up
to 10 candidates per table, post-deduplication typically 5-15 total). The
task is:

1. Parse a name out of label text (easy NLU)
2. Judge whether any candidate matches the query name, given common nickname
   variations and company context
3. Decide between conflicting gwm_ids when they appear to be the same person
4. Report confidence and whether the result is ambiguous

### Decision: gpt-4o-mini

gpt-4o-mini is sufficient. The reasoning:

- The matching problem is already solved by the DB layer. The LLM is not doing
  semantic search; it is doing a constrained judgment on a small candidate list.
- The prompt is short (under 1000 tokens for a typical request), the candidate
  list is short, and the output schema is simple JSON.
- gpt-4o-mini produces deterministic structured output reliably at temperature
  0.0 with JSON mode enabled. The task does not require reasoning depth.
- Cost at gpt-4o-mini rates for 10,000 lookups/day is roughly $0.50-$2.00/day.
  gpt-4o would be ~20x more expensive with no accuracy benefit for this task.
- The fast-path (see Section 6) skips the LLM for high-confidence single-source
  matches, reducing actual LLM call volume by an estimated 40-60%.

### Escalation Reserve (not implemented in V1)

If accuracy benchmarking against the labeled test set falls below 90% true
positive rate (Section 6.1 of the product spec), escalation to gpt-4o for
difficult cases is the first lever to pull. The routing logic should be:
- candidate_count >= 5 AND max_db_score < 0.6 AND company not provided
  → escalate to gpt-4o

This is a V2 optimization. V1 uses gpt-4o-mini universally.

---

## 6. Fast-Path Integration

The Python expert's fast-path design is adopted with one modification. The
original checked `gwm_id is not None AND similarity >= 0.8`. This is updated
to be source-aware because the two tables use different score functions.

### Fast-Path Rules

```
Fast path is triggered when ALL of the following hold:
  1. Total deduplicated candidates = 1 (only one unique gwm_id across both tables)
  2. Source is fuzzy_client AND similarity score >= 0.85
     OR
     Source is high_priority_queue_client AND word_similarity score >= 0.75
       (word_similarity is inherently lower; 0.75 here is equivalent confidence
        to 0.85 similarity)
  3. No company was provided in the query (if company provided, always use LLM
     to verify the company match, even if name score is high)
```

### Fast-Path Response Construction

```python
def _build_fast_path_result(candidate: CandidateResult, search_summary: SearchSummary) -> LookupResult:
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
            "LLM adjudication skipped: unambiguous match"
        ],
        candidates_evaluated=1,
        search_summary=search_summary
    )
```

The confidence is capped at 0.95 to signal that even a fast-path result is
not certainty. A score of 1.0 is never returned; the system is fuzzy matching,
not exact lookup.

---

## 7. Conflicting gwm_id Handling

### The Scenario

fuzzy_client returns gwm_id=78234 and high_priority_queue_client returns
gwm_id=91102 for what appears to be the same person.

### How the LLM Is Instructed

The prompt includes explicit handling instructions for this case. The LLM is
told (a) that this CAN happen, (b) what it means, and (c) what to do:

```
CONFLICT DETECTION:
If you identify the same person appearing in both sources with DIFFERENT gwm_ids,
this is a data conflict that cannot be resolved by name matching alone. In this case:
- Set "conflict": true
- List both gwm_ids in "conflict_gwm_ids"
- Set "match_found": false (do not pick one arbitrarily)
- Set "confidence" to reflect how confident you are that these ARE the same person
  (which is what makes the conflict meaningful)
- Explain the conflict in "resolution_factors"

If the same person appears in both sources with the SAME gwm_id, this is
corroboration. Weight it strongly in favor of a match.
```

### Post-LLM Business Rule

After the LLM returns a decision with `conflict=True`, the Python layer applies:

```python
if llm_decision.conflict:
    result.match_found = False
    result.confidence = min(llm_decision.confidence, 0.5)  # hard cap per product spec
    result.conflict = True
    result.candidates = [
        CandidateResult(gwm_id=gid, ...) for gid in llm_decision.conflict_gwm_ids
    ]
    result.resolution_factors.append(
        "Manual verification required: conflicting gwm_ids in source tables"
    )
```

The confidence cap at 0.5 is a product spec requirement (Section 5.4) and is
enforced in code regardless of what the LLM self-reports. The LLM's confidence
in the conflict scenario represents "how sure am I these are the same person,"
not "how sure am I of the gwm_id" — these are different quantities, and keeping
both is useful for downstream analysis.

---

## 8. Disambiguation Logic: When to Return needs_disambiguation vs Best Match

The product spec uses `ambiguous: true`. This document settles the exact rules.

### Disambiguation Decision Tree

```
Given a set of candidates after LLM evaluation:

1. ZERO candidates:
   → match_found=False, ambiguous=False, confidence=0.0
   → "No candidates found in either source."

2. ONE candidate, LLM confidence >= 0.7:
   → match_found=True, pick that candidate
   → (fast-path may have already handled this; see Section 6)

3. ONE candidate, LLM confidence < 0.7:
   → match_found=False, ambiguous=False, confidence=LLM confidence
   → "Candidate found but confidence too low to assert match."
   → Include the candidate in candidates[] so the caller can inspect it

4. MULTIPLE candidates, one has confidence >= 0.7 AND next-best confidence
   is < (best - 0.15):
   → match_found=True, pick the best
   → The 0.15 gap ensures we are not picking arbitrarily between near-equal scores

5. MULTIPLE candidates, no clear winner (gap < 0.15 or all < 0.7):
   → match_found=False, ambiguous=True
   → Include up to 5 best candidates in candidates[]
   → "Multiple potential matches found. Provide company, title, or other context."

6. CONFLICT (different gwm_ids for apparent same person):
   → See Section 7. Treated as its own category, not "ambiguous."
```

### The Gap Rule Rationale

The 0.15 confidence gap threshold prevents a common failure mode: the LLM
assigns 0.82 and 0.79 to two different "John Smith" candidates, and the system
picks the first one. From the user's perspective these are effectively tied.
The gap threshold forces the system to ask for more context rather than make
a plausible but unreliable guess.

The gap threshold is a configurable constant in the resolver:

```python
DISAMBIGUATION_GAP_THRESHOLD = 0.15
MIN_MATCH_CONFIDENCE = 0.70
```

---

## 9. Prompt Design v2

This is the complete, production system prompt. It replaces the draft in
Appendix A of the product spec.

### 9.1 System Prompt

```
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
}
```

### 9.2 User Message Template

```python
def _build_user_message(
    name: str,
    company: str | None,
    context: str | None,
    fuzzy_candidates: list[CandidateResult],
    hpq_candidates: list[CandidateResult],
) -> str:
    lines = ["QUERY:"]
    lines.append(f"  Name: {name}")
    lines.append(f"  Company: {company or 'not provided'}")
    lines.append(f"  Additional context: {context or 'none'}")
    lines.append("")

    if fuzzy_candidates:
        lines.append("CANDIDATES FROM CLIENT DIRECTORY (playbook.fuzzy_client):")
        lines.append("  [Score type: similarity() — higher is stronger, max 1.0]")
        for c in fuzzy_candidates:
            companies_str = c.companies or "none listed"
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
```

### 9.3 OpenAI Call Configuration

```python
ADJUDICATOR_CONFIG = {
    "model": "gpt-4o-mini",
    "temperature": 0.0,
    "response_format": {"type": "json_object"},
    "max_tokens": 512,   # LLMDecision JSON is always < 200 tokens; 512 is safe headroom
    "timeout": 15.0,     # asyncio.wait_for wraps this; matches product spec
}
```

`response_format: json_object` is used instead of pure prompt instruction for
two reasons:
1. It guarantees no markdown fences in the response, eliminating the defensive
   strip logic the Python expert added (which can still be retained as defense-
   in-depth but should never trigger)
2. It enables faster token generation (no schema negotiation in streamed output)

---

## 10. Candidate Deduplication Before LLM Call

Both tables can return the same gwm_id for the same person. Before building
the LLM prompt, deduplicate by gwm_id while preserving source metadata.

### Deduplication Strategy

```python
def deduplicate_candidates(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
) -> tuple[list[CandidateResult], list[CandidateResult]]:
    """
    Deduplicates candidates by gwm_id across both lists.
    When the same gwm_id appears in both sources, keep BOTH entries.
    The LLM prompt will show both, which signals cross-table corroboration.
    Only deduplicate within each source (remove lower-scoring duplicates
    from the same table if a gwm_id appears twice, which should be rare).
    Returns (deduplicated_fuzzy, deduplicated_hpq).
    """
    def dedup_within(candidates: list[CandidateResult]) -> list[CandidateResult]:
        seen: dict[str, CandidateResult] = {}
        for c in sorted(candidates, key=lambda x: x.db_score, reverse=True):
            if c.gwm_id not in seen:
                seen[c.gwm_id] = c
        return list(seen.values())

    return dedup_within(fuzzy), dedup_within(hpq)
```

Cross-source duplicates (same gwm_id in both tables) are intentionally kept
in both candidate lists rather than collapsed. Showing the LLM that "this
gwm_id appears in both sources" is meaningful corroborating evidence, and the
prompt explicitly instructs the LLM to weight cross-table agreement.

---

## 11. Rule-Based Fallback (LLM Failure Path)

When the LLM call times out or returns unparseable output, the system falls
back to a deterministic rule-based ranking. This fallback must be reliable
because it is the last line of defense before returning a 504.

### Fallback Algorithm

```python
def rule_based_fallback(
    fuzzy: list[CandidateResult],
    hpq: list[CandidateResult],
    search_summary: SearchSummary,
) -> LookupResult:
    """
    Selects the best candidate by normalized score.
    fuzzy scores are used as-is (similarity scale).
    hpq scores are normalized upward by 1.2x to compensate for word_similarity
    scale difference (heuristic; can be tuned against labeled data).
    """
    NORMALIZATION_FACTOR_HPQ = 1.20
    FALLBACK_CONFIDENCE_CAP = 0.60

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
            warnings=["LLM adjudication failed; rule-based fallback found no candidates"],
        )

    best_score, best_candidate = max(normalized, key=lambda x: x[0])
    effective_confidence = min(best_score, FALLBACK_CONFIDENCE_CAP)

    # Only assert match_found=True if score clears the minimum threshold
    if effective_confidence < 0.40:
        return LookupResult(
            match_found=False,
            confidence=effective_confidence,
            adjudication=AdjudicationMethod.RULE_BASED,
            candidates_evaluated=len(normalized),
            search_summary=search_summary,
            warnings=["LLM adjudication failed; best rule-based candidate below threshold"],
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
        warnings=["LLM adjudication failed; result is rule-based and may be less accurate"],
    )
```

---

## 12. Complete Resolution Flow

```
lookup_client_id(name, company, context)
        │
        ├─ Input validation (name 1..200 chars)
        │
        ├─ asyncio.gather(
        │     db_search_fuzzy_client(name, company, limit=10),
        │     db_search_hpq_client(name, company, limit=10)
        │  )  ← concurrent, independent DB queries
        │
        ├─ Handle partial DB failure:
        │     If one source fails, continue with the other + add warning
        │     If both fail, raise database_unavailable
        │
        ├─ If total candidates == 0:
        │     Return match_found=False immediately (no LLM call)
        │
        ├─ deduplicate_candidates(fuzzy_results, hpq_results)
        │
        ├─ FAST PATH CHECK:
        │     single unique gwm_id AND score >= threshold (see Section 6)?
        │     AND no company provided?
        │     └─ Yes → return _build_fast_path_result()
        │     └─ No  → continue to LLM
        │
        ├─ asyncio.wait_for(
        │     openai_client.chat.completions.create(...),
        │     timeout=15.0
        │  )
        │     On timeout or OpenAI error → rule_based_fallback()
        │     On JSON parse error        → rule_based_fallback()
        │
        ├─ Parse LLMDecision from response
        │
        ├─ Apply business rules on top of LLM decision:
        │     conflict=True  → cap confidence at 0.5, match_found=False
        │     ambiguous=True → match_found=False
        │     confidence < MIN_MATCH_CONFIDENCE → match_found=False
        │     gap_check (see Section 8) → may override match_found=True to False
        │
        └─ Return LookupResult
```

---

## 13. Token Budget and Cost Estimate

### Per-Request Token Estimate

| Component              | Tokens (typical) | Tokens (worst case) |
|------------------------|------------------|---------------------|
| System prompt          | ~520             | ~520 (fixed)        |
| User message header    | ~40              | ~60                 |
| Fuzzy candidates (10)  | ~150             | ~200                |
| HPQ candidates (10)    | ~250             | ~400 (long labels)  |
| Total input            | ~960             | ~1180               |
| Output (LLMDecision)   | ~120             | ~180                |
| **Total**              | **~1080**        | **~1360**           |

### Cost Projection (gpt-4o-mini, March 2026 pricing ~$0.15/1M input, $0.60/1M output)

| Volume            | Input cost | Output cost | Total/day |
|-------------------|------------|-------------|-----------|
| 1,000 lookups/day | $0.14      | $0.07       | $0.21     |
| 10,000/day        | $1.44      | $0.72       | $2.16     |
| 50,000/day        | $7.20      | $3.60       | $10.80    |

Fast-path deflection (estimated 40-60% skip rate) reduces these costs further.
At 10,000 lookups/day with 50% fast-path: ~$1.08/day.

---

## 14. Accuracy Instrumentation

The product spec requires >= 90% true positive rate against a labeled test set.
To benchmark this in production, the following fields must be logged to a
structured log sink (not the DB in V1):

```json
{
  "ts": "2026-03-30T14:22:11Z",
  "query_name": "John Smith",
  "query_company": "Acme Corp",
  "adjudication": "llm",
  "match_found": true,
  "gwm_id": "GWM-12345",
  "confidence": 0.92,
  "conflict": false,
  "ambiguous": false,
  "fuzzy_client_hits": 2,
  "hpq_client_hits": 1,
  "candidates_evaluated": 3,
  "llm_latency_ms": 847,
  "total_latency_ms": 1102
}
```

This structured log allows post-hoc accuracy analysis when a labeled test set
becomes available. The log is written to stdout as JSON (FastAPI structured
logging) so it flows into whatever log aggregation the team uses.

---

## 15. Open Questions Resolved in v2

| Question (from product spec Section 10) | v2 Decision |
|------------------------------------------|-------------|
| GIN index type (trigram vs full-text)    | Assumed trigram (gin_trgm_ops) based on use of similarity()/word_similarity(). DBA must confirm before implementation. If full-text, query operators change entirely. |
| Galileo schema permissions               | Must be confirmed before implementation. The Python expert should add a startup health check that tests `SELECT 1 FROM galileo.high_priority_queue_client LIMIT 1`. |
| Data freshness                           | Out of scope for LLM strategy. Noted in search_summary only. |
| Nickname mapping                         | Handled in LLM prompt (see Section 9.1). Static lookup table is not needed in V1. |
| Usage analytics                          | Structured log to stdout in V1 (see Section 14). DB logging deferred to V2. |

---

## 16. Items Deferred to Iteration 3

1. gpt-4o escalation routing for genuinely hard cases (Section 5 defines criteria)
2. Redis caching of lookup results (keyed on normalized name + company hash)
3. Nickname expansion at the DB query layer (expand "Bob" to "Bob OR Robert"
   using a nicknames table before the GIN query)
4. Cross-reference with playbook.entities to auto-link resolved gwm_ids to
   campaign entity records
5. Confidence calibration: compare LLM self-reported confidence against labeled
   ground truth to determine if a calibration offset is needed

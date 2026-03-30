# Product Specification: Client ID Lookup Tool (GWM ID Resolution)

**Version:** 2.0 (Consolidated from Iteration 1 expert reviews)
**Date:** 2026-03-30
**Status:** Approved for implementation
**Author:** Product Owner
**Reviewers:** LLM Expert, Postgres Expert, Python Expert

---

## Change Log from v1

| # | Change | Rationale |
|---|--------|-----------|
| 1 | Corrected all table references from `playbook.entities`/`entity_library` to `playbook.fuzzy_client` and `galileo.high_priority_queue_client` | Python expert designed against wrong tables |
| 2 | Standardized on `gpt-4o-mini` for adjudication model | LLM expert specified `gpt-4o-mini`; Python expert assumed `gpt-4o`. Mini is sufficient for name matching and 10x cheaper |
| 3 | Removed `GET /api/client-lookup` endpoint | Scope creep. The POST endpoint covers all use cases. GET encourages name-in-query-string which has URL-encoding/logging issues |
| 4 | Deferred bulk endpoint to v1.1 | Bulk adds significant complexity (concurrency control, partial failure, timeout management) for a feature no user has requested yet |
| 5 | Removed `services/client_resolver.py` layer | No services layer exists in this codebase. Logic lives in db modules and tool functions directly. Adding a service layer for one feature breaks the established pattern |
| 6 | Unified LLM response schema with Pydantic models | LLM expert's response schema and Python expert's Pydantic models had divergent field names and structures |
| 7 | Adopted Postgres expert's separate-query approach over UNION | Correct: two different schemas, different operators, merge in Python |
| 8 | Added `word_similarity()` + `%>` for hpq table per Postgres expert | `label` contains name-within-bio text; `word_similarity` handles substring-in-longer-text better than `similarity` |
| 9 | Specified Levenshtein fallback from LLM expert as concrete implementation | Rule-based fallback is essential for reliability |
| 10 | Clarified `SET LOCAL` threshold tuning is transaction-scoped per Postgres expert | Prevents leaking threshold changes to other connections |
| 11 | Added missing edge case: galileo schema not in search_path | Must use fully-qualified `galileo.high_priority_queue_client` in all queries |
| 12 | Removed `models/client_lookup.py` as separate file | Pydantic models go in `app/models/client_lookup.py` per existing pattern, but this is only needed if we ship the REST endpoint. For v1, models are internal to the tool |

---

## 1. Problem Statement

Users need to determine whether a person has a GWM client ID. Today this requires manual queries across two separate database tables in two different schemas, knowledge of GIN-indexed fuzzy matching syntax, and subjective judgment about whether a candidate row actually matches the person in question. This process is slow, error-prone, and inaccessible to non-technical users.

The Client ID Lookup Tool automates this workflow: accept a person's name (with optional context), search both data sources using fuzzy matching, have the LLM adjudicate candidates, and return a structured, confidence-scored result.

---

## 2. Data Sources

### 2.1 playbook.fuzzy_client

| Column    | Type | Notes                                  |
|-----------|------|----------------------------------------|
| gwm_id    | TEXT | The GWM client identifier              |
| name      | TEXT | Client full name. GIN-indexed (pg_trgm) |
| companies | TEXT | Associated company names (may be NULL) |

- **Schema:** `playbook`
- **Index:** GIN on `name` using `gin_trgm_ops`
- **Query operator:** `similarity(name, $1)` + `name % $1` (standard trigram; names are short strings where full-token trigram works well)
- **Access:** Via existing asyncpg pool (`_acquire()` from `app.db._pool`), search_path already includes `playbook`
- **Notes:** This is a read-only reference table. We do not own its schema.

### 2.2 galileo.high_priority_queue_client

| Column         | Type | Notes                                                    |
|----------------|------|----------------------------------------------------------|
| entity_id      | TEXT | The GWM ID (when entity_id_type = 'Client')              |
| entity_id_type | TEXT | Filter: must equal `'Client'` for gwm_id resolution      |
| label          | TEXT | Name + short bio. GIN-indexed (pg_trgm)                  |

- **Schema:** `galileo` (NOT in the connection pool's search_path)
- **Index:** GIN on `label` using `gin_trgm_ops`
- **Query operator:** `word_similarity(label, $1)` + `label %> $1` (word-level trigram; better for matching a name substring within a longer bio string)
- **Access:** MUST use fully-qualified `galileo.high_priority_queue_client` since search_path is `playbook, public`
- **Key constraint:** Only rows where `entity_id_type = 'Client'` are relevant; `entity_id` becomes the gwm_id
- **Notes:** This is a read-only external table in a different schema. We do not own it.

### 2.3 Open Questions (Carry-forward)

1. **GIN index expression:** Need DBA confirmation that indexes use `gin_trgm_ops` (not `tsvector`). If they use `tsvector`, the query operators must change to `@@`/`to_tsquery()`.
2. **Galileo schema permissions:** Confirm the application's database role has `SELECT` access to `galileo.high_priority_queue_client`.
3. **Companies column type:** Is `fuzzy_client.companies` a single TEXT value or a delimited list? This affects how we pass it to the LLM prompt.

---

## 3. User Stories

### US-1: Basic Name Lookup (v1 -- MUST HAVE)

**As a** research analyst,
**I want to** ask "Does John Smith have a client ID?"
**So that** I get back a GWM ID (or a clear "no match") without writing SQL.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | User provides a person name via the chat interface | The agent tool receives the `name` parameter |
| 2 | System searches `playbook.fuzzy_client` using `similarity(name, $1)` with threshold >= 0.3 | Unit test confirms query uses trigram similarity |
| 3 | System searches `galileo.high_priority_queue_client` using `word_similarity($1, label)` with threshold >= 0.3, filtered to `entity_id_type = 'Client'` | Unit test confirms query uses word_similarity with type filter |
| 4 | Both queries run concurrently via `asyncio.gather` | Integration test confirms wall-clock time < sequential sum |
| 5 | Candidates from both sources are deduplicated by `gwm_id` in Python, then passed to the LLM for adjudication | Dedup logic tested with overlapping gwm_ids |
| 6 | If a match exists, the response includes the gwm_id, matched name, source table, and a confidence level | Tool return string validated |
| 7 | If no match exists, the response states "no match found" with an explanation of what was searched | Explanation references both tables |
| 8 | Response completes within 5 seconds for a single lookup (DB queries + LLM) | p95 latency under 5s |
| 9 | The tool is registered in `TOOL_REGISTRY` and available to the research agent via function calling | `get_openai_tools()` includes the new tool schema |
| 10 | If LLM is unavailable, deterministic Levenshtein fallback produces a result with confidence capped at "low" | Fallback tested in isolation |

### US-2: Lookup with Company/Context (v1 -- MUST HAVE)

**As a** research analyst,
**I want to** ask "Does John Smith at Acme Corp have a client ID?"
**So that** I can disambiguate common names using company affiliation.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | User provides a name AND optional company/context string | Tool schema has optional `company` and `context` parameters |
| 2 | For `fuzzy_client`, company info is passed to the LLM prompt for ranking (NOT used as SQL filter on `companies` column -- too brittle) | LLM prompt includes company context |
| 3 | For `high_priority_queue_client`, the LLM considers company context when evaluating the `label` field (which contains bio text) | LLM prompt instructs company weighting |
| 4 | LLM adjudication considers the company context when deciding between multiple candidates | System prompt includes explicit instruction to weigh company match |
| 5 | When company context resolves an otherwise-ambiguous match, the response notes this | Response string explains resolution factors |

### US-3: Bulk Lookup (DEFERRED to v1.1)

**Rationale for deferral:** No user has requested bulk lookup. The agent tool handles one lookup at a time naturally. Adding batch processing (concurrency control with `asyncio.Semaphore`, partial failure handling, 30-second timeout budgets, summary statistics) adds significant implementation and testing complexity. We will revisit after v1 usage data shows demand.

### US-4: REST API Endpoint (v1 -- SHOULD HAVE)

**As a** developer,
**I want to** call a REST endpoint to look up a client ID programmatically,
**So that** I can integrate client lookup into other tools without going through the chat agent.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | `POST /api/client-lookup` accepts JSON body with `name`, optional `company`, optional `context` | Pydantic model validates input |
| 2 | Response follows the same JSON schema as the agent tool's structured output | Shared Pydantic model |
| 3 | Endpoint requires JWT authentication via existing `get_current_user` dependency | 401 on missing/invalid JWT |
| 4 | No `GET` endpoint (names in query strings create URL-encoding, caching, and logging concerns) | Only POST exists |

---

## 4. Scope

### 4.1 In Scope (v1)

| Deliverable | File | Notes |
|-------------|------|-------|
| DB query module | `backend/app/db/client_lookup.py` | Two functions: `db_search_fuzzy_client()`, `db_search_hpq_client()` |
| Agent tool | `backend/app/agent/tools.py` | `lookup_client_id` via `@_register` decorator |
| REST endpoint | `backend/app/routers/client_lookup.py` | `POST /api/client-lookup` only |
| Pydantic models | `backend/app/models/client_lookup.py` | Request/response models |
| Router registration | `backend/app/main.py` | Add `client_lookup_router` |
| DB exports | `backend/app/db/__init__.py` | Export new DB functions |
| Unit tests | `backend/tests/test_client_lookup_unit.py` | Mock DB + LLM, edge cases |
| Integration tests | `backend/tests/test_client_lookup_integration.py` | End-to-end with test data |

### 4.2 Out of Scope (v1)

- **Bulk endpoint** -- deferred to v1.1 pending usage data
- **GET endpoint** -- not shipping (see rationale above)
- **Frontend UI** -- no dedicated lookup page; users interact via chat agent or API
- **Redis caching** -- no caching of lookup results
- **Audit logging** -- no persistent log of lookups
- **Write-back** -- read-only; no updating client records
- **Cross-reference with `playbook.entities`** -- no auto-population of `gwm_id` on campaign entities
- **Rate limiting** -- beyond existing API middleware
- **Galileo schema management** -- read-only external table

---

## 5. Technical Architecture

### 5.1 Database Layer: `backend/app/db/client_lookup.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from ._pool import _acquire


@dataclass(frozen=True, slots=True)
class ClientCandidate:
    gwm_id: str
    name: str
    source: str              # "fuzzy_client" | "high_priority_queue_client"
    similarity: float        # 0.0 - 1.0
    companies: str | None    # only from fuzzy_client
    raw_label: str | None    # only from hpq (full label with bio text)


async def db_search_fuzzy_client(
    name: str,
    *,
    threshold: float = 0.3,
    limit: int = 10,
) -> list[ClientCandidate]:
    """Search playbook.fuzzy_client using trigram similarity on name.

    Uses SET LOCAL to safely adjust pg_trgm.similarity_threshold within
    a transaction, preventing leakage to other connections.
    """
    ...


async def db_search_hpq_client(
    name: str,
    *,
    threshold: float = 0.3,
    limit: int = 10,
) -> list[ClientCandidate]:
    """Search galileo.high_priority_queue_client using word_similarity on label.

    Filters to entity_id_type = 'Client' only.
    Uses fully-qualified table name (galileo schema not in search_path).
    Uses SET LOCAL to safely adjust pg_trgm.word_similarity_threshold.
    """
    ...
```

**Key SQL patterns (from Postgres expert review):**

For `fuzzy_client`:
```sql
BEGIN;
SET LOCAL pg_trgm.similarity_threshold = $2;
SELECT gwm_id, name, companies, similarity(name, $1) AS sim
FROM playbook.fuzzy_client
WHERE name % $1
ORDER BY sim DESC
LIMIT $3;
COMMIT;
```

For `high_priority_queue_client`:
```sql
BEGIN;
SET LOCAL pg_trgm.word_similarity_threshold = $2;
SELECT entity_id AS gwm_id, label, word_similarity($1, label) AS sim
FROM galileo.high_priority_queue_client
WHERE entity_id_type = 'Client'
  AND label %> $1
ORDER BY sim DESC
LIMIT $3;
COMMIT;
```

**Implementation notes:**
- Each query uses `SET LOCAL` inside a transaction for threshold safety (Postgres expert recommendation)
- Per-source fetch limit = `limit * 2` (fetch 20 from each source)
- Final deduplication in Python by `gwm_id`, keeping the higher-similarity entry
- Final limit = 10 candidates passed to LLM
- Both queries executed via `asyncio.gather` for concurrency
- Each query wrapped in its own `_acquire()` context manager (separate connections for parallel execution)

### 5.2 LLM Adjudication

**Model:** `gpt-4o-mini` (via `app.openai_factory.get_openai_client()`)

**Rationale (from LLM expert):** Name matching is a classification task, not a generation task. `gpt-4o-mini` handles structured output well, costs ~$0.000075/call, and has lower latency than `gpt-4o`. The prompt is simple and the candidate list is short.

**Structured output format (enforced via OpenAI response_format):**

```python
@dataclass(frozen=True, slots=True)
class LLMMatchResult:
    match_found: bool
    gwm_id: str | None
    matched_name: str | None
    source: str | None          # "fuzzy_client" | "high_priority_queue_client"
    confidence: float           # 0.0 - 1.0
    reasoning: str              # human-readable explanation
    conflict: bool              # True if same person appears with different gwm_ids
    ambiguous: bool             # True if multiple plausible candidates, cannot pick one
    alternatives: list[dict]    # top 3 runner-up candidates when ambiguous
```

**System prompt (refined from v1 Appendix A):**

```
You are a name-matching specialist. Given a search query and a list of
candidates from two data sources, determine if any candidate is the same
person as the query.

RULES:
1. Consider common name variations: Bob=Robert, Bill=William, Dick=Richard,
   Jim=James, Mike=Michael, etc. Also consider that initials (R. Smith)
   may match full names (Robert Smith).
2. Company match is a strong positive signal but not required.
3. If a candidate appears in BOTH sources with the SAME gwm_id, that is
   very strong evidence of a match -- increase confidence.
4. If candidates from different sources have DIFFERENT gwm_ids for what
   appears to be the same person, set conflict=true.
5. If multiple candidates are plausible and you cannot confidently select
   one, set ambiguous=true and list them in alternatives.
6. confidence thresholds:
   - >= 0.8: strong match (recommend accepting)
   - 0.5 - 0.79: moderate match (recommend human review)
   - < 0.5: weak match (report as no confident match)
```

**User prompt template:**

```
SEARCH QUERY:
- Name: {name}
- Company: {company or "not provided"}
- Additional context: {context or "none"}

CANDIDATES (numbered):
{for i, c in enumerate(candidates, 1)}
{i}. gwm_id={c.gwm_id}, name={c.name}, source={c.source},
    similarity={c.similarity:.3f}, companies={c.companies or "N/A"}
{endfor}
```

**Fallback (LLM unavailable):**

When the LLM call fails (timeout, API error, unparseable response), use a deterministic Levenshtein-based scoring (from LLM expert):
1. Rank candidates by their trigram similarity score
2. If the top candidate has similarity >= 0.8 and is 0.15+ ahead of the second candidate, return it as a match
3. Set `adjudication: "rule_based"` and cap confidence at 0.6
4. If no candidate meets the threshold, return no match

### 5.3 Agent Tool Registration

The tool follows the existing `@_register` pattern in `backend/app/agent/tools.py`:

```python
@_register(
    "lookup_client_id",
    "Look up whether a person has a GWM client ID by searching the client "
    "directory and priority queue. Provide the person's name and optionally "
    "their company or other context to disambiguate common names.",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's full name to look up."
            },
            "company": {
                "type": "string",
                "description": "Optional company name to help disambiguate."
            },
            "context": {
                "type": "string",
                "description": "Optional additional context (title, location, etc.)."
            },
        },
        "required": ["name"],
    },
)
async def lookup_client_id(
    deps: AgentDeps,
    name: str,
    company: str | None = None,
    context: str | None = None,
) -> str:
    """Tool returns a formatted string (not JSON) per the existing tool pattern."""
    ...
```

**Return value:** A formatted string (not raw JSON). All existing tools in `tools.py` return human-readable strings that the orchestrator LLM can incorporate into its response. The tool should return something like:

```
## Client ID Lookup: John Smith

**Match found:** GWM-12345
**Matched name:** John A. Smith
**Source:** fuzzy_client (client directory)
**Confidence:** 0.92 (high)
**Adjudication:** LLM

**Resolution factors:**
- Name similarity: 0.88 (trigram)
- Company match: "Acme Corporation" found in companies field
- Single strong candidate in fuzzy_client, corroborated by priority queue

**Candidates evaluated:** 3 (2 from client directory, 1 from priority queue)
```

Or for no match:
```
## Client ID Lookup: Zygmunt Brzezinski III

**No match found.**

Searched both the client directory (playbook.fuzzy_client) and priority queue
(galileo.high_priority_queue_client). No candidates exceeded the similarity
threshold (0.3) in either source.
```

### 5.4 REST Endpoint: `backend/app/routers/client_lookup.py`

```python
router = APIRouter(prefix="/api/client-lookup", tags=["client-lookup"])

@router.post("")
async def lookup_client(
    body: ClientLookupRequest,
    user: dict = Depends(get_current_user),
) -> ClientLookupResponse:
    ...
```

### 5.5 Pydantic Models: `backend/app/models/client_lookup.py`

```python
from pydantic import BaseModel, Field


class ClientLookupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=500)


class CandidateOut(BaseModel):
    gwm_id: str
    name: str
    source: str
    similarity: float
    companies: str | None = None


class SearchSummary(BaseModel):
    fuzzy_client_hits: int
    hpq_client_hits: int


class ClientLookupResponse(BaseModel):
    match_found: bool
    gwm_id: str | None = None
    matched_name: str | None = None
    source: str | None = None
    confidence: float = 0.0
    adjudication: str = "llm"           # "llm" | "rule_based"
    reasoning: str = ""
    conflict: bool = False
    ambiguous: bool = False
    candidates: list[CandidateOut] = []  # populated when ambiguous=True
    candidates_evaluated: int = 0
    search_summary: SearchSummary
    warnings: list[str] = []            # partial failures, degraded mode
```

### 5.6 File Modification Summary

| File | Change |
|------|--------|
| `backend/app/db/client_lookup.py` | **NEW** -- DB query functions |
| `backend/app/db/__init__.py` | Export `db_search_fuzzy_client`, `db_search_hpq_client` |
| `backend/app/models/client_lookup.py` | **NEW** -- Pydantic request/response models |
| `backend/app/agent/tools.py` | Add `lookup_client_id` tool registration |
| `backend/app/routers/client_lookup.py` | **NEW** -- REST endpoint |
| `backend/app/main.py` | Import and register `client_lookup_router` |
| `backend/tests/test_client_lookup_unit.py` | **NEW** -- Unit tests |
| `backend/tests/test_client_lookup_integration.py` | **NEW** -- Integration tests |

---

## 6. Edge Cases

### 6.1 No Match in Either Table

**Trigger:** User asks about "Zygmunt Brzezinski III" and neither table has a match.

**Behavior:**
- Both queries return empty result sets
- Skip LLM call (zero candidates -- no adjudication needed)
- Return `match_found: false` with explanation referencing both tables
- Confidence: 0.0

### 6.2 Multiple Strong Matches (Ambiguous)

**Trigger:** User asks about "James Johnson" and there are 5+ candidates across both tables.

**Behavior:**
- All candidates (up to 10 after dedup) passed to LLM
- If LLM cannot determine a single best match with confidence >= 0.5, return `ambiguous: true`
- Response includes `candidates` array with up to 5 best alternatives
- Explanation: "Multiple potential matches found. Please provide additional context (company, title) to narrow the result."

### 6.3 Match in One Table Only

**Trigger:** Name appears in `fuzzy_client` but not `high_priority_queue_client` (or vice versa).

**Behavior:**
- LLM adjudicates based on available candidates from one source
- Response includes `source` field to indicate provenance
- No confidence penalty for single-source match (the data is what it is)

### 6.4 Match in Both Tables with Conflicting gwm_ids

**Trigger:** "John Smith" exists in both tables but with different gwm_ids.

**Behavior:**
- LLM flags `conflict: true`
- Response includes both gwm_ids in reasoning
- Confidence capped at 0.5
- Explanation states the conflict and recommends manual verification

### 6.5 Name Variations (Nicknames, Initials, Prefixes)

**Trigger:** User asks about "Bob Smith" but the database has "Robert Smith" or "R. Smith".

**Behavior:**
- Trigram matching catches partial overlap (lower similarity scores)
- LLM system prompt handles nickname expansion (Bob=Robert, Bill=William, etc.)
- Lower similarity scores are compensated by LLM reasoning

### 6.6 One Database Query Fails

**Trigger:** `galileo.high_priority_queue_client` query times out but `fuzzy_client` succeeds.

**Behavior:**
- Return results from the working source
- Add warning to response: `"warnings": ["high_priority_queue_client query failed: connection timeout"]`
- Proceed with LLM adjudication on partial results
- HTTP 200 (not 503) -- the request partially succeeded

### 6.7 Both Database Queries Fail

**Trigger:** Database connection is down.

**Behavior:**
- Return HTTP 503 with structured error: `{"error": "database_unavailable", "message": "Unable to query client databases."}`
- For the agent tool: return a string explaining the failure so the agent can relay it to the user

### 6.8 LLM Timeout or Failure

**Trigger:** OpenAI API returns an error or times out (15-second timeout).

**Behavior:**
- Fall back to rule-based Levenshtein ranking
- Set `adjudication: "rule_based"`
- Cap confidence at 0.6
- Log the LLM failure for monitoring

### 6.9 LLM Returns Unparseable Response

**Trigger:** LLM returns text that does not match the expected JSON schema.

**Behavior:**
- Same as LLM failure: fall back to rule-based ranking
- Log the raw LLM response for debugging

### 6.10 SQL Injection / Malicious Input

**Trigger:** User provides `'; DROP TABLE fuzzy_client; --` as the name.

**Behavior:**
- All queries use asyncpg parameterized queries ($1, $2...) -- no string interpolation
- Input stripped of leading/trailing whitespace only
- GIN index handles special characters safely

### 6.11 Empty Name Input

**Trigger:** User provides `""` or `"   "` as the name.

**Behavior:**
- Pydantic validation rejects at the REST layer (`min_length=1` after strip)
- Agent tool returns early: "Please provide a person's name to look up."

### 6.12 Very Long Name Input

**Trigger:** User provides a 10,000-character string.

**Behavior:**
- Pydantic validation rejects at REST layer (`max_length=200`)
- Agent tool truncates to 200 characters before querying

---

## 7. Error Handling

### 7.1 Error Response Format (REST endpoint)

```json
{
  "error": "<error_code>",
  "message": "<human-readable description>"
}
```

### 7.2 Error Catalog

| HTTP Status | Error Code | Trigger |
|-------------|-----------|---------|
| 400 | `invalid_input` | Name empty, blank, or exceeds 200 characters |
| 401 | `unauthorized` | Missing or invalid JWT |
| 503 | `database_unavailable` | Both DB queries fail |
| 500 | `internal_error` | Unexpected exception |

### 7.3 Graceful Degradation Matrix

| Failure Mode | Behavior | HTTP Status |
|-------------|----------|-------------|
| `fuzzy_client` query fails | Search `hpq_client` only; add warning | 200 |
| `hpq_client` query fails | Search `fuzzy_client` only; add warning | 200 |
| Both queries fail | Return error | 503 |
| Both queries return empty | Return `match_found: false` | 200 |
| LLM call fails | Rule-based fallback; confidence capped at 0.6 | 200 |
| LLM returns bad JSON | Rule-based fallback (same as failure) | 200 |
| DB query takes > 5s | Query timeout; treat as query failure | 200/503 |

---

## 8. API Contract

### 8.1 Single Lookup (only endpoint in v1)

```
POST /api/client-lookup
Content-Type: application/json
Cookie: jwt=<token>

{
  "name": "John Smith",
  "company": "Acme Corporation",
  "context": "Managing Director"
}
```

**Response (match found):**
```json
{
  "match_found": true,
  "gwm_id": "GWM-12345",
  "matched_name": "John A. Smith",
  "source": "fuzzy_client",
  "confidence": 0.92,
  "adjudication": "llm",
  "reasoning": "Strong name match (similarity 0.88) with company corroboration. Single dominant candidate.",
  "conflict": false,
  "ambiguous": false,
  "candidates": [],
  "candidates_evaluated": 3,
  "search_summary": {
    "fuzzy_client_hits": 2,
    "hpq_client_hits": 1
  },
  "warnings": []
}
```

**Response (no match):**
```json
{
  "match_found": false,
  "gwm_id": null,
  "matched_name": null,
  "source": null,
  "confidence": 0.0,
  "adjudication": "none",
  "reasoning": "No candidates found in either the client directory or the priority queue.",
  "conflict": false,
  "ambiguous": false,
  "candidates": [],
  "candidates_evaluated": 0,
  "search_summary": {
    "fuzzy_client_hits": 0,
    "hpq_client_hits": 0
  },
  "warnings": []
}
```

**Response (ambiguous):**
```json
{
  "match_found": false,
  "gwm_id": null,
  "matched_name": null,
  "source": null,
  "confidence": 0.0,
  "adjudication": "llm",
  "reasoning": "Multiple candidates with similar confidence. Cannot determine unique match without additional context.",
  "conflict": false,
  "ambiguous": true,
  "candidates": [
    {
      "gwm_id": "GWM-12345",
      "name": "John A. Smith",
      "source": "fuzzy_client",
      "similarity": 0.85,
      "companies": "Acme Corporation"
    },
    {
      "gwm_id": "GWM-67890",
      "name": "John B. Smith",
      "source": "high_priority_queue_client",
      "similarity": 0.82,
      "companies": null
    }
  ],
  "candidates_evaluated": 5,
  "search_summary": {
    "fuzzy_client_hits": 3,
    "hpq_client_hits": 2
  },
  "warnings": []
}
```

**Response (partial database failure):**
```json
{
  "match_found": true,
  "gwm_id": "GWM-12345",
  "matched_name": "John A. Smith",
  "source": "fuzzy_client",
  "confidence": 0.85,
  "adjudication": "llm",
  "reasoning": "Match found in client directory. Priority queue was unavailable.",
  "conflict": false,
  "ambiguous": false,
  "candidates": [],
  "candidates_evaluated": 2,
  "search_summary": {
    "fuzzy_client_hits": 2,
    "hpq_client_hits": 0
  },
  "warnings": ["high_priority_queue_client query failed: connection timeout. Results are from fuzzy_client only."]
}
```

### 8.2 Agent Tool Schema (OpenAI Function Calling)

```json
{
  "type": "function",
  "function": {
    "name": "lookup_client_id",
    "description": "Look up whether a person has a GWM client ID by searching the client directory and priority queue. Provide the person's name and optionally their company or other context to disambiguate common names.",
    "parameters": {
      "type": "object",
      "properties": {
        "name": {
          "type": "string",
          "description": "The person's full name to look up (e.g., 'John Smith')."
        },
        "company": {
          "type": "string",
          "description": "Optional company name to help disambiguate (e.g., 'Acme Corporation')."
        },
        "context": {
          "type": "string",
          "description": "Optional additional context such as title, location, or other identifying information."
        }
      },
      "required": ["name"]
    }
  }
}
```

---

## 9. Success Metrics

### 9.1 Accuracy

| Metric | Target | Measurement |
|--------|--------|-------------|
| True positive rate | >= 90% | Against a labeled test set of 100 known name-to-gwm_id pairs |
| False positive rate | <= 5% | LLM incorrectly assigns a gwm_id to the wrong person |
| Ambiguity detection rate | >= 85% | System correctly flags ambiguous cases rather than guessing |

### 9.2 Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Single lookup p50 latency | < 2 seconds | End-to-end including DB + LLM |
| Single lookup p95 latency | < 5 seconds | End-to-end including DB + LLM |
| DB query time (per table) | < 200ms | Isolated DB query without LLM |
| LLM adjudication time | < 3 seconds | Isolated OpenAI call |

### 9.3 Reliability

| Metric | Target | Measurement |
|--------|--------|-------------|
| Graceful degradation rate | 100% | When LLM fails, rule-based fallback always returns a result |
| Zero unhandled exceptions | 0 in production | Error monitoring |
| Partial failure resilience | 100% | One DB source failing never crashes the request |

---

## 10. Testing Requirements

### 10.1 Unit Tests (`backend/tests/test_client_lookup_unit.py`)

| Test | Description |
|------|-------------|
| `test_search_fuzzy_client_returns_candidates` | Mock asyncpg, verify SQL uses `similarity()` + `%` operator |
| `test_search_hpq_client_returns_candidates` | Mock asyncpg, verify SQL uses `word_similarity()` + `%>` operator and `entity_id_type='Client'` filter |
| `test_search_hpq_uses_qualified_table_name` | Verify query string contains `galileo.high_priority_queue_client` |
| `test_deduplication_by_gwm_id` | Given overlapping gwm_ids from both sources, verify dedup keeps higher similarity |
| `test_llm_adjudication_match` | Mock OpenAI, verify correct prompt construction and response parsing |
| `test_llm_adjudication_no_match` | Mock OpenAI returning no match |
| `test_llm_adjudication_ambiguous` | Mock OpenAI returning ambiguous with alternatives |
| `test_llm_adjudication_conflict` | Mock OpenAI returning conflict |
| `test_llm_fallback_on_timeout` | Mock OpenAI raising timeout, verify Levenshtein fallback |
| `test_llm_fallback_on_bad_json` | Mock OpenAI returning garbage, verify fallback |
| `test_llm_fallback_confidence_cap` | Verify rule-based results have confidence <= 0.6 |
| `test_empty_name_rejected` | Blank/whitespace-only name returns early |
| `test_long_name_truncated` | Name > 200 chars is truncated before query |
| `test_single_high_confidence_skip_llm` | When exactly one candidate has similarity >= 0.95, consider fast-path (optional optimization) |
| `test_zero_candidates_skips_llm` | No candidates from either source -> no LLM call |
| `test_tool_returns_formatted_string` | Tool function returns readable string, not JSON |

### 10.2 Integration Tests (`backend/tests/test_client_lookup_integration.py`)

| Test | Description |
|------|-------------|
| `test_end_to_end_match` | Insert test data, call tool, verify match |
| `test_end_to_end_no_match` | Empty tables, call tool, verify no match |
| `test_concurrent_queries` | Verify both DB queries run in parallel |
| `test_partial_db_failure` | Kill one query, verify partial results returned |
| `test_rest_endpoint_auth` | Verify 401 without JWT |
| `test_rest_endpoint_success` | POST with valid JWT, verify response schema |
| `test_tool_registered` | Verify `lookup_client_id` in `TOOL_REGISTRY` |
| `test_tool_in_openai_tools` | Verify `get_openai_tools()` includes the tool schema |

---

## 11. Implementation Sequence

### Phase 1: Database Layer (day 1)
1. Create `backend/app/db/client_lookup.py` with both query functions
2. Add exports to `backend/app/db/__init__.py`
3. Write unit tests for DB functions (mocked)

### Phase 2: LLM Adjudication (day 1-2)
4. Implement LLM adjudication logic in the tool function
5. Implement Levenshtein fallback
6. Write unit tests for adjudication + fallback

### Phase 3: Agent Tool (day 2)
7. Add `@_register("lookup_client_id", ...)` to `tools.py`
8. Implement the orchestration: gather queries -> dedup -> adjudicate -> format string
9. Write tool-level unit tests

### Phase 4: REST Endpoint (day 2-3)
10. Create `backend/app/models/client_lookup.py`
11. Create `backend/app/routers/client_lookup.py`
12. Register router in `backend/app/main.py`
13. Write REST endpoint tests

### Phase 5: Integration Testing (day 3)
14. Write integration tests with test data
15. Verify end-to-end flow

---

## 12. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| GIN indexes are `tsvector` not `gin_trgm_ops` | Queries fail or return no results | Medium | Check with DBA before implementation. If `tsvector`, switch to `@@`/`to_tsquery()` operators. |
| App role lacks SELECT on `galileo` schema | `hpq_client` query fails | Medium | Test in dev environment first. If no access, ship with `fuzzy_client` only and add warning. |
| `gpt-4o-mini` hallucinating gwm_ids | False positive matches | Low | LLM only selects from provided candidates; it cannot invent gwm_ids. Structured output enforces this. |
| High latency from LLM call | p95 > 5 seconds | Medium | 15-second timeout with rule-based fallback. Monitor and consider switching to local model if chronic. |
| `companies` column is a pipe-delimited string | LLM prompt formatting is wrong | Low | Inspect sample data before implementation. Pass raw value to LLM regardless of format. |

---

## Appendix A: Decisions Record

| # | Decision | Alternatives Considered | Rationale |
|---|----------|------------------------|-----------|
| D1 | `gpt-4o-mini` for adjudication | `gpt-4o`, Claude, local model | Cost/speed tradeoff. Name matching is simple classification. ~$0.13/1000 lookups. |
| D2 | Separate queries, not UNION | Single UNION query | Different schemas, different operators (`%` vs `%>`), different column semantics. Merge in Python is cleaner. |
| D3 | `word_similarity` for hpq table | `similarity` | `label` contains bio text, not just a name. `word_similarity` matches a short query within a longer string. |
| D4 | `SET LOCAL` for threshold tuning | `SET` (session-scoped) | Transaction-scoped prevents leaking to other queries on the same pooled connection. |
| D5 | No services layer | `services/client_resolver.py` | Codebase has no services layer. DB modules + tool functions is the established pattern. |
| D6 | POST only, no GET | GET + POST | Names in query strings create encoding/logging/caching issues. POST-only is standard for search endpoints. |
| D7 | Bulk deferred to v1.1 | Bulk in v1 | Adds semaphore logic, partial failure, timeout budget. No user demand yet. |
| D8 | Tool returns formatted string | Tool returns JSON | All existing tools return human-readable strings. The orchestrator LLM interprets them. |
| D9 | Dataclass for `ClientCandidate` | Pydantic BaseModel | Internal data transfer only (not serialized to HTTP). Dataclass is lighter. |
| D10 | Levenshtein fallback when LLM unavailable | No fallback / raise error | Graceful degradation is a project requirement per v1 spec. Cap confidence at 0.6. |

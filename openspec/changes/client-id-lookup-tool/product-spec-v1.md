# Product Specification: Client ID Lookup Tool (GWM ID Resolution)

**Version:** 1.0 (Iteration 1 of 3)
**Date:** 2026-03-30
**Status:** Draft
**Author:** Product Owner

---

## 1. Problem Statement

Users need to determine whether a person has a GWM client ID. Today this requires
manual queries across two separate database tables in two different schemas, knowledge
of GIN-indexed fuzzy matching syntax, and subjective judgment about whether a candidate
row actually matches the person in question. This process is slow, error-prone, and
inaccessible to non-technical users.

The Client ID Lookup Tool automates this workflow: accept a person's name (with optional
context), search both data sources using fuzzy matching, have the LLM adjudicate
candidates, and return a structured, confidence-scored result.

---

## 2. Data Sources

### 2.1 playbook.fuzzy_client

| Column    | Type | Notes                                  |
|-----------|------|----------------------------------------|
| gwm_id    | TEXT | The GWM client identifier              |
| name      | TEXT | Client full name. GIN-indexed.         |
| companies | TEXT | Associated company names (may be NULL) |

- **Schema:** `playbook`
- **Index:** GIN on `name`
- **Access:** Via existing asyncpg pool (`_acquire()` from `app.db._pool`), search_path already includes `playbook`

### 2.2 galileo.high_priority_queue_client

| Column         | Type | Notes                                                    |
|----------------|------|----------------------------------------------------------|
| entity_id      | TEXT | The GWM ID (when entity_id_type = 'Client')              |
| entity_id_type | TEXT | Filter: must equal `'Client'` for gwm_id resolution      |
| label          | TEXT | Name + short bio. GIN-indexed.                           |

- **Schema:** `galileo` (different schema from the playbook search_path)
- **Index:** GIN on `label`
- **Access:** Requires explicit schema qualification (`galileo.high_priority_queue_client`) since the connection pool's search_path is `playbook, public`
- **Key constraint:** Only rows where `entity_id_type = 'Client'` are relevant; `entity_id` becomes the gwm_id

---

## 3. User Stories

### US-1: Basic Name Lookup

**As a** research analyst,
**I want to** ask "Does John Smith have a client ID?"
**So that** I get back a GWM ID (or a clear "no match") without writing SQL.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | User provides a person name via the chat interface | The agent tool receives the `name` parameter |
| 2 | System searches `playbook.fuzzy_client` using GIN trigram matching on `name` | Query uses `name % $1` or `similarity(name, $1)` with a threshold >= 0.3 |
| 3 | System searches `galileo.high_priority_queue_client` using GIN trigram matching on `label`, filtered to `entity_id_type = 'Client'` | Query uses `label % $1` with the type filter |
| 4 | Both queries run concurrently (asyncio.gather) | Measured latency is not sequential |
| 5 | Candidates from both sources are passed to the LLM for adjudication | LLM prompt includes all candidates with source attribution |
| 6 | If a match exists, the response includes the gwm_id, matched name, source table, and a confidence score (0.0-1.0) | JSON response validated against schema |
| 7 | If no match exists, the response states "no match found" with an explanation of what was searched | Explanation references both tables |
| 8 | Response completes within 5 seconds for a single lookup (DB queries + LLM) | p95 latency under 5s |
| 9 | The tool is registered in `TOOL_REGISTRY` and available to the research agent via function calling | `get_openai_tools()` includes the new tool schema |

### US-2: Lookup with Company/Context

**As a** research analyst,
**I want to** ask "Does John Smith at Acme Corp have a client ID?"
**So that** I can disambiguate common names using company affiliation.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | User provides a name AND optional company/context string | Tool schema has optional `company` and `context` parameters |
| 2 | For `fuzzy_client`, company is used as a secondary filter: candidates whose `companies` field matches the provided company are ranked higher | LLM prompt explicitly instructs prioritization of company-matching candidates |
| 3 | For `high_priority_queue_client`, the `label` field (which contains bio text) is searched for both name AND company keywords | Query includes company in the search predicate |
| 4 | LLM adjudication considers the company context when deciding between multiple candidates | LLM system prompt includes explicit instruction to weigh company match |
| 5 | When company context resolves an otherwise-ambiguous match, the response notes this | Response JSON includes a `resolution_factors` array |
| 6 | When company context contradicts all candidates, the response says "no match" rather than forcing a weak match | Confidence threshold of 0.5 enforced -- below that, report no match |

### US-3: Bulk Lookup

**As a** research analyst,
**I want to** submit a list of names (up to 50) for batch client ID resolution
**So that** I can process an entire roster without making 50 individual requests.

#### Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | User submits a JSON array of lookup requests, each with `name` and optional `company`/`context` | POST body validated via Pydantic model |
| 2 | System processes lookups concurrently with bounded parallelism (max 10 concurrent) | Uses `asyncio.Semaphore(10)` |
| 3 | Maximum batch size is 50 items | Pydantic validator enforces `max_length=50` |
| 4 | Each item in the response array matches the single-lookup response schema | Same `LookupResult` model for single and bulk |
| 5 | Partial failures do not abort the entire batch; failed items get an error field | Response includes per-item `error` field (null on success) |
| 6 | Bulk endpoint returns within 30 seconds for a 50-item batch | p95 latency under 30s |
| 7 | Response includes a summary: total requested, matched, unmatched, errored | Top-level `summary` object in response |

---

## 4. Scope

### 4.1 In Scope (V1)

- **Agent tool registration:** New tool `lookup_client_id` in `backend/app/agent/tools.py` following the `@_register` decorator pattern
- **Database query module:** New file `backend/app/db/client_lookup.py` with two functions:
  - `db_search_fuzzy_client(name, company=None, limit=10)` -- queries `playbook.fuzzy_client`
  - `db_search_hpq_client(name, company=None, limit=10)` -- queries `galileo.high_priority_queue_client`
- **LLM adjudication:** Within the tool function, call OpenAI to evaluate candidates and determine best match
- **REST API endpoint:** `POST /api/client-lookup` for direct API access (bypassing the agent)
- **Bulk REST endpoint:** `POST /api/client-lookup/bulk` for batch processing
- **Structured response format:** JSON with gwm_id, confidence, source, explanation
- **Authentication:** All endpoints require JWT auth via existing `get_current_user` dependency
- **Unit tests:** Full coverage of DB query functions, LLM adjudication logic, edge cases
- **Integration tests:** End-to-end tests with test data in both tables

### 4.2 Out of Scope (V1)

- **Frontend UI:** No dedicated lookup page in SvelteKit. Users interact via the chat agent or direct API calls. Frontend will be V2.
- **Caching/memoization:** No Redis caching of lookup results. Can be added in V2 if latency is a concern.
- **Audit logging:** No persistent log of who looked up which client ID. Planned for V2.
- **Write-back:** No ability to create or update client records. Read-only.
- **Cross-reference with `playbook.entities`:** The existing entities table has a `gwm_id` column, but V1 does not cross-reference or auto-populate it. V2 may link lookups to campaign entities.
- **Rate limiting:** No per-user rate limits beyond existing API middleware. V2 if needed.
- **Galileo schema management:** We treat `galileo.high_priority_queue_client` as a read-only external table. We do not own its schema or indexes.

---

## 5. Edge Cases

### 5.1 No Match in Either Table

**Scenario:** User asks about "Zygmunt Brzezinski III" and neither table has a match.

**Expected behavior:**
- Both queries return empty result sets
- Tool returns `match_found: false` with explanation: "No candidates found in either the client directory or the priority queue. Searched for: 'Zygmunt Brzezinski III'."
- No LLM call is made (skip adjudication when zero candidates)

### 5.2 Multiple Strong Matches (Ambiguous)

**Scenario:** User asks about "James Johnson" and there are 5+ candidates across both tables.

**Expected behavior:**
- All candidates (up to the limit) are passed to the LLM
- If the LLM cannot determine a single best match with confidence >= 0.7, return `match_found: false` with `ambiguous: true`
- Response includes `candidates` array with up to 5 best candidates, each with their gwm_id, name, source, and similarity score
- Explanation: "Multiple potential matches found. Please provide additional context (company, title, or other identifying information) to narrow the result."

### 5.3 Match in One Table Only

**Scenario:** Name appears in `fuzzy_client` but not `high_priority_queue_client` (or vice versa).

**Expected behavior:**
- LLM adjudicates based on available candidates from the one source
- Response includes `source: "fuzzy_client"` or `source: "high_priority_queue_client"` to indicate provenance
- Confidence may be lower since there is no cross-table corroboration

### 5.4 Match in Both Tables with Conflicting gwm_ids

**Scenario:** "John Smith" exists in both tables but with different gwm_ids.

**Expected behavior:**
- LLM is explicitly instructed to flag conflicts
- Response includes `conflict: true` with both gwm_ids listed
- Confidence is capped at 0.5 for conflicting results
- Explanation clearly states the conflict and recommends manual verification

### 5.5 Name Variations (Nicknames, Initials, Prefixes)

**Scenario:** User asks about "Bob Smith" but the database has "Robert Smith" or "R. Smith".

**Expected behavior:**
- GIN trigram matching handles partial overlap (Bob/Robert share little trigram similarity)
- The LLM system prompt explicitly instructs: "Consider that Bob = Robert, Bill = William, Dick = Richard, etc. Also consider that initials like 'R. Smith' may match 'Robert Smith'."
- Lower similarity threshold (0.2) for trigram queries to catch these cases, with LLM doing the heavy lifting on relevance

### 5.6 Empty Tables / Database Down

**Scenario:** One or both tables are empty, or the database connection fails.

**Expected behavior:**
- If one table query fails but the other succeeds, return results from the working source with a warning
- If both queries fail, return a structured error: `{"error": "database_unavailable", "message": "Unable to query client databases. Please try again later."}`
- If tables exist but are empty, treat as "no match" (not an error)

### 5.7 LLM Timeout or Failure

**Scenario:** OpenAI API is slow or returns an error during adjudication.

**Expected behavior:**
- 15-second timeout on the LLM call
- On timeout/error, fall back to a rule-based ranking: return the candidate with the highest trigram similarity score, with `adjudication: "rule_based"` (rather than `adjudication: "llm"`) and a note that LLM adjudication was unavailable
- Confidence is capped at 0.6 for rule-based results

### 5.8 SQL Injection / Malicious Input

**Scenario:** User provides `'; DROP TABLE fuzzy_client; --` as the name.

**Expected behavior:**
- All queries use asyncpg parameterized queries ($1, $2...) -- no string interpolation
- Input is stripped of leading/trailing whitespace but otherwise passed as-is to the parameterized query
- The GIN index handles the special characters safely

---

## 6. Success Metrics

### 6.1 Accuracy

| Metric | Target | Measurement |
|--------|--------|-------------|
| True positive rate | >= 90% | Against a labeled test set of 100 known name-to-gwm_id pairs |
| False positive rate | <= 5% | LLM incorrectly assigns a gwm_id to the wrong person |
| Ambiguity detection rate | >= 85% | System correctly flags ambiguous cases rather than guessing |

### 6.2 Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Single lookup p50 latency | < 2 seconds | End-to-end including DB + LLM |
| Single lookup p95 latency | < 5 seconds | End-to-end including DB + LLM |
| Bulk lookup (50 items) p95 | < 30 seconds | End-to-end |
| DB query time (per table) | < 200ms | Isolated DB query without LLM |

### 6.3 Reliability

| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.5% | Uptime excluding planned DB maintenance |
| Graceful degradation rate | 100% | When LLM fails, rule-based fallback always returns a result |
| Zero unhandled exceptions | 0 in production | Error monitoring alerts |

### 6.4 Usage (post-launch tracking)

| Metric | Purpose |
|--------|---------|
| Lookups per day | Adoption signal |
| Bulk vs single ratio | Informs optimization priority |
| Match rate | Data quality signal -- if match rate is very low, data may be stale |
| Average confidence score | LLM calibration signal |

---

## 7. API Contract

### 7.1 Single Lookup

```
POST /api/client-lookup
Content-Type: application/json
Cookie: jwt=<token>

{
  "name": "John Smith",
  "company": "Acme Corporation",   // optional
  "context": "Managing Director"   // optional, any additional context
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
  "resolution_factors": [
    "Name similarity: 0.88",
    "Company match: Acme Corporation found in companies field",
    "Single strong candidate in fuzzy_client"
  ],
  "conflict": false,
  "candidates_evaluated": 3,
  "search_summary": {
    "fuzzy_client_hits": 2,
    "hpq_client_hits": 1
  }
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
  "adjudication": "llm",
  "resolution_factors": [
    "No candidates exceeded similarity threshold in either source"
  ],
  "conflict": false,
  "ambiguous": false,
  "candidates_evaluated": 0,
  "search_summary": {
    "fuzzy_client_hits": 0,
    "hpq_client_hits": 0
  }
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
  "resolution_factors": [
    "Multiple candidates with similar confidence, cannot determine unique match"
  ],
  "conflict": false,
  "ambiguous": true,
  "candidates": [
    {
      "gwm_id": "GWM-12345",
      "name": "John A. Smith",
      "source": "fuzzy_client",
      "similarity": 0.85,
      "company": "Acme Corporation"
    },
    {
      "gwm_id": "GWM-67890",
      "name": "John B. Smith",
      "source": "high_priority_queue_client",
      "similarity": 0.82,
      "company": null
    }
  ],
  "candidates_evaluated": 5,
  "search_summary": {
    "fuzzy_client_hits": 3,
    "hpq_client_hits": 2
  }
}
```

### 7.2 Bulk Lookup

```
POST /api/client-lookup/bulk
Content-Type: application/json
Cookie: jwt=<token>

{
  "lookups": [
    {"name": "John Smith", "company": "Acme Corp"},
    {"name": "Jane Doe"},
    {"name": "Bob Johnson", "context": "CFO"}
  ]
}
```

**Response:**
```json
{
  "results": [
    {
      "index": 0,
      "input": {"name": "John Smith", "company": "Acme Corp"},
      "match_found": true,
      "gwm_id": "GWM-12345",
      "matched_name": "John A. Smith",
      "source": "fuzzy_client",
      "confidence": 0.92,
      "adjudication": "llm",
      "error": null
    },
    {
      "index": 1,
      "input": {"name": "Jane Doe"},
      "match_found": false,
      "gwm_id": null,
      "matched_name": null,
      "source": null,
      "confidence": 0.0,
      "adjudication": "llm",
      "error": null
    },
    {
      "index": 2,
      "input": {"name": "Bob Johnson", "context": "CFO"},
      "match_found": null,
      "gwm_id": null,
      "matched_name": null,
      "source": null,
      "confidence": null,
      "adjudication": null,
      "error": "LLM adjudication timed out; rule-based fallback returned no strong match"
    }
  ],
  "summary": {
    "total": 3,
    "matched": 1,
    "unmatched": 1,
    "errored": 1
  }
}
```

### 7.3 Agent Tool Schema (OpenAI Function Calling)

```json
{
  "type": "function",
  "function": {
    "name": "lookup_client_id",
    "description": "Look up whether a person has a GWM client ID by searching the client directory and priority queue. Provide the person's name and optionally their company or other context to disambiguate common names. Returns the gwm_id if found, or reports no match with an explanation.",
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

## 8. Error Handling

### 8.1 Error Response Format

All errors follow the same JSON structure:

```json
{
  "error": "<error_code>",
  "message": "<human-readable description>",
  "details": {}
}
```

### 8.2 Error Catalog

| HTTP Status | Error Code | Trigger | Response |
|-------------|-----------|---------|----------|
| 400 | `invalid_input` | Name is empty, blank, or exceeds 200 characters | `{"error": "invalid_input", "message": "Name must be between 1 and 200 characters."}` |
| 400 | `batch_too_large` | Bulk request exceeds 50 items | `{"error": "batch_too_large", "message": "Maximum 50 lookups per batch. Received: 75."}` |
| 401 | `unauthorized` | Missing or invalid JWT | Standard FastAPI 401 |
| 503 | `database_unavailable` | Both DB queries fail (connection error, timeout) | `{"error": "database_unavailable", "message": "Unable to query client databases. Please try again later."}` |
| 503 | `partial_database_failure` | One table query fails, other succeeds | 200 with results from working source + `warnings` array in response |
| 504 | `llm_timeout` | OpenAI call exceeds 15s timeout | Falls back to rule-based; only returns 504 if rule-based also fails (should not happen) |
| 500 | `internal_error` | Unexpected exception | `{"error": "internal_error", "message": "An unexpected error occurred."}` |

### 8.3 Graceful Degradation Matrix

| Failure Mode | Behavior |
|-------------|----------|
| `fuzzy_client` query fails | Search `hpq_client` only; add warning to response |
| `hpq_client` query fails | Search `fuzzy_client` only; add warning to response |
| Both queries fail | Return 503 `database_unavailable` |
| Both queries return empty | Return `match_found: false` (this is normal, not an error) |
| LLM call fails | Fall back to rule-based ranking by trigram similarity; cap confidence at 0.6; set `adjudication: "rule_based"` |
| LLM returns unparseable JSON | Fall back to rule-based ranking (same as LLM failure) |
| DB query takes > 5s | Query timeout; treat as query failure; trigger graceful degradation |

---

## 9. Technical Architecture (Implementation Guidance)

### 9.1 New Files

| File | Purpose |
|------|---------|
| `backend/app/db/client_lookup.py` | DB query functions for both tables |
| `backend/app/routers/client_lookup.py` | REST API endpoints (single + bulk) |
| `backend/tests/test_client_lookup_unit.py` | Unit tests for DB functions and adjudication logic |
| `backend/tests/test_client_lookup_integration.py` | Integration tests with test data |

### 9.2 Modified Files

| File | Change |
|------|--------|
| `backend/app/agent/tools.py` | Add `lookup_client_id` tool registration |
| `backend/app/db/__init__.py` | Export new DB functions |
| `backend/app/main.py` | Register `client_lookup_router` |

### 9.3 Key Design Decisions

1. **GIN trigram vs. full-text search:** Use `pg_trgm` trigram similarity (`%` operator and `similarity()` function) rather than `tsvector` full-text search. Names are short strings where trigram matching excels; full-text search is designed for documents. The GIN indexes on these tables already support trigram operations.

2. **Schema qualification for galileo:** The connection pool sets `search_path TO playbook, public`. Since `galileo` is not in the search path, all queries against `high_priority_queue_client` must use fully qualified names: `galileo.high_priority_queue_client`.

3. **LLM as adjudicator, not searcher:** The LLM does not generate SQL or decide what to search. It receives a structured list of candidates from both tables and makes a match/no-match decision. This keeps the LLM's role bounded and deterministic.

4. **Separate REST endpoints from agent tool:** The tool (`lookup_client_id`) is for the agent's function-calling loop. The REST endpoints (`/api/client-lookup`) are for direct programmatic access. Both share the same core logic in `client_lookup.py`.

5. **Connection reuse:** Both DB queries go through the existing `_acquire()` context manager from `app.db._pool`, ensuring connection pooling, auth-error recovery, and proper search_path configuration.

---

## 10. Open Questions for Iteration 2

1. **GIN index type confirmation:** Are the GIN indexes on `fuzzy_client.name` and `hpq_client.label` trigram-type (`gin_trgm_ops`) or full-text (`tsvector`)? This determines whether we use `%`/`similarity()` or `@@`/`to_tsquery()`. Need DBA confirmation.

2. **Galileo schema permissions:** Does the application's database role have SELECT access to `galileo.high_priority_queue_client`? Need ops confirmation.

3. **Data freshness:** How often are these tables updated? Is there a risk of stale data leading to missed matches?

4. **Nickname mapping:** Should we maintain a static lookup table of common nicknames (Bob/Robert, Bill/William) to expand search queries, or rely entirely on the LLM's knowledge?

5. **Usage analytics:** Should we log every lookup to a dedicated analytics table for tracking match rates and data quality metrics?

---

## Appendix A: LLM Adjudication Prompt (Draft)

```
You are a name-matching specialist. Given a search query and a list of candidates from
two data sources, determine if any candidate is the same person as the query.

SEARCH QUERY:
- Name: {{name}}
- Company: {{company or "not provided"}}
- Additional context: {{context or "none"}}

CANDIDATES FROM CLIENT DIRECTORY (playbook.fuzzy_client):
{{for candidate in fuzzy_candidates}}
- gwm_id: {{candidate.gwm_id}}, name: {{candidate.name}}, companies: {{candidate.companies}}, similarity: {{candidate.similarity}}
{{endfor}}

CANDIDATES FROM PRIORITY QUEUE (galileo.high_priority_queue_client):
{{for candidate in hpq_candidates}}
- gwm_id: {{candidate.entity_id}}, label: {{candidate.label}}, similarity: {{candidate.similarity}}
{{endfor}}

RULES:
1. Consider common name variations: Bob = Robert, Bill = William, Dick = Richard,
   Jim = James, etc. Also consider that initials (R. Smith) may match full names.
2. Company match is a strong signal but not required.
3. If a candidate appears in BOTH sources with the SAME gwm_id, that is very strong
   evidence of a match.
4. If candidates from different sources have DIFFERENT gwm_ids for what appears to be
   the same person, flag this as a conflict.
5. If multiple candidates are plausible and you cannot confidently select one, report
   ambiguity rather than guessing.

Respond with ONLY valid JSON:
{
  "match_found": true/false,
  "gwm_id": "the gwm_id or null",
  "matched_name": "the matched candidate's name or null",
  "source": "fuzzy_client" or "high_priority_queue_client" or null,
  "confidence": 0.0 to 1.0,
  "conflict": true/false,
  "ambiguous": true/false,
  "resolution_factors": ["reason 1", "reason 2"],
  "candidates_considered": number
}
```

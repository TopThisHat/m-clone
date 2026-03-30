## 1. P0: Dependencies & Schema Setup

- [ ] 1.1 Add `python-Levenshtein` to backend dependencies via `uv add python-Levenshtein`
- [ ] 1.2 Add GIN trigram index verification in `backend/app/db/_schema.py` for `playbook.fuzzy_client.name` and `galileo.high_priority_queue_client.label` (CREATE INDEX IF NOT EXISTS)
- [ ] 1.3 Verify pg_trgm extension is database-wide (covers galileo schema)
- [ ] 1.4 Verify DB role has SELECT on `galileo.high_priority_queue_client`
- [ ] 1.5 Verify `playbook.fuzzy_client` table structure: confirm column types for `gwm_id`, `name`, `companies` (text vs text[] vs jsonb)

## 2. P0: Pydantic Models

- [ ] 2.1 Create `backend/app/models/client_lookup.py` with `ClientLookupRequest` (name: str, company: str | None)
- [ ] 2.2 Add `Confidence` enum (high, medium, low, no_match) and `CandidateSource` enum (fuzzy_client, queue)
- [ ] 2.3 Add `ClientCandidate` model (name, gwm_id, entity_id, company, similarity, source)
- [ ] 2.4 Add `ClientMatch` model (name, gwm_id, entity_id, company, confidence, source, reasoning)
- [ ] 2.5 Add `ClientLookupResponse` model (match, alternatives, needs_disambiguation, conflict_gwm_ids, query_name, query_company, resolution_method)

## 3. P0: Database Query Layer

- [ ] 3.1 Create `backend/app/db/client_lookup.py` with `normalize_name()` function (strip honorifics: Mr., Mrs., Dr., Jr., Sr., etc.)
- [ ] 3.2 Add `parse_queue_label()` function (regex parse "Last, First" and "Last, First - Company" patterns from queue label)
- [ ] 3.3 Implement `search_fuzzy_client()`: SET LOCAL pg_trgm.similarity_threshold inside transaction, query with `LOWER(name) % LOWER($1)`, score with `similarity()`, company boost in ORDER BY (not WHERE filter)
- [ ] 3.4 Implement `search_queue_client()`: SET LOCAL pg_trgm.word_similarity_threshold inside transaction, fully-qualified `galileo.high_priority_queue_client`, filter `entity_id_type = 'Client'`, query with `LOWER(label) %> LOWER($1)`, score with `word_similarity()`
- [ ] 3.5 Update `backend/app/db/__init__.py` to re-export `search_fuzzy_client`, `search_queue_client`, `normalize_name`, `parse_queue_label`

## 4. P0: LLM Resolver & Orchestration

- [ ] 4.1 Create `backend/app/agent/client_resolver.py` with LLM system prompt (identity resolution rules, confidence definitions, JSON output schema)
- [ ] 4.2 Implement `_build_user_prompt()` to format query + numbered candidates for LLM
- [ ] 4.3 Implement `_dedup_candidates()`: merge results from both tables, dedup by (normalized_name, company), keep highest similarity, cap at 10
- [ ] 4.4 Implement `_detect_gwm_id_conflicts()`: detect when same name maps to multiple gwm_ids
- [ ] 4.5 Implement `_fast_path()`: skip LLM when single candidate with gwm_id and similarity >= 0.85 (fuzzy_client) or >= 0.75 (queue), with company guard (never fast-path when company provided)
- [ ] 4.6 Implement `_call_llm()`: call gpt-4o-mini with temperature=0.0, response_format=json_object, parse structured output
- [ ] 4.7 Implement `_parse_llm_response()`: parse LLM JSON, cap confidence at "medium" when gwm_id conflicts exist, force needs_disambiguation on conflicts
- [ ] 4.8 Implement `_levenshtein_fallback()`: deterministic Levenshtein ratio scoring when LLM fails, with company boost and appropriate confidence levels
- [ ] 4.9 Implement `resolve_client()`: main entry point orchestrating normalize -> parallel DB queries -> merge -> dedup -> fast-path check -> LLM with fallback -> response assembly

## 5. P0: Agent Tool Registration

- [ ] 5.1 Add `lookup_client` tool to `backend/app/agent/tools.py` using `@_register` decorator with name, company parameters
- [ ] 5.2 Tool function calls `resolve_client()` and formats result as markdown string for agent consumption

## 6. P1: REST API Endpoint

- [ ] 6.1 Create `backend/app/routers/client_lookup.py` with POST `/api/client-lookup` endpoint, auth via `get_current_user`
- [ ] 6.2 Wire router in `backend/app/main.py` via `app.include_router()`

## 7. P1: Unit Tests

- [ ] 7.1 Create `backend/tests/test_client_lookup_unit.py`
- [ ] 7.2 Test `normalize_name()`: strips "Mr.", "Dr.", "Jr.", etc., handles empty/whitespace input
- [ ] 7.3 Test `parse_queue_label()`: "Last, First", "Last, First - Company", plain "First Last", edge cases
- [ ] 7.4 Test `_dedup_candidates()`: keeps highest similarity, respects 10-candidate cap, handles empty input
- [ ] 7.5 Test `_detect_gwm_id_conflicts()`: identifies conflicting gwm_ids, handles no conflicts
- [ ] 7.6 Test `_fast_path()`: returns match when conditions met, returns None when company provided, returns None when multiple candidates, respects threshold per source
- [ ] 7.7 Test `_levenshtein_fallback()`: ranks by Levenshtein ratio, applies company boost, caps confidence on conflicts
- [ ] 7.8 Test `_parse_llm_response()`: handles null match, alternatives, caps confidence on conflicts, forces disambiguation on conflicts
- [ ] 7.9 Test LLM call mock: successful resolution, timeout returns fallback, unparseable JSON returns fallback, invalid candidate index handled

## 8. P1: Integration Tests

- [ ] 8.1 Create `backend/tests/test_client_lookup_integration.py`
- [ ] 8.2 Test `search_fuzzy_client()` with seeded test data: exact match, partial match, no match, company boost
- [ ] 8.3 Test `search_queue_client()` with seeded test data: name within bio, entity_id_type filter
- [ ] 8.4 Test SET LOCAL threshold scoping: verify threshold doesn't leak to other queries
- [ ] 8.5 Test `resolve_client()` full flow with mocked LLM: DB query -> dedup -> LLM -> response
- [ ] 8.6 Test `resolve_client()` with LLM failure: verify Levenshtein fallback activates

## 9. P2: E2E Tests

- [ ] 9.1 Create `backend/tests/test_client_lookup_e2e.py`
- [ ] 9.2 Test POST /api/client-lookup returns 200 with valid response shape
- [ ] 9.3 Test POST returns 401 without JWT auth
- [ ] 9.4 Test POST returns 422 with empty name
- [ ] 9.5 Test full round-trip with mocked DB + LLM

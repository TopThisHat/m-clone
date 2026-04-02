## Sprint 1: Foundation (Configuration + Tool Implementation)

### 1. P0: Configuration & Feature Gate
- [ ] 1.1 Add `talktome_api_url: str = ""`, `talktome_api_key: str = ""`, `talktome_timeout_seconds: float = 30.0`, `talktome_max_concurrency: int = 5` to `Settings` class in `backend/app/config.py`
- [ ] 1.2 Add `TALKTOME_API_URL`, `TALKTOME_API_KEY`, `TALKTOME_TIMEOUT_SECONDS`, `TALKTOME_MAX_CONCURRENCY` to `backend/.env.example` with documentation comments
- [ ] 1.3 Implement feature gate: tool returns "TalkToMe is not configured" when `talktome_api_url` is empty

### 2. P0: Tool Implementation
- [ ] 2.1 Add `talk_to_me` tool to `backend/app/agent/tools.py` with `@_register` decorator — schema: `question` (required str), `gwm_id` (required str), `client_name` (required str)
- [ ] 2.2 Implement parameter validation: reject empty `question`, empty `gwm_id`, empty `client_name`
- [ ] 2.3 Implement cache check/store using `deps.tool_cache` with key `("talk_to_me", gwm_id, question.strip().lower())`
- [ ] 2.4 Implement HTTP POST to TalkToMe API via `httpx.AsyncClient` with configurable timeout — payload: `{"question": str, "id": uuid4(), "context": {"client_id": gwm_id}}`
- [ ] 2.5 Implement Bearer token auth header from `settings.talktome_api_key`
- [ ] 2.6 Implement response parsing: extract `summary` field, handle empty/missing summary
- [ ] 2.7 Implement response formatting: `**TalkToMe Insight** (client: {client_name})\n\n{summary}`

### 3. P0: Error Handling & Resilience
- [ ] 3.1 Implement error handlers for: timeout, 401/403, 404, 429, 5xx, connection error, malformed response — each returns a user-friendly string (never raises)
- [ ] 3.2 Implement single retry with 2s delay for 502/503 status codes only
- [ ] 3.3 Implement `asyncio.Semaphore` concurrency cap (lazy init from `settings.talktome_max_concurrency`, default 5)
- [ ] 3.4 Implement structured logging: INFO for request/success, WARNING for retry/feature-gate, ERROR for failures — correlation_id on all log lines, no PII in response bodies

## Sprint 2: Agent Integration (System Prompt + Orchestration)

### 4. P0: System Prompt Updates
- [ ] 4.1 Add `talk_to_me` to the tool listing section in `SYSTEM_PROMPT` in `backend/app/agent/agent.py`
- [ ] 4.2 Add "TalkToMe Client Queries" section to `SYSTEM_PROMPT` with chaining rules: require gwm_id, call lookup_client first, handle no-match/ambiguity, handle unspecified-client, multi-client parallel resolution
- [ ] 4.3 Add instruction to always display `client_name` (not raw gwm_id) in agent responses

### 5. P1: Prompt Regression Validation
- [ ] 5.1 Verify agent correctly chains `lookup_client` → `talk_to_me` when user provides a name (manual test with mock API)
- [ ] 5.2 Verify agent asks for clarification when `lookup_client` returns ambiguous/no-match
- [ ] 5.3 Verify agent asks user to specify a client when no client named in query
- [ ] 5.4 Verify agent resolves multiple clients in parallel for multi-client queries

## Sprint 3: Testing (Unit + Integration + Security)

### 6. P0: Security Tests
- [ ] 6.1 Test API key not leaked in error messages or return values
- [ ] 6.2 Test PII not logged at INFO level or above (capture log output, verify no response bodies)
- [ ] 6.3 Test injection via question parameter (SQL, prompt injection) — verify passed as-is in JSON body
- [ ] 6.4 Test API key not present in exception traces

### 7. P0: Unit Tests — Error Paths
- [ ] 7.1 Create `backend/tests/test_talk_to_me.py` with test fixtures
- [ ] 7.2 Test empty question rejected (no API call)
- [ ] 7.3 Test empty gwm_id rejected (no API call)
- [ ] 7.4 Test whitespace-only inputs rejected
- [ ] 7.5 Test feature gate: returns config error when `talktome_api_url` empty
- [ ] 7.6 Test HTTP timeout returns friendly message
- [ ] 7.7 Test HTTP 401/403 returns auth failure message
- [ ] 7.8 Test HTTP 404 returns not-found message with client_name
- [ ] 7.9 Test HTTP 429 returns rate-limit message
- [ ] 7.10 Test HTTP 500 returns service error message
- [ ] 7.11 Test HTTP 502/503 triggers retry then returns error if retry also fails
- [ ] 7.12 Test connection error returns network message
- [ ] 7.13 Test malformed response (missing summary key) handled
- [ ] 7.14 Test malformed response (non-JSON body) handled

### 8. P0: Unit Tests — Happy Paths
- [ ] 8.1 Test successful API call returns formatted summary with client_name
- [ ] 8.2 Test cache hit returns cached result without API call
- [ ] 8.3 Test case-insensitive cache hit (different question casing)
- [ ] 8.4 Test cache populated after successful API call
- [ ] 8.5 Test payload structure matches API contract: `{"question", "id", "context": {"client_id"}}`
- [ ] 8.6 Test Bearer token header sent when `talktome_api_key` configured
- [ ] 8.7 Test no auth header when `talktome_api_key` empty
- [ ] 8.8 Test empty summary returns "no interactions found" message
- [ ] 8.9 Test 502 retry succeeds on second attempt

### 9. P1: Integration Tests
- [ ] 9.1 Create `backend/tests/test_talk_to_me_integration.py` with `@pytest.mark.integration` marker
- [ ] 9.2 Test agent selects `talk_to_me` for meeting note queries (mock execute_tool, verify call sequence)
- [ ] 9.3 Test agent chains `lookup_client` → `talk_to_me` when no gwm_id (verify ordered tool calls)
- [ ] 9.4 Test agent asks clarification on ambiguous client (verify no `talk_to_me` call)
- [ ] 9.5 Test agent uses cache on repeated query (verify API called once for two identical questions)
- [ ] 9.6 Test agent combines `talk_to_me` with other tools (web_search + talk_to_me in parallel)

### 10. P2: Edge Case Tests
- [ ] 10.1 Test very long question (10,000 chars) — verify graceful handling
- [ ] 10.2 Test special characters in question (unicode, newlines, HTML tags)
- [ ] 10.3 Test concurrent calls for different clients (5 parallel, verify no cross-contamination)
- [ ] 10.4 Test semaphore backpressure (6+ concurrent calls, verify all complete)
- [ ] 10.5 Test DNS resolution failure handled gracefully

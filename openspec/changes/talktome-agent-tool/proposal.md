## Why

Research analysts currently have no access to client interaction history (meeting notes, call transcripts, follow-up summaries) within the Playbook Research platform. They must leave the platform, open TalkToMe separately, search manually, and copy-paste context back. This context switch costs time, breaks research flow, and risks missed information. Integrating TalkToMe as an agent tool brings client interaction intelligence directly into the research loop.

## What Changes

- **New agent tool** (`talk_to_me` in `backend/app/agent/tools.py`): Registered via existing `@_register` decorator. Calls the TalkToMe external API to retrieve client interaction summaries. Requires a resolved `gwm_id` (Approach B — agent chains `lookup_client` first).
- **New config settings** (`backend/app/config.py`): `TALKTOME_API_URL`, `TALKTOME_API_KEY`, `TALKTOME_TIMEOUT_SECONDS`, `TALKTOME_MAX_CONCURRENCY`
- **System prompt update** (`backend/app/agent/agent.py`): New "TalkToMe Client Queries" section instructing the agent on tool chaining, disambiguation, and unspecified-client handling
- **Environment template** (`backend/.env.example`): New env vars documented

## Capabilities

### New Capabilities
- `talktome-query`: Query a client's meeting notes, call transcripts, and interaction records via the TalkToMe API using natural language questions
- `talktome-agent-chaining`: Agent automatically resolves client names to gwm_id via `lookup_client` before querying TalkToMe
- `talktome-disambiguation`: Agent handles ambiguous/no-match client lookups by asking user for clarification before querying

### Modified Capabilities
- `agent-tools`: Extended with new `talk_to_me` tool in the registry
- `agent-system-prompt`: Updated with TalkToMe query instructions and tool listing

## Impact

- **backend/app/config.py** -- modified: add TalkToMe settings (URL, API key, timeout, concurrency)
- **backend/app/agent/tools.py** -- modified: add `talk_to_me` tool with `@_register` decorator
- **backend/app/agent/agent.py** -- modified: update SYSTEM_PROMPT with TalkToMe instructions and tool listing
- **backend/.env.example** -- modified: add TalkToMe env vars
- **backend/tests/test_talk_to_me.py** -- new: unit tests (parameter validation, caching, HTTP mocking, error handling)
- **backend/tests/test_talk_to_me_integration.py** -- new: integration tests (agent orchestration, tool chaining)

## Design Decisions

### Approach B: gwm_id required (agent chains lookup_client first)
- Separation of concerns — each tool does one thing
- Reuses existing client resolution pipeline without duplication
- Agent already knows how to chain `lookup_client` (battle-tested pattern)
- Resolved gwm_id is reusable across multiple `talk_to_me` calls in a session
- Two-call latency cost is negligible (~200ms-2s for lookup)

### Key Design Details
- **Parameters**: `gwm_id` (required), `client_name` (required for display), `question` (required)
- **Payload**: `{"question": str, "id": uuid4(), "context": {"client_id": gwm_id}}`
- **Response**: `{"summary": str}`
- **Timeout**: 30s default, configurable via `TALKTOME_TIMEOUT_SECONDS`
- **Retries**: Single retry with 2s delay for 502/503 only
- **Caching**: Session-scoped via `deps.tool_cache`, key: `("talk_to_me", gwm_id, question.lower())`
- **Concurrency**: `asyncio.Semaphore` from `TALKTOME_MAX_CONCURRENCY` (default 5)
- **Feature gate**: Returns early with clear message if `TALKTOME_API_URL` not set
- **Logging**: Structured — INFO for requests/responses (no PII in bodies), WARNING for retries, ERROR for failures
- **`id` field**: Per-request UUID correlation ID for end-to-end tracing

## Open Questions

1. TalkToMe API endpoint path — is it `/query`, `/ask`, or something else?
2. Does TalkToMe enforce per-analyst access control?
3. Rate limits and quotas on the TalkToMe API?
4. Can TalkToMe return structured data (dates, attendees) beyond `summary`?
5. Is a sandbox/mock TalkToMe available for dev/UAT?
6. Should TalkToMe results appear in the "Sources" section of research reports?
7. Data retention — should TalkToMe responses be persisted in session history?

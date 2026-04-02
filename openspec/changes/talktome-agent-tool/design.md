# Technical Design: TalkToMe Agent Tool

## Architecture

```
User: "What did we discuss with Robert Kraft in the last meeting?"
  │
  ▼
Agent (ResearchOrchestrator)
  │
  ├── Step 1: lookup_client(name="Robert Kraft")
  │   └── Returns: LookupResult(match_found=True, gwm_id="GWM-ABC123", matched_name="Robert Kraft")
  │
  ├── Step 2: talk_to_me(question="...", gwm_id="GWM-ABC123", client_name="Robert Kraft")
  │   ├── Feature gate check (TALKTOME_API_URL set?)
  │   ├── Cache check (deps.tool_cache)
  │   ├── Semaphore acquire (concurrency cap)
  │   ├── HTTP POST to TalkToMe API (with retry for 502/503)
  │   ├── Response parsing + formatting
  │   └── Cache store
  │
  └── Step 3: Format research response with TalkToMe insight
```

## Tool Registration Schema

```python
@_register(
    "talk_to_me",
    "Query the TalkToMe API for client interaction history (meeting notes, call "
    "transcripts). Requires a resolved gwm_id — call lookup_client first if you "
    "only have a name. Returns a summary of relevant interactions.",
    {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Natural language question about client interactions"
            },
            "gwm_id": {
                "type": "string",
                "description": "GWM client ID from lookup_client"
            },
            "client_name": {
                "type": "string",
                "description": "Human-readable client name from lookup_client (for display)"
            }
        },
        "required": ["question", "gwm_id", "client_name"]
    }
)
```

## Configuration

```python
# backend/app/config.py — additions to Settings class
talktome_api_url: str = ""              # TalkToMe API base URL
talktome_api_key: str = ""              # Bearer token for auth
talktome_timeout_seconds: float = 30.0  # HTTP timeout
talktome_max_concurrency: int = 5       # Max parallel requests per process
```

## Implementation Pattern

```python
async def talk_to_me(deps, *, question, gwm_id, client_name) -> str:
    # 1. Validate: non-empty question and gwm_id
    # 2. Feature gate: return early if talktome_api_url not configured
    # 3. Cache check: ("talk_to_me", gwm_id, question.lower())
    # 4. Build payload: {"question": str, "id": uuid4(), "context": {"client_id": gwm_id}}
    # 5. Acquire semaphore (concurrency cap)
    # 6. HTTP POST with retry loop (max 1 retry for 502/503, 2s delay)
    # 7. Handle errors: timeout, 401/403, 404, 429, 5xx, connection error
    # 8. Parse response: extract "summary" field
    # 9. Format: "**TalkToMe Insight** (client: {client_name})\n\n{summary}"
    # 10. Cache result and return
```

## System Prompt Addition

```text
## TalkToMe Client Queries

- **talk_to_me** — query a client's interaction history (requires gwm_id from lookup_client)

When the user asks about a client's meeting notes, call transcripts, or interactions:

1. You MUST have a valid gwm_id before calling talk_to_me.
2. If the user provides a name but no gwm_id, call lookup_client first.
   The resolver enforces a minimum confidence threshold internally; if match
   quality is too low, match_found will be False.
3. If lookup_client returns no match or ambiguity, tell the user and ask
   for clarification. Do NOT call talk_to_me.
4. If the user asks about interactions without naming a client, ask them
   to specify which client. talk_to_me requires a resolved client.
5. For multi-client queries, resolve each client in parallel then call
   talk_to_me for each in parallel.
6. Always display client_name in responses, never raw gwm_id.
```

## Error Handling Matrix

| Scenario | Behavior | User Message |
|----------|----------|--------------|
| Empty gwm_id | Validate early, no API call | "A valid GWM client ID is required." |
| URL not configured | Feature gate, no API call | "TalkToMe is not configured." |
| HTTP 401/403 | Log ERROR, no retry | "Authentication failed." |
| HTTP 404 | Return info message | "No interactions found for {client_name}." |
| HTTP 429 | Log WARNING, no retry | "Rate limited. Try again shortly." |
| HTTP 502/503 | Retry once after 2s | If retry fails: "Service temporarily unavailable." |
| Other 5xx | Log ERROR, no retry | "Service error. Try again later." |
| Timeout | Log ERROR, no retry | "Timed out after {N} seconds." |
| Connection error | Log ERROR | "Service unreachable." |
| Empty/missing summary | Log WARNING | "No relevant interactions found." |
| Malformed response | Log WARNING | "Unexpected response format." |

## Concurrency

Module-level `asyncio.Semaphore` initialized lazily from `settings.talktome_max_concurrency`. Scope: per-process. Additional calls await on the semaphore (backpressure, no error).

## Logging Specification

| Level | Event | Fields |
|-------|-------|--------|
| INFO | Request initiated | correlation_id, gwm_id, client_name |
| INFO | Success | correlation_id, attempt |
| WARNING | Retry (502/503) | correlation_id, status_code, attempt |
| WARNING | Feature gate | — |
| ERROR | Timeout | correlation_id, attempt |
| ERROR | HTTP error | correlation_id, status_code |
| ERROR | Connection error | correlation_id |

Response bodies are never logged (PII risk).

## Caching

- Scope: per-session (`deps.tool_cache`)
- Key: `("talk_to_me", gwm_id, question.strip().lower())`
- Eviction: none (session-scoped, GC'd on session end)
- Same question + same client = cache hit (case-insensitive on question)

## Security

- API key in env var, never logged or exposed to frontend
- HTTPS only for TalkToMe calls
- No PII in logs (response bodies excluded)
- Input validation: non-empty strings, reasonable length
- Session-scoped cache only (no cross-session persistence of interaction data)

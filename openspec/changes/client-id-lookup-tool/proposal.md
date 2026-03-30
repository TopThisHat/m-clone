## Why

Users need to look up whether a person has a GWM client ID (`gwm_id`) by searching across two internal databases. Currently there is no tool or API for this -- analysts must manually query both `playbook.fuzzy_client` and `galileo.high_priority_queue_client`, interpret fuzzy matches, and cross-reference results. This is slow, error-prone, and blocks the research workflow. An LLM-powered resolution tool will automate this as both an agent tool (conversational) and a direct API endpoint.

## What Changes

- **New DB module** (`backend/app/db/client_lookup.py`): Fuzzy search functions for both tables using pg_trgm `similarity()` (fuzzy_client) and `word_similarity()` (queue table), with name normalization and label parsing
- **New LLM resolver** (`backend/app/agent/client_resolver.py`): Orchestrates parallel DB queries, deduplication, fast-path matching, gpt-4o-mini disambiguation, and Levenshtein fallback when LLM is unavailable
- **New Pydantic models** (`backend/app/models/client_lookup.py`): Request, response, candidate, and match models
- **New agent tool** (`lookup_client` in `backend/app/agent/tools.py`): Registered via existing `@_register` decorator so the research agent can call it conversationally
- **New REST endpoint** (`POST /api/client-lookup`): Direct API for programmatic client lookup with auth
- **Schema migration** (`backend/app/db/_schema.py`): Ensure GIN trigram indexes exist on both tables
- **New dependency**: `python-Levenshtein` for deterministic fallback scoring

## Capabilities

### New Capabilities
- `client-id-lookup`: Resolve a person's name to a gwm_id by fuzzy-searching `playbook.fuzzy_client` and `galileo.high_priority_queue_client`, then using gpt-4o-mini to pick the best match from candidates
- `client-lookup-agent-tool`: Agent tool registration so users can ask "does this person have a client ID?" in conversation
- `client-lookup-api`: Direct POST endpoint for programmatic access

### Modified Capabilities
- `agent-tools`: Extended with new `lookup_client` tool in the registry

## Impact

- **backend/app/db/client_lookup.py** -- new: fuzzy search queries for both tables
- **backend/app/db/__init__.py** -- modified: re-export new db functions
- **backend/app/db/_schema.py** -- modified: add GIN trigram indexes
- **backend/app/models/client_lookup.py** -- new: Pydantic models
- **backend/app/agent/client_resolver.py** -- new: LLM resolver + fallback
- **backend/app/agent/tools.py** -- modified: register `lookup_client` tool
- **backend/app/routers/client_lookup.py** -- new: POST endpoint
- **backend/app/main.py** -- modified: wire new router
- **pyproject.toml** -- modified: add python-Levenshtein dependency

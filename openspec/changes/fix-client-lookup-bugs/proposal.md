## Why

Users report the research agent refuses to call `lookup_client` multiple times when asked to check client IDs for a list of people (e.g., "give me all NFL owners and check if they have client IDs"). The agent says it cannot do bulk lookups, which breaks user expectations. Additionally, two data bugs exist: the `fuzzy_client` table is queried from the wrong schema (`playbook` instead of `galileo`), and the `companies` column is mistyped as a scalar string when the database returns a `text[]` array.

## What Changes

- **Add `lookup_client` to the research agent system prompt** with explicit guidance that it SHOULD be called multiple times (in parallel batches) when users ask about multiple people. Currently the tool list in `agent.py` omits `lookup_client` entirely.
- **Fix schema reference**: Change all references from `playbook.fuzzy_client` to `galileo.fuzzy_client` across the DB query layer, schema initialization, health checks, integration tests, and LLM prompt context strings.
- **Fix `companies` column type**: Change `CandidateResult.companies` from `str | None` to `list[str] | None` to match the actual `text[]` column type, and update all downstream formatting code to join the list for display.

## Capabilities

### New Capabilities
- `bulk-client-lookup`: Agent system prompt guidance for iterative/parallel multi-person client ID lookups

### Modified Capabilities
- `client-id-lookup`: Fix schema reference (`playbook` -> `galileo`) and `companies` field type (`str` -> `list[str]`)

## Impact

- **Backend code**: `backend/app/agent/agent.py` (system prompt), `backend/app/db/client_lookup.py` (SQL queries), `backend/app/db/_schema.py` (index creation + health checks), `backend/app/models/client_lookup.py` (Pydantic model), `backend/app/agent/client_resolver.py` (LLM prompt builder, companies formatting), `backend/app/agent/tools.py` (tool output formatting)
- **Tests**: `backend/tests/test_client_lookup_integration.py` (schema references in seed SQL)
- **OpenSpec docs**: Multiple spec/design docs in `openspec/changes/client-id-lookup-tool/` reference `playbook.fuzzy_client`
- **No API changes**: The REST endpoint and tool schema are unchanged; only internal behavior and data correctness are affected

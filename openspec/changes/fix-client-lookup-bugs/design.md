## Context

The `lookup_client` tool was recently added to the research agent's tool registry but never integrated into the agent's system prompt. The agent receives the tool schema via OpenAI function calling but has no guidance on when or how to use it — and critically, no instruction that it can be called multiple times. Users requesting bulk lookups (e.g., "check all NFL owners for client IDs") see the agent refuse or call the tool only once.

Separately, the DB query layer references `playbook.fuzzy_client` but the actual table lives in the `galileo` schema. The `companies` column is a PostgreSQL `text[]` array, but the Pydantic model types it as `str | None`, causing serialization issues and incorrect display.

## Goals / Non-Goals

**Goals:**
- Agent calls `lookup_client` iteratively for multi-person queries, using parallel tool calls
- All DB queries target `galileo.fuzzy_client` (the correct schema)
- `companies` field correctly typed as `list[str]` throughout the stack
- Existing tests updated and passing

**Non-Goals:**
- Adding a dedicated bulk endpoint (the agent's parallel tool calling handles this)
- Changing the LLM adjudication model or thresholds
- Migrating data between schemas
- Updating archived OpenSpec docs (only live code and active specs)

## Decisions

### Decision 1: Agent prompt update strategy

**Choice:** Add `lookup_client` to the existing tool list in the system prompt with explicit bulk-usage guidance, plus a new "Client Lookup Queries" section.

**Rationale:** The agent already supports parallel tool calling (Phase 1 instructions say "Batch multiple independent tool calls into a single response"). We just need to tell it that `lookup_client` exists and should be called once per person. No code changes to the orchestrator needed — the LLM will naturally batch parallel `lookup_client` calls.

**Alternative considered:** Adding a `bulk_lookup_clients` tool that accepts a list of names. Rejected because it adds API surface, requires batch orchestration code, and the agent's native parallel tool calling already solves this.

### Decision 2: Schema reference — find-and-replace approach

**Choice:** Global replacement of `playbook.fuzzy_client` → `galileo.fuzzy_client` across all live code, tests, and schema initialization. Spec/design docs in `openspec/changes/client-id-lookup-tool/` are left as-is (historical artifacts).

**Rationale:** The table physically lives in `galileo`. The `playbook` reference was an error in the original spec that propagated into implementation. Since we don't own these tables, the schema name must match what the DBA provisioned.

### Decision 3: Companies field — list[str] typing

**Choice:** Change `CandidateResult.companies` from `str | None` to `list[str] | None`. Update all downstream consumers:
- DB layer: pass `row["companies"]` directly (asyncpg auto-converts `text[]` to `list[str]`)
- LLM prompt builder: join with `", "` for display
- Tool output formatter: join with `", "` for display

**Rationale:** asyncpg natively deserializes PostgreSQL `text[]` into Python `list[str]`. The current `str` typing silently coerces via `str(list)` which produces `"['Company A', 'Company B']"` — ugly and confusing for the LLM adjudicator.

## Risks / Trade-offs

- **[Risk] Agent over-calls lookup_client for very large lists (50+ names)** → Mitigation: The system prompt guidance caps parallel batches and the research evaluation loop naturally limits total tool calls. Token budget trimming in the orchestrator also prevents runaway.
- **[Risk] Schema change breaks if `galileo.fuzzy_client` doesn't exist in some environments** → Mitigation: The existing `verify_client_lookup_prerequisites()` health check already validates table existence at startup and logs warnings. No behavioral change needed.
- **[Risk] `companies` type change could break existing cached/serialized data** → Mitigation: There's no persistent caching of `CandidateResult` — it's created fresh per request from DB rows. The Pydantic model change is safe.

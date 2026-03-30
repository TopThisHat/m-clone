## Context

The backend has a research agent (`app/agent/agent.py`) that uses OpenAI function calling with a tool registry (`app/agent/tools.py`). Users interact conversationally and the agent calls tools to answer questions. Two existing PostgreSQL tables hold client identity data across different schemas:

- **`playbook.fuzzy_client`** (in search_path): `gwm_id`, `name`, `companies` -- curated client list with GIN index on `name`
- **`galileo.high_priority_queue_client`** (NOT in search_path, must be fully qualified): `entity_id`, `label`, `entity_id_type` -- queue table with GIN index on `label`, filtered by `entity_id_type = 'Client'`

The `fuzzy_client.name` column contains clean person names. The queue table's `label` column contains name + small bio text. Both tables have GIN trigram indexes (`gin_trgm_ops`).

**Key files:**
- `app/agent/tools.py` -- tool registry with `@_register` decorator
- `app/agent/agent.py` -- research agent orchestrator
- `app/db/_pool.py` -- asyncpg pool singleton, `search_path = playbook, public`
- `app/openai_factory.py` -- `get_openai_client()` returns `AsyncOpenAI`

## Goals / Non-Goals

**Goals:**
- Users can ask "does X have a client ID?" and get a structured answer with gwm_id and confidence
- Fuzzy matching handles typos, nicknames, and partial names via pg_trgm
- LLM resolves ambiguous matches (multiple candidates, same name different companies)
- Deterministic fallback when LLM is unavailable (Levenshtein scoring)
- Fast-path skips LLM for obvious single-candidate high-confidence matches
- Both agent tool and direct API endpoint available
- Comprehensive test coverage (unit, integration, e2e)

**Non-Goals:**
- Bulk lookup endpoint (deferred to v1.1)
- Frontend UI for client lookup (separate feature)
- Write-back or cache of resolved mappings
- Cross-referencing with other entity tables (`playbook.entities`, `entity_library`)
- Modifying the source tables or their schemas
- GET endpoint (POST only -- names shouldn't be in URLs/logs)

## Decisions

### Decision 1: Separate queries, merge in Python (not UNION)
**Choice:** Query both tables independently, merge and deduplicate in Python.
**Rationale:** The tables have different schemas (`gwm_id`/`name`/`companies` vs `entity_id`/`label`), different scoring functions (`similarity()` vs `word_similarity()`), and live in different PG schemas. A UNION would require artificial NULLs and couple the queries. Independent queries also allow partial results if one table is unavailable.

### Decision 2: word_similarity() for queue table, similarity() for fuzzy_client
**Choice:** Use `similarity()` + `%` operator for `fuzzy_client.name` (name-to-name comparison). Use `word_similarity()` + `%>` operator for queue `label` (name-within-bio matching).
**Rationale:** The queue table's `label` contains more than just a name (it includes a bio). `word_similarity()` finds the best-matching word-sized substring within the label, so "John Smith" scores well against "John Smith, Managing Director at Goldman Sachs" even though full-string similarity would be diluted.

### Decision 3: gpt-4o-mini for resolution
**Choice:** Use `gpt-4o-mini` at temperature=0.0 with `response_format={"type": "json_object"}`.
**Rationale:** By the time the LLM receives input, the DB has already solved the hard matching problem. The LLM only needs to judge a short ranked list of candidates -- shallow classification, not deep reasoning. gpt-4o-mini handles this at ~20x lower cost than gpt-4o with negligible quality difference for this task.

### Decision 4: Categorical confidence, not float
**Choice:** Confidence levels are categorical strings: "high", "medium", "low", "no_match".
**Rationale:** LLMs produce unreliable precise floats (0.73 vs 0.74 is false precision). Categorical levels map cleanly to business rules: fast-path = "high", disambiguation = "medium"/"low".

### Decision 5: Fast-path skips LLM when conditions met
**Choice:** Skip LLM call when: (a) exactly 1 candidate after dedup, (b) no company provided in query, (c) similarity >= 0.85 (fuzzy_client) or >= 0.75 (queue), (d) candidate has a gwm_id.
**Rationale:** Saves LLM cost and 400ms latency for the common case. The company guard ensures we always invoke the LLM when the user provides company context to verify.

### Decision 6: Label parsing in Python, not LLM
**Choice:** Parse queue table labels using regex in Python (`"Last, First - Company"` pattern).
**Rationale:** Deterministic, zero-cost, testable. The label format is structured data. The LLM's job is disambiguation, not string parsing.

### Decision 7: Levenshtein fallback, not failure
**Choice:** When LLM call fails (timeout, error, unparseable response), fall back to deterministic Levenshtein ratio scoring with confidence capped appropriately.
**Rationale:** Never fail the request. Users still get ranked candidates they can inspect manually.

### Decision 8: Resolver lives in app/agent/client_resolver.py
**Choice:** Place resolver logic alongside agent code, not in a new `services/` directory.
**Rationale:** The codebase has no services layer. Business logic lives in `app/db/` or `app/agent/`. Since the resolver uses the OpenAI client, it belongs with agent code.

### Decision 9: Threshold 0.3 for both tables
**Choice:** pg_trgm similarity threshold = 0.3, word_similarity threshold = 0.3, applied via SET LOCAL inside transactions.
**Rationale:** 0.3 aligns with the existing `db_find_similar_entities` in `knowledge_graph.py`. SET LOCAL prevents threshold leaking to other queries on the same pooled connection.

### Decision 10: Dedup by normalized name+company in Python
**Choice:** Deduplicate candidates in Python after merging results from both tables, keyed on `(normalized_name.lower(), company.lower())`, keeping highest similarity score.
**Rationale:** Cross-table dedup requires matching across different column shapes. Python dedup is cleaner, testable, and doesn't couple the two SQL queries.

## Architecture

```
User Question ("Does John Smith at Goldman have a client ID?")
    |
    v
[Research Agent] -- calls tool: lookup_client(name="John Smith", company="Goldman")
    |
    v
[client_resolver.resolve_client()]
    |
    +---> [normalize_name()] -- strip "Mr.", "Dr.", etc.
    |
    +---> asyncio.gather(
    |       search_fuzzy_client("John Smith", company="Goldman"),
    |       search_queue_client("John Smith"),
    |     )
    |
    +---> [parse_queue_label()] -- "Smith, John - Goldman" -> {name, company}
    |
    +---> [_dedup_candidates()] -- merge, dedup by name+company, top 10
    |
    +---> [_fast_path()] -- single candidate, high sim, no company? -> return immediately
    |     OR
    +---> [_call_llm()] -- gpt-4o-mini with candidates -> structured JSON
    |     ON FAILURE:
    +---> [_levenshtein_fallback()] -- deterministic scoring
    |
    v
ClientLookupResponse { match, alternatives, needs_disambiguation, conflict_gwm_ids }
```

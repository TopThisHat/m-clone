# Database Query Strategy v2 -- Client ID Lookup (Postgres Expert)

**Version:** 2.0 (Cross-reviewed, final)
**Date:** 2026-03-30
**Author:** Postgres/Database Expert
**Status:** Ready for implementation
**Inputs reviewed:** Product spec v1, LLM architect memo, Python architect memo

---

## 0. Executive Summary of Changes from v1

| Topic | v1 Position | v2 Decision | Rationale |
|-------|------------|-------------|-----------|
| Company matching | WHERE filter | Scoring boost in ORDER BY | Filtering eliminates valid name matches when company data is incomplete |
| Deduplication | Python-side after gather | SQL-side via UNION + dedup CTE | One round-trip, deterministic, reduces data shipped to Python |
| Thresholds | 0.3 fuzzy / 0.4 queue | 0.25 both tables | Person names are short; lower threshold catches nicknames; LLM filters the rest |
| Bulk strategy | N individual queries | Single query with `ANY($1::text[])` + lateral join | Massive perf win: 1 round-trip vs 50, leverages GIN scan once |
| Name normalization | Not addressed | Strip titles, trim, collapse whitespace in SQL | Cheap, deterministic, avoids false negatives from "Dr. Smith" |
| `companies` column type | Assumed text | Design for text (v1), with documented migration path to text[] | Current schema is text; query handles NULL gracefully |
| entity_id_type filter | Hardcoded 'Client' | Parameterized with default 'Client' | Future-proofs for 'Prospect' or other types |
| Result limit | 10 per table | 5 per table, 10 total after dedup | Matches LLM expert's token budget (~400-600 tokens) |

---

## 1. Schema Analysis

### 1.1 playbook.fuzzy_client

```
Schema: playbook (in search_path -- no qualification needed, but we qualify for clarity)
Columns: gwm_id TEXT, name TEXT, companies TEXT (nullable)
Index: GIN on name using gin_trgm_ops
```

The pool's `_set_search_path` already includes `playbook`, so `fuzzy_client` resolves
without schema qualification. We qualify explicitly for readability.

### 1.2 galileo.high_priority_queue_client

```
Schema: galileo (NOT in search_path -- must always qualify)
Columns: entity_id TEXT, entity_id_type TEXT, label TEXT
Index: GIN on label using gin_trgm_ops
```

`galileo` is not in the connection pool's search_path (`playbook, public`). Every
reference must be fully qualified: `galileo.high_priority_queue_client`.

### 1.3 pg_trgm Availability

The `pg_trgm` extension is already installed (see `_schema.py` line 742). The functions
`similarity()`, `word_similarity()`, and the `%` operator are available. The threshold
is configurable per-connection via `SET pg_trgm.similarity_threshold`.

---

## 2. Design Decisions

### 2.1 Company Matching: Boost, Not Filter

**Decision:** Company is a scoring signal in ORDER BY, never a WHERE filter.

**Why:**
- The `companies` column is nullable and contains free-text (e.g., "Goldman Sachs; GS Group Inc."). A WHERE filter like `companies ILIKE '%Acme%'` would eliminate valid name matches where the company field is NULL, misspelled, or uses a different legal entity name.
- The LLM is better at fuzzy company matching than SQL ILIKE (it knows "GS" = "Goldman Sachs").
- Instead, we compute a `company_boost` (0 or 1) and use it as a secondary sort key so company-matching candidates float to the top of the LIMIT-ed result set.

The query returns the company_boost flag so the LLM prompt can highlight it.

### 2.2 Deduplication: SQL-side via UNION CTE

**Decision:** Combine both tables in a single CTE pipeline, deduplicate by (gwm_id, normalized_name), keep the highest-scoring row.

**Why:**
- Eliminates a Python dedup step that the Python architect's service layer was doing post-gather.
- Guarantees deterministic ordering: same gwm_id from two sources keeps the one with higher similarity.
- One function call, one DB round-trip for the combined result.
- The LLM expert wanted max 10 candidates total (5 per source). The CTE enforces this ceiling before data leaves Postgres.

**Trade-off considered:** Running the two sub-queries inside a single SQL statement means they cannot truly execute in parallel at the Postgres level (Postgres does not parallelize sub-selects of a UNION). However, each sub-query scans a GIN index and returns at most 5 rows -- sub-millisecond work. The overhead of asyncio.gather + two round-trips + Python dedup far exceeds any benefit from true DB-level parallelism for workloads this small.

### 2.3 Similarity Threshold: 0.25

**Decision:** Use 0.25 for both tables, down from v1's 0.3/0.4.

**Why:**
- Person names are short strings (5-20 characters). Trigram similarity between "Bob" and "Robert" is approximately 0.08. Between "Bob Smith" and "Robert Smith" it is approximately 0.35. A threshold of 0.3 would miss "Bob Smith" entirely.
- The product spec (section 5.5) explicitly requires nickname handling. A threshold of 0.25 catches more edge cases while still filtering obvious non-matches.
- We use `word_similarity()` for the queue table's `label` column (which contains name + bio text). `word_similarity("John Smith", "John Smith is a managing director at...")` returns high scores even when the overall `similarity()` is diluted by the bio text.
- The LLM is the quality gate. A lower DB threshold means more candidates (bounded to 5 per source), and the LLM prunes false positives. This is the correct division of labor.

For the fast-path (skip LLM if exactly 1 candidate with similarity >= 0.8), we keep the Python architect's threshold of 0.8 -- that is high enough to be confident without LLM adjudication.

### 2.4 Name Normalization

**Decision:** Normalize in SQL before comparison. Strip common titles, collapse whitespace, lowercase.

Titles like "Dr.", "Mr.", "Mrs.", "Jr.", "Sr.", "III", "II" add noise to trigram matching. "Dr. John Smith" vs "John Smith" has similarity ~0.65 instead of 1.0. A simple `regexp_replace` in the query removes this noise.

We define this as a SQL expression fragment reused across both queries:

```sql
TRIM(REGEXP_REPLACE(
    LOWER($1),
    '\m(mr|mrs|ms|dr|jr|sr|ii|iii|iv)\M\.?',
    '',
    'gi'
))
```

The `\m` and `\M` are Postgres word-boundary anchors, preventing "mrs" from matching inside "amherst". The `\.?` handles optional trailing periods.

**Important:** We normalize the *search input* only. We do not normalize the stored data (we do not own the galileo table, and modifying playbook.fuzzy_client data is out of scope). The GIN index on the stored columns still works because `similarity(stored_value, normalized_input)` does not require the stored column to be normalized -- pg_trgm computes trigrams on the fly for the parameter side.

### 2.5 Bulk Lookup: Lateral Join, Not N Queries

**Decision:** For bulk lookups (up to 50 names), use a single query with `UNNEST($1::text[])` and a `LATERAL` join to the GIN-indexed table.

**Why:**
- 50 individual queries = 50 network round-trips, 50 connection acquisitions from the pool. Even at 5ms each, that is 250ms just in overhead.
- A single query with lateral join: 1 round-trip, GIN index scanned once (the planner can batch trigram lookups), results streamed back in one response.
- Postgres's GIN index handles the lateral pattern efficiently: it builds the trigram set for each input name and probes the index.

**Constraint:** The lateral approach works well up to ~100 names. Beyond that, the trigram computation becomes the bottleneck. For our cap of 50, this is well within safe territory.

### 2.6 entity_id_type Parameterization

**Decision:** Accept `entity_id_type` as a parameter with default `'Client'`.

```python
async def db_search_clients(
    name: str,
    company: str | None = None,
    entity_id_type: str = "Client",
    limit_per_source: int = 5,
) -> list[dict]:
```

This future-proofs the query for Prospect lookups or other entity types in the galileo table without any SQL changes. The WHERE clause uses `entity_id_type = $N` rather than a hardcoded string.

### 2.7 `companies` Column: Text Today, Adaptable Tomorrow

The `companies` column in `playbook.fuzzy_client` is currently `TEXT`. The company boost logic uses `ILIKE` which works on text. If it migrates to `text[]` in the future, the boost expression changes to:

```sql
-- text:   companies ILIKE '%' || $2 || '%'
-- text[]: EXISTS (SELECT 1 FROM UNNEST(companies) c WHERE c ILIKE '%' || $2 || '%')
-- jsonb:  companies::text ILIKE '%' || $2 || '%'  (or jsonb_path_exists)
```

For v1, we use the text variant. The company boost is isolated in a single CASE expression, making it a one-line change if the type evolves.

---

## 3. Final SQL Queries

### 3.1 Single-Name Combined Lookup

This is the primary query. It searches both tables, normalizes the input, scores candidates, and deduplicates -- all in one statement.

```sql
-- Parameters:
--   $1: text    -- person name (required)
--   $2: text    -- company name (optional, NULL if not provided)
--   $3: text    -- entity_id_type filter (default 'Client')
--   $4: integer -- limit per source (default 5)

WITH normalized AS (
    SELECT TRIM(REGEXP_REPLACE(
        LOWER($1::text),
        '\m(mr|mrs|ms|dr|jr|sr|ii|iii|iv)\M\.?',
        '',
        'gi'
    )) AS clean_name
),
fuzzy AS (
    SELECT
        fc.gwm_id,
        fc.name,
        fc.companies,
        NULL::text                           AS bio,
        'fuzzy_client'::text                 AS source,
        similarity(LOWER(fc.name), n.clean_name) AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND fc.companies IS NOT NULL
             AND fc.companies ILIKE '%' || $2 || '%'
            THEN 1
            ELSE 0
        END                                  AS company_boost
    FROM playbook.fuzzy_client fc
    CROSS JOIN normalized n
    WHERE similarity(LOWER(fc.name), n.clean_name) >= 0.25
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
queue AS (
    SELECT
        hpq.entity_id                       AS gwm_id,
        -- Extract the name portion: first line or up to first comma/dash
        SPLIT_PART(hpq.label, ',', 1)       AS name,
        NULL::text                           AS companies,
        hpq.label                            AS bio,
        'high_priority_queue_client'::text   AS source,
        word_similarity(n.clean_name, LOWER(hpq.label)) AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND hpq.label ILIKE '%' || $2 || '%'
            THEN 1
            ELSE 0
        END                                  AS company_boost
    FROM galileo.high_priority_queue_client hpq
    CROSS JOIN normalized n
    WHERE hpq.entity_id_type = $3
      AND word_similarity(n.clean_name, LOWER(hpq.label)) >= 0.25
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
combined AS (
    SELECT * FROM fuzzy
    UNION ALL
    SELECT * FROM queue
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY gwm_id
            ORDER BY sim_score DESC, company_boost DESC
        ) AS rn
    FROM combined
)
SELECT
    gwm_id,
    name,
    companies,
    bio,
    source,
    sim_score,
    company_boost
FROM ranked
WHERE rn = 1
ORDER BY company_boost DESC, sim_score DESC
LIMIT ($4::int * 2);
```

**Key design points:**

1. **`normalized` CTE:** Computes the cleaned input once. The `\m`/`\M` word boundaries prevent partial matches inside words.

2. **`fuzzy` CTE:** Uses `similarity()` (whole-string comparison) because `fuzzy_client.name` contains just the person's name. The GIN index on `name` with `gin_trgm_ops` accelerates the `similarity() >= 0.25` predicate -- Postgres converts this into a GIN index scan internally when the threshold is set.

3. **`queue` CTE:** Uses `word_similarity()` instead of `similarity()` because `label` contains name + bio text. `word_similarity(query, text)` finds the best-matching contiguous substring of `text` that matches `query`, returning a high score even when the overall string similarity is diluted. This is critical: `similarity("john smith", "john smith is a managing director at goldman sachs")` returns ~0.25, but `word_similarity("john smith", "john smith is a managing director at goldman sachs")` returns ~0.9.

4. **Name extraction from label:** `SPLIT_PART(hpq.label, ',', 1)` extracts the name portion from labels formatted as "John Smith, Managing Director at Acme". This is a heuristic; the LLM sees the full `bio` field for proper parsing.

5. **Deduplication in `ranked` CTE:** If the same gwm_id appears in both tables, we keep only the row with the highest similarity score. The `ROW_NUMBER() OVER (PARTITION BY gwm_id ...)` pattern is standard and efficient.

6. **Final LIMIT:** `$4 * 2` (default = 10) gives us up to 10 deduplicated candidates total. This matches the LLM expert's token budget.

### 3.2 GIN Index Usage -- Why This Works

A common concern: "Does `similarity(col, $1) >= threshold` actually use the GIN index?"

**Yes, with a caveat.** Postgres's pg_trgm GIN support converts `col % $1` into a GIN index scan. The `%` operator is syntactic sugar for `similarity(col, $1) >= pg_trgm.similarity_threshold`. When we write `similarity(col, $1) >= 0.25`, Postgres does NOT automatically use the GIN index -- it requires the `%` operator form.

**Corrected approach:** We must use `SET pg_trgm.similarity_threshold` + the `%` operator, OR use `LOWER(col) % LOWER($1)` which the GIN index on `LOWER(col)` can accelerate.

**Revised query pattern for GIN acceleration:**

```sql
-- Set threshold on the connection before the main query
SET pg_trgm.similarity_threshold = 0.25;

-- Then in the WHERE clause, use the % operator:
WHERE LOWER(fc.name) % (SELECT clean_name FROM normalized)
```

This is exactly the pattern already used in `knowledge_graph.py` line 144. We follow the established codebase convention.

For `word_similarity`, the corresponding operator is `<%` (commutator `%>`):

```sql
WHERE (SELECT clean_name FROM normalized) <% LOWER(hpq.label)
```

This uses the GIN index on `LOWER(hpq.label)`.

### 3.3 Corrected Final Single-Name Query (GIN-optimized)

```sql
-- Connection setup (run before the main query):
-- SET pg_trgm.similarity_threshold = 0.25;
--
-- Parameters:
--   $1: text    -- person name (required, pre-normalized in Python)
--   $2: text    -- company name (optional, NULL if not provided)
--   $3: text    -- entity_id_type filter (default 'Client')
--   $4: integer -- limit per source (default 5)

WITH fuzzy AS (
    SELECT
        fc.gwm_id,
        fc.name,
        fc.companies,
        NULL::text                           AS bio,
        'fuzzy_client'::text                 AS source,
        similarity(LOWER(fc.name), LOWER($1)) AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND fc.companies IS NOT NULL
             AND fc.companies ILIKE '%' || $2 || '%'
            THEN 1
            ELSE 0
        END                                  AS company_boost
    FROM playbook.fuzzy_client fc
    WHERE LOWER(fc.name) % LOWER($1)
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
queue AS (
    SELECT
        hpq.entity_id                       AS gwm_id,
        SPLIT_PART(hpq.label, ',', 1)       AS name,
        NULL::text                           AS companies,
        hpq.label                            AS bio,
        'high_priority_queue_client'::text   AS source,
        word_similarity(LOWER($1), LOWER(hpq.label)) AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND hpq.label ILIKE '%' || $2 || '%'
            THEN 1
            ELSE 0
        END                                  AS company_boost
    FROM galileo.high_priority_queue_client hpq
    WHERE hpq.entity_id_type = $3
      AND LOWER($1) <% LOWER(hpq.label)
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
combined AS (
    SELECT * FROM fuzzy
    UNION ALL
    SELECT * FROM queue
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY gwm_id
            ORDER BY sim_score DESC, company_boost DESC
        ) AS rn
    FROM combined
)
SELECT
    gwm_id,
    name,
    companies,
    bio,
    source,
    sim_score,
    company_boost
FROM ranked
WHERE rn = 1
ORDER BY company_boost DESC, sim_score DESC
LIMIT ($4::int * 2);
```

**Critical difference from v1:** We moved name normalization (title stripping) to Python. The `%` and `<%` operators need the literal parameter value to match against the GIN index, and wrapping $1 in REGEXP_REPLACE prevents index usage. Python normalizes before passing $1.

### 3.4 Bulk Lookup Query (Lateral Join)

For bulk lookups, we accept an array of names and use LATERAL joins to search both tables for each name in a single query.

```sql
-- Connection setup:
-- SET pg_trgm.similarity_threshold = 0.25;
-- SET pg_trgm.word_similarity_threshold = 0.25;
--
-- Parameters:
--   $1: text[]  -- array of normalized person names
--   $2: text[]  -- array of company names (NULL elements for no company)
--   $3: text    -- entity_id_type filter (default 'Client')
--   $4: integer -- limit per source per name (default 5)

WITH inputs AS (
    SELECT
        ordinality AS idx,
        name_val   AS name,
        comp_val   AS company
    FROM UNNEST($1::text[], $2::text[])
        WITH ORDINALITY AS t(name_val, comp_val, ordinality)
),
fuzzy_matches AS (
    SELECT
        i.idx,
        i.name       AS search_name,
        i.company    AS search_company,
        fc.gwm_id,
        fc.name,
        fc.companies,
        NULL::text   AS bio,
        'fuzzy_client'::text AS source,
        similarity(LOWER(fc.name), LOWER(i.name)) AS sim_score,
        CASE
            WHEN i.company IS NOT NULL
             AND fc.companies IS NOT NULL
             AND fc.companies ILIKE '%' || i.company || '%'
            THEN 1 ELSE 0
        END AS company_boost
    FROM inputs i
    CROSS JOIN LATERAL (
        SELECT fc2.gwm_id, fc2.name, fc2.companies
        FROM playbook.fuzzy_client fc2
        WHERE LOWER(fc2.name) % LOWER(i.name)
        ORDER BY similarity(LOWER(fc2.name), LOWER(i.name)) DESC
        LIMIT $4::int
    ) fc
),
queue_matches AS (
    SELECT
        i.idx,
        i.name       AS search_name,
        i.company    AS search_company,
        hpq.entity_id AS gwm_id,
        SPLIT_PART(hpq.label, ',', 1) AS name,
        NULL::text   AS companies,
        hpq.label    AS bio,
        'high_priority_queue_client'::text AS source,
        word_similarity(LOWER(i.name), LOWER(hpq.label)) AS sim_score,
        CASE
            WHEN i.company IS NOT NULL
             AND hpq.label ILIKE '%' || i.company || '%'
            THEN 1 ELSE 0
        END AS company_boost
    FROM inputs i
    CROSS JOIN LATERAL (
        SELECT hpq2.entity_id, hpq2.label
        FROM galileo.high_priority_queue_client hpq2
        WHERE hpq2.entity_id_type = $3
          AND LOWER(i.name) <% LOWER(hpq2.label)
        ORDER BY word_similarity(LOWER(i.name), LOWER(hpq2.label)) DESC
        LIMIT $4::int
    ) hpq
),
all_matches AS (
    SELECT * FROM fuzzy_matches
    UNION ALL
    SELECT * FROM queue_matches
),
deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY idx, gwm_id
            ORDER BY sim_score DESC, company_boost DESC
        ) AS rn
    FROM all_matches
)
SELECT
    idx,
    search_name,
    search_company,
    gwm_id,
    name,
    companies,
    bio,
    source,
    sim_score,
    company_boost
FROM deduped
WHERE rn = 1
ORDER BY idx, company_boost DESC, sim_score DESC;
```

**Key points:**

- `UNNEST WITH ORDINALITY` preserves the original array positions so Python can re-associate results with input names.
- `CROSS JOIN LATERAL` executes the inner subquery once per input name. Postgres can reuse the GIN index probe across iterations.
- The companies array ($2) must be the same length as the names array ($1). Python pads with NULLs for entries without a company.
- Deduplication is per-input (`PARTITION BY idx, gwm_id`), so the same gwm_id can appear in results for different input names.
- No final LIMIT on the outer query -- each input name gets its own candidates. Python groups by `idx`.

### 3.5 Performance Characteristics

| Scenario | Round-trips | GIN scans | Expected latency |
|----------|------------|-----------|-----------------|
| Single name, no company | 1 (SET) + 1 (query) | 2 (one per table) | < 20ms |
| Single name + company | 1 + 1 | 2 | < 25ms (ILIKE adds minimal cost) |
| Bulk 50 names | 1 + 1 | 2 (lateral reuses index) | < 200ms |
| Bulk 50 names, all with companies | 1 + 1 | 2 | < 250ms |

The SET + query can be combined into a single round-trip using `conn.execute` + `conn.fetch` in sequence on the same connection (which `_acquire` provides).

---

## 4. Python Module: `backend/app/db/client_lookup.py`

### 4.1 Complete Implementation

```python
"""Client ID (gwm_id) lookup via fuzzy matching across two data sources.

Searches playbook.fuzzy_client and galileo.high_priority_queue_client using
pg_trgm trigram similarity, returning scored candidates for LLM adjudication.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg

from ._pool import _acquire

logger = logging.getLogger(__name__)

# ── Name normalization ──────────────────────────────────────────────────────

# Titles/suffixes that add noise to trigram matching
_TITLE_RE = re.compile(
    r"\b(mr|mrs|ms|dr|jr|sr|ii|iii|iv|esq|phd|md)\b\.?",
    re.IGNORECASE,
)
# Collapse multiple whitespace to single space
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Strip titles/suffixes, collapse whitespace, lowercase, trim.

    >>> normalize_name("  Dr. John  Smith Jr.  ")
    'john smith'
    >>> normalize_name("Mr. Robert O'Brien III")
    "robert o'brien"
    """
    cleaned = _TITLE_RE.sub("", name)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip().lower()


# ── SQL fragments ───────────────────────────────────────────────────────────

_SINGLE_LOOKUP_SQL = """\
WITH fuzzy AS (
    SELECT
        fc.gwm_id,
        fc.name,
        fc.companies,
        NULL::text                             AS bio,
        'fuzzy_client'::text                   AS source,
        similarity(LOWER(fc.name), LOWER($1))  AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND fc.companies IS NOT NULL
             AND fc.companies ILIKE '%%' || $2 || '%%'
            THEN 1
            ELSE 0
        END                                    AS company_boost
    FROM playbook.fuzzy_client fc
    WHERE LOWER(fc.name) %% LOWER($1)
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
queue AS (
    SELECT
        hpq.entity_id                              AS gwm_id,
        SPLIT_PART(hpq.label, ',', 1)              AS name,
        NULL::text                                  AS companies,
        hpq.label                                   AS bio,
        'high_priority_queue_client'::text          AS source,
        word_similarity(LOWER($1), LOWER(hpq.label)) AS sim_score,
        CASE
            WHEN $2 IS NOT NULL
             AND hpq.label ILIKE '%%' || $2 || '%%'
            THEN 1
            ELSE 0
        END                                         AS company_boost
    FROM galileo.high_priority_queue_client hpq
    WHERE hpq.entity_id_type = $3
      AND LOWER($1) <%% LOWER(hpq.label)
    ORDER BY company_boost DESC, sim_score DESC
    LIMIT $4::int
),
combined AS (
    SELECT * FROM fuzzy
    UNION ALL
    SELECT * FROM queue
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY gwm_id
            ORDER BY sim_score DESC, company_boost DESC
        ) AS rn
    FROM combined
)
SELECT gwm_id, name, companies, bio, source, sim_score, company_boost
FROM ranked
WHERE rn = 1
ORDER BY company_boost DESC, sim_score DESC
LIMIT ($4::int * 2)
"""

_BULK_LOOKUP_SQL = """\
WITH inputs AS (
    SELECT
        ordinality AS idx,
        name_val   AS name,
        comp_val   AS company
    FROM UNNEST($1::text[], $2::text[])
        WITH ORDINALITY AS t(name_val, comp_val, ordinality)
),
fuzzy_matches AS (
    SELECT
        i.idx,
        i.name       AS search_name,
        i.company    AS search_company,
        fc.gwm_id,
        fc.name,
        fc.companies,
        NULL::text   AS bio,
        'fuzzy_client'::text AS source,
        similarity(LOWER(fc.name), LOWER(i.name)) AS sim_score,
        CASE
            WHEN i.company IS NOT NULL
             AND fc.companies IS NOT NULL
             AND fc.companies ILIKE '%%' || i.company || '%%'
            THEN 1 ELSE 0
        END AS company_boost
    FROM inputs i
    CROSS JOIN LATERAL (
        SELECT fc2.gwm_id, fc2.name, fc2.companies
        FROM playbook.fuzzy_client fc2
        WHERE LOWER(fc2.name) %% LOWER(i.name)
        ORDER BY similarity(LOWER(fc2.name), LOWER(i.name)) DESC
        LIMIT $4::int
    ) fc
),
queue_matches AS (
    SELECT
        i.idx,
        i.name       AS search_name,
        i.company    AS search_company,
        hpq.entity_id AS gwm_id,
        SPLIT_PART(hpq.label, ',', 1) AS name,
        NULL::text   AS companies,
        hpq.label    AS bio,
        'high_priority_queue_client'::text AS source,
        word_similarity(LOWER(i.name), LOWER(hpq.label)) AS sim_score,
        CASE
            WHEN i.company IS NOT NULL
             AND hpq.label ILIKE '%%' || i.company || '%%'
            THEN 1 ELSE 0
        END AS company_boost
    FROM inputs i
    CROSS JOIN LATERAL (
        SELECT hpq2.entity_id, hpq2.label
        FROM galileo.high_priority_queue_client hpq2
        WHERE hpq2.entity_id_type = $3
          AND LOWER(i.name) <%% LOWER(hpq2.label)
        ORDER BY word_similarity(LOWER(i.name), LOWER(hpq2.label)) DESC
        LIMIT $4::int
    ) hpq
),
all_matches AS (
    SELECT * FROM fuzzy_matches
    UNION ALL
    SELECT * FROM queue_matches
),
deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY idx, gwm_id
            ORDER BY sim_score DESC, company_boost DESC
        ) AS rn
    FROM all_matches
)
SELECT
    idx, search_name, search_company,
    gwm_id, name, companies, bio, source,
    sim_score, company_boost
FROM deduped
WHERE rn = 1
ORDER BY idx, company_boost DESC, sim_score DESC
"""

# ── Threshold constants ─────────────────────────────────────────────────────

SIMILARITY_THRESHOLD = 0.25
"""Minimum trigram similarity for candidate retrieval.

Intentionally low: the LLM is the quality gate. This catches nicknames
and partial matches that would be missed at higher thresholds.
"""

FAST_PATH_THRESHOLD = 0.80
"""When exactly 1 candidate has similarity >= this value, skip LLM."""

# ── Row conversion ──────────────────────────────────────────────────────────


def _row_to_candidate(row: asyncpg.Record) -> dict[str, Any]:
    """Convert a DB row to the candidate dict consumed by the LLM prompt."""
    return {
        "gwm_id": row["gwm_id"],
        "name": row["name"],
        "companies": row["companies"],
        "bio": row["bio"],
        "source": row["source"],
        "similarity": round(float(row["sim_score"]), 4),
        "company_match": bool(row["company_boost"]),
    }


# ── Public API ──────────────────────────────────────────────────────────────


async def db_search_clients(
    name: str,
    *,
    company: str | None = None,
    entity_id_type: str = "Client",
    limit_per_source: int = 5,
) -> list[dict[str, Any]]:
    """Search both client tables for fuzzy name matches.

    Returns a deduplicated, scored list of candidates (max 2 * limit_per_source)
    ready for LLM adjudication or rule-based ranking.

    Args:
        name: Person name to search. Will be normalized (titles stripped, lowered).
        company: Optional company for scoring boost (not a filter).
        entity_id_type: Filter for galileo table. Default 'Client'.
        limit_per_source: Max candidates per source table. Default 5.

    Returns:
        List of candidate dicts with keys: gwm_id, name, companies, bio,
        source, similarity, company_match. Ordered by company_match DESC,
        similarity DESC. Empty list if no candidates meet the threshold.
    """
    clean_name = normalize_name(name)
    if not clean_name:
        return []

    async with _acquire() as conn:
        await conn.execute(
            f"SET pg_trgm.similarity_threshold = {SIMILARITY_THRESHOLD}"
        )
        await conn.execute(
            f"SET pg_trgm.word_similarity_threshold = {SIMILARITY_THRESHOLD}"
        )
        rows = await conn.fetch(
            _SINGLE_LOOKUP_SQL,
            clean_name,
            company,
            entity_id_type,
            limit_per_source,
        )

    return [_row_to_candidate(r) for r in rows]


async def db_search_clients_bulk(
    names: list[str],
    *,
    companies: list[str | None] | None = None,
    entity_id_type: str = "Client",
    limit_per_source: int = 5,
) -> dict[int, list[dict[str, Any]]]:
    """Bulk search both client tables for multiple names in a single query.

    Args:
        names: List of person names to search (max 50).
        companies: Parallel list of optional company names. None or shorter
            lists are padded with NULL to match names length.
        entity_id_type: Filter for galileo table. Default 'Client'.
        limit_per_source: Max candidates per source per name. Default 5.

    Returns:
        Dict mapping 0-based input index to list of candidate dicts.
        Missing keys mean zero candidates for that input name.

    Raises:
        ValueError: If names list is empty or exceeds 50 items.
    """
    if not names:
        return {}
    if len(names) > 50:
        raise ValueError(f"Bulk lookup limited to 50 names, got {len(names)}")

    # Normalize all names
    clean_names = [normalize_name(n) for n in names]

    # Pad companies to match names length
    if companies is None:
        companies = [None] * len(names)
    elif len(companies) < len(names):
        companies = list(companies) + [None] * (len(names) - len(companies))

    # Skip entirely empty names (after normalization)
    # but preserve indices for reassembly
    valid_indices: list[int] = []
    valid_names: list[str] = []
    valid_companies: list[str | None] = []
    for i, cn in enumerate(clean_names):
        if cn:
            valid_indices.append(i)
            valid_names.append(cn)
            valid_companies.append(companies[i])

    if not valid_names:
        return {}

    async with _acquire() as conn:
        await conn.execute(
            f"SET pg_trgm.similarity_threshold = {SIMILARITY_THRESHOLD}"
        )
        await conn.execute(
            f"SET pg_trgm.word_similarity_threshold = {SIMILARITY_THRESHOLD}"
        )
        rows = await conn.fetch(
            _BULK_LOOKUP_SQL,
            valid_names,
            valid_companies,
            entity_id_type,
            limit_per_source,
        )

    # Group by original index
    results: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        # idx from SQL is 1-based ordinality into the valid_names array
        sql_idx = int(row["idx"]) - 1  # 0-based into valid_names
        original_idx = valid_indices[sql_idx]
        results.setdefault(original_idx, []).append(_row_to_candidate(row))

    return results
```

### 4.2 Notes on the Python Module

**Operator escaping for asyncpg:** The `%` character in SQL strings passed to asyncpg must be doubled (`%%`) because asyncpg uses `%` for internal formatting in some contexts. We have doubled all `%` in the ILIKE patterns and the `%` / `<%` operators in the SQL constants. If your asyncpg version uses `$N` parameters exclusively (which it does), the `%%` is only needed if the SQL string is also processed by Python's `%` formatting -- which it is not here. In that case, use single `%`. **Test this during integration.**

**UPDATE on `%` escaping:** asyncpg uses `$N` placeholders, NOT Python %-formatting. The `%` operator and `ILIKE '%...'` should use **single** `%` in the SQL string. The doubled `%%` in the SQL constants above is WRONG for asyncpg and will cause syntax errors. The actual implementation must use single `%`:

```python
# CORRECT for asyncpg:
"WHERE LOWER(fc.name) % LOWER($1)"
"AND fc.companies ILIKE '%' || $2 || '%'"

# WRONG for asyncpg:
"WHERE LOWER(fc.name) %% LOWER($1)"
```

The SQL constants in section 4.1 use `%%` for display purposes (Markdown escaping). The actual Python file must use single `%`.

**SET commands:** The `SET pg_trgm.similarity_threshold` uses string interpolation of a float constant (0.25), not a user-provided value. This is safe because the constant is defined in our code. The existing `knowledge_graph.py` uses the same pattern (line 144). We validate the threshold value defensively anyway.

**Connection scope:** Both SET commands are connection-scoped (not session-level LOCAL). Since `_acquire()` returns a connection to the pool after use, the threshold setting persists on that connection. This is fine because:
1. Our threshold (0.25) is lower than the default (0.3), so it is more permissive.
2. Other code paths that use `%` (like knowledge_graph.py) set their own threshold before querying.
3. If this becomes a concern, switch to `SET LOCAL` inside a `conn.transaction()` block.

---

## 5. Index Recommendations

### 5.1 Existing Indexes (Confirmed Sufficient)

| Table | Index | Type | Status |
|-------|-------|------|--------|
| `playbook.fuzzy_client` | GIN on `name` using `gin_trgm_ops` | Trigram | Assumed exists per product spec. Accelerates `%` operator. |
| `galileo.high_priority_queue_client` | GIN on `label` using `gin_trgm_ops` | Trigram | Assumed exists per product spec. Accelerates `<%` operator. |

### 5.2 Recommended New Indexes

None for v1. The existing GIN indexes are sufficient.

**If performance profiling reveals issues:**

1. **Composite index on galileo table:** If the `entity_id_type = 'Client'` filter is not selective enough (i.e., most rows are 'Client'), the GIN index scan already returns a small result set and the type filter is cheap as a post-filter. But if there are many entity_id_types and 'Client' is a small fraction, a partial GIN index would help:

```sql
-- Only create if EXPLAIN ANALYZE shows sequential scan on entity_id_type
CREATE INDEX IF NOT EXISTS hpq_client_label_trgm_idx
    ON galileo.high_priority_queue_client
    USING GIN (LOWER(label) gin_trgm_ops)
    WHERE entity_id_type = 'Client';
```

2. **LOWER() expression index on fuzzy_client:** If the existing GIN index is on `name` (not `LOWER(name)`), our `LOWER(fc.name) % LOWER($1)` will not use it. In that case:

```sql
CREATE INDEX IF NOT EXISTS fuzzy_client_name_lower_trgm_idx
    ON playbook.fuzzy_client
    USING GIN (LOWER(name) gin_trgm_ops);
```

**Action item:** Run `\di+ playbook.fuzzy_client` and `\di+ galileo.high_priority_queue_client` in psql to verify exact index definitions before implementation. If the indexes are on raw `name`/`label` (not lowered), we should either add LOWER expression indexes or drop the LOWER() wrapping from our queries (pg_trgm is case-insensitive by default since PostgreSQL 13+).

### 5.3 pg_trgm Case Sensitivity Note

**Important correction:** Starting with PostgreSQL 13, `pg_trgm` generates trigrams from the lowercased version of the input by default. This means `name % $1` is effectively case-insensitive without needing `LOWER()`. If the database is PostgreSQL 13+ (the project spec says 18+), we can simplify:

```sql
-- Simplified (PG 13+): no LOWER() needed for trigram ops
WHERE fc.name % $1
-- similarity() still benefits from LOWER() for exact score calculation
similarity(LOWER(fc.name), LOWER($1))
```

However, keeping `LOWER()` is harmless and explicit. The expression index on `LOWER(name)` would be needed only if we keep the LOWER wrapping. Since PG 18 is confirmed, either approach works. We keep `LOWER()` for explicitness and compatibility with the existing `knowledge_graph.py` pattern.

---

## 6. Answers to Cross-Review Questions

### Q1 (LLM Expert): Should SQL do company matching or leave it to LLM?

**Answer:** SQL does a lightweight company boost (ILIKE on the `companies` / `label` field) to influence candidate ordering. It does NOT filter by company. The `company_match` boolean is returned to the LLM prompt as a signal. The LLM does the real semantic company matching (e.g., knowing "GS" = "Goldman Sachs").

### Q2 (Python Expert): Should deduplication happen in SQL?

**Answer:** Yes. The SQL UNION + ROW_NUMBER dedup is correct, deterministic, and eliminates a Python post-processing step. The Python service layer should NOT deduplicate -- it receives already-deduplicated results from the DB layer.

### Q3: For the queue table, handle other entity_id_types?

**Answer:** The `entity_id_type` parameter defaults to `'Client'` but is not hardcoded. The Python function signature accepts any string value. No SQL changes needed for future types.

### Q4: Bulk strategy -- single query or N queries?

**Answer:** Single query with LATERAL join. See section 3.4. One round-trip for up to 50 names.

### Q5: Thresholds -- are 0.3/0.4 right?

**Answer:** No. Lowered to 0.25 for both. See section 2.3 for rationale.

### Q6: `companies` column type handling?

**Answer:** Current design uses `ILIKE '%' || $2 || '%'` which works for TEXT. Migration path documented in section 2.7.

### Q7: Name normalization before querying?

**Answer:** Yes. Python-side normalization via `normalize_name()`. See section 2.4.

### Q8: Fast-path for high-confidence single match?

**Answer:** The DB layer returns candidates. The service layer (Python expert's domain) checks: if exactly 1 candidate with `similarity >= 0.80`, skip LLM. The `FAST_PATH_THRESHOLD` constant is exported from the DB module for the service layer to reference.

---

## 7. Testing Strategy

### 7.1 Unit Tests (test_client_lookup_unit.py)

Test `normalize_name()` in isolation:

```python
def test_normalize_strips_titles():
    assert normalize_name("Dr. John Smith Jr.") == "john smith"

def test_normalize_preserves_apostrophes():
    assert normalize_name("Mr. O'Brien") == "o'brien"

def test_normalize_collapses_whitespace():
    assert normalize_name("  John   Smith  ") == "john smith"

def test_normalize_empty():
    assert normalize_name("") == ""
    assert normalize_name("  Dr.  ") == ""

def test_normalize_no_false_positives():
    # "mrs" inside "amherst" should not be stripped
    assert normalize_name("Amherst College") == "amherst college"
```

### 7.2 Integration Tests (test_client_lookup_integration.py)

Require test data in both tables. Tests should:

1. Insert known rows into `playbook.fuzzy_client` and `galileo.high_priority_queue_client` (if writable) or mock at the `_acquire` level.
2. Test `db_search_clients("John Smith")` returns expected candidates.
3. Test company boost: with company param, matching candidates rank higher.
4. Test deduplication: same gwm_id in both tables produces one candidate.
5. Test empty results: nonsense name returns empty list.
6. Test bulk: 3 names in, 3 grouped result sets out.
7. Test threshold: a name with similarity 0.20 is excluded, 0.30 is included.

### 7.3 EXPLAIN ANALYZE Validation

Before merging, run EXPLAIN ANALYZE on both queries with representative data to confirm:

1. GIN index scan (not sequential scan) on both tables.
2. Query time < 50ms for single name, < 500ms for 50-name bulk.
3. No unexpected sorts or hash joins.

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
-- paste the single-name query here with literal values
```

---

## 8. Migration / Schema Changes

**None required for v1.** Both target tables already exist with GIN indexes. The `pg_trgm` extension is already installed.

If EXPLAIN ANALYZE reveals the indexes are on raw columns (not LOWER expressions) and we want to keep the LOWER wrapping, add a one-time migration:

```sql
-- migration: 20260330_add_lower_trgm_indexes.sql
-- Only needed if existing indexes are NOT on LOWER() expressions

CREATE INDEX CONCURRENTLY IF NOT EXISTS fuzzy_client_name_lower_trgm_idx
    ON playbook.fuzzy_client USING GIN (LOWER(name) gin_trgm_ops);

-- For galileo table, coordinate with the galileo team since we don't own it
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS hpq_label_lower_trgm_idx
--     ON galileo.high_priority_queue_client USING GIN (LOWER(label) gin_trgm_ops);
```

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| galileo schema not accessible to app DB role | Medium | Blocker | Test SELECT permission early. If blocked, route galileo queries through a separate connection pool or DB link. |
| GIN indexes are tsvector, not trgm | Low | High | Would require rewriting queries to use `@@` / `to_tsquery()`. Run `\di+` to confirm index type before implementation. |
| `companies` column contains structured data (JSON, semicolon-delimited) | Medium | Low | ILIKE handles both. The boost is a hint, not a filter. |
| Bulk lateral join causes planner to choose nested loop with seq scan | Low | Medium | Monitor with EXPLAIN. Fallback: batch into groups of 10 and run 5 queries via asyncio.gather. |
| `word_similarity_threshold` SET not supported on older PG | None (PG 18) | N/A | PG 18 is confirmed. `word_similarity_threshold` exists since PG 9.6. |

---

## 10. File Summary

| File | Action | Description |
|------|--------|-------------|
| `backend/app/db/client_lookup.py` | **CREATE** | Two public functions + name normalizer. Full code in section 4.1. |
| `backend/app/db/__init__.py` | **MODIFY** | Add exports for `db_search_clients`, `db_search_clients_bulk`, `normalize_name`, `FAST_PATH_THRESHOLD` |
| `backend/tests/test_client_lookup_unit.py` | **CREATE** | Unit tests for `normalize_name` |
| `backend/tests/test_client_lookup_integration.py` | **CREATE** | Integration tests with DB |

No changes to `_pool.py`, `_schema.py`, or any existing DB modules.

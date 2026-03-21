# Knowledge Graph & Validation Workflow Redesign

## Status: IMPLEMENTED (P1-P8)

---

## 1. Problem Statement

The current validation workflow is unsustainable at scale:

- **N entities x M attributes = N*M research calls.** A campaign with 1,000 entities and 80 attributes generates 80,000 individual research + LLM calls.
- **No team scoping.** The `kg_entities` and `kg_relationships` tables are global with no ownership model.
- **Primitive deduplication.** Entity dedup relies on exact lowercase name + alias matching — "JPMorgan Chase" and "JP Morgan" won't match.
- **Staleness is TTL-only.** The `entity_attribute_knowledge` cache uses a flat 7-day TTL. No concept of "this was already researched in another campaign 2 days ago" across team boundaries.
- **No attribute grouping.** Each attribute triggers a separate research query, even when attributes are thematically related (e.g., "has ESG policy", "publishes sustainability report", "has carbon neutrality target" are all answerable from one ESG-focused research pass).

---

## 2. Design Goals

| # | Goal | Metric |
|---|------|--------|
| G1 | Team-scoped KG with master graph feed | Team data isolated; cross-team insights flow to master |
| G2 | Smart entity deduplication | LLM-assisted fuzzy matching + pg_trgm similarity |
| G3 | Staleness-aware research skipping | If master or campaign KG has fresh data, skip re-research |
| G4 | Attribute grouping → batched research | Reduce research calls by 5-15x via logical attribute clustering |
| G5 | Verification from grouped research | LLM extracts per-attribute verdicts from a single grouped report |

---

## 3. Architecture

### 3.1 Team-Scoped KG with Master Graph

```
┌─────────────────────────────────────────────────────────┐
│                    MASTER GRAPH                          │
│  kg_entities (team_id = NULL)                           │
│  kg_relationships (team_id = NULL)                      │
│  entity_attribute_knowledge (team_id = NULL)            │
│                                                         │
│  ▲ promoted from team graphs (reviewed / high-confidence)│
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────────┐
        │              │                  │
   ┌────▼────┐   ┌─────▼────┐    ┌───────▼──────┐
   │ Team A  │   │ Team B   │    │  Team C      │
   │ KG      │   │ KG       │    │  KG          │
   └─────────┘   └──────────┘    └──────────────┘
```

**Schema changes:**

```sql
-- Add team_id to KG tables
ALTER TABLE playbook.kg_entities
    ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

ALTER TABLE playbook.kg_relationships
    ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

ALTER TABLE playbook.entity_attribute_knowledge
    ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

-- team_id = NULL → master graph
-- team_id = <uuid> → team-scoped

-- Index for team-scoped queries
CREATE INDEX kg_entities_team_idx ON kg_entities(team_id);
CREATE INDEX kg_relationships_team_idx ON kg_relationships(team_id);
CREATE INDEX eak_team_idx ON entity_attribute_knowledge(team_id);
```

**Promotion rules (team → master):**
1. When a team-scoped entity/relationship achieves `confidence >= 0.85` AND has been validated by at least 2 independent research sessions, it is promoted to the master graph.
2. Promotion is async — a `promote_to_master` job runs after each validation job completes.
3. Master graph entities are immutable from individual team scopes — teams can reference them but not modify them directly.
4. A nightly reconciliation job merges newly promoted entities with existing master entities (dedup pass).

**Lookup order for research:**
1. Check master graph first (highest authority).
2. Check team-scoped graph.
3. If neither has fresh data → run research.

### 3.2 Smart Entity Deduplication

Current dedup is `LOWER(name)` exact match + alias array containment. This misses:
- Abbreviations: "JPMorgan Chase & Co." vs "JP Morgan"
- Name variants: "Alphabet Inc." vs "Google" vs "GOOGL"
- Misspellings from CSV uploads

**Three-layer dedup strategy:**

#### Layer 1: Postgres trigram similarity (fast, cheap)

```sql
-- Enable pg_trgm extension
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Add trigram index
CREATE INDEX kg_entities_name_trgm_idx
    ON kg_entities USING GIN (LOWER(name) gin_trgm_ops);

-- Candidate lookup: find entities with similarity > 0.4
SELECT id, name, entity_type,
       similarity(LOWER(name), LOWER($1)) AS sim
FROM playbook.kg_entities
WHERE LOWER(name) % LOWER($1)  -- uses GIN index, default threshold 0.3
  AND (team_id = $2 OR team_id IS NULL)  -- team + master scope
ORDER BY sim DESC
LIMIT 10;
```

#### Layer 2: Alias + GWM ID matching (exact)

```sql
-- Check if gwm_id already exists
SELECT id FROM kg_entities WHERE gwm_id = $1;

-- Check aliases
SELECT id FROM kg_entities WHERE $1 = ANY(aliases);
```

#### Layer 3: LLM confirmation (for ambiguous candidates)

When Layer 1 returns candidates with `0.4 < similarity < 0.85`, use an LLM to confirm:

```python
async def llm_confirm_entity_match(
    new_entity: str,
    candidate: dict,  # {name, entity_type, aliases, metadata}
) -> bool:
    """Ask LLM whether new_entity is the same as candidate."""
    prompt = f"""Are these the same real-world entity?

Entity A: {new_entity}
Entity B: {candidate['name']} (type: {candidate['entity_type']}, aliases: {candidate['aliases']})

Answer with JSON: {{"same_entity": true|false, "confidence": 0.0-1.0, "reason": "..."}}"""

    # Uses get_openai_client() — same proxy/token setup as app
    resp = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=150,
    )
    result = json.loads(resp.choices[0].message.content)
    return result.get("same_entity", False) and result.get("confidence", 0) >= 0.7
```

**Dedup pipeline (runs on entity insert/import):**
1. Exact match on `LOWER(TRIM(name))` or `gwm_id` → merge immediately.
2. Trigram query → if `sim >= 0.85` → auto-merge (add as alias).
3. Trigram query → if `0.4 <= sim < 0.85` → LLM confirm → merge or create new.
4. No candidates → create new entity.

### 3.3 Staleness & Research Skipping

**Current state:** `entity_attribute_knowledge` has a `last_updated` timestamp and `knowledge_cache_ttl_hours` (default 7 days). This is only checked per-pair.

**Proposed multi-tier staleness model:**

```sql
-- Add staleness metadata to knowledge table
ALTER TABLE playbook.entity_attribute_knowledge
    ADD COLUMN research_source TEXT,          -- 'campaign' | 'master' | 'manual'
    ADD COLUMN research_session_count INT DEFAULT 1,  -- how many independent sessions confirmed this
    ADD COLUMN staleness_tier TEXT DEFAULT 'fresh';    -- 'fresh' | 'warm' | 'stale' | 'expired'

-- Materialized view for staleness (refreshed by cron or trigger)
CREATE OR REPLACE FUNCTION playbook.compute_staleness_tier(last_updated TIMESTAMPTZ)
RETURNS TEXT AS $$
BEGIN
    IF last_updated > NOW() - INTERVAL '3 days' THEN RETURN 'fresh';
    ELSIF last_updated > NOW() - INTERVAL '14 days' THEN RETURN 'warm';
    ELSIF last_updated > NOW() - INTERVAL '30 days' THEN RETURN 'stale';
    ELSE RETURN 'expired';
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

**Staleness rules:**

| Tier | Age | Behavior |
|------|-----|----------|
| `fresh` | < 3 days | Skip research entirely. Use cached result. |
| `warm` | 3–14 days | Use cached result but flag as "may need refresh". Allow campaign owner to force re-research. |
| `stale` | 14–30 days | Re-research, but use cached result as fallback if research fails. |
| `expired` | > 30 days | Must re-research. Do not use cached result. |

**Cross-scope staleness check (the key innovation):**

Before researching `entity X + attribute group Y`:
1. Check **campaign-scoped** knowledge (team_id = campaign's team_id).
2. Check **master graph** knowledge (team_id = NULL).
3. If either returns `fresh` or `warm` → skip research for that attribute group.
4. If `stale` → re-research but merge with existing evidence.

```python
async def check_staleness(
    entity_gwm_id: str,
    attribute_labels: list[str],
    team_id: str | None,
    campaign_id: str,
) -> dict[str, str]:
    """Return {attribute_label: staleness_tier} for all attributes."""
    # Check team-scoped first, then master
    async with _acquire() as conn:
        rows = await conn.fetch("""
            SELECT attribute_label,
                   last_updated,
                   playbook.compute_staleness_tier(last_updated) AS tier,
                   team_id
            FROM playbook.entity_attribute_knowledge
            WHERE gwm_id = $1
              AND attribute_label = ANY($2)
              AND (team_id = $3 OR team_id IS NULL)
            ORDER BY
                CASE WHEN team_id = $3 THEN 0 ELSE 1 END,  -- prefer team-scoped
                last_updated DESC
        """, entity_gwm_id, attribute_labels, team_id)

    result = {}
    for row in rows:
        label = row["attribute_label"]
        if label not in result:  # first match wins (team > master, newest first)
            result[label] = row["tier"]

    # Attributes with no cached data → 'expired'
    for label in attribute_labels:
        if label not in result:
            result[label] = "expired"

    return result
```

### 3.4 Attribute Grouping → Batched Research

**This is the most impactful optimization.** Instead of 80 research calls per entity (one per attribute), we group attributes into ~5-10 logical clusters and generate one research question per cluster.

#### Step 1: Attribute Clustering (LLM-assisted, done once per campaign)

When a campaign's validation job starts, group attributes before fan-out:

```python
async def cluster_attributes(attributes: list[dict]) -> list[dict]:
    """
    Group attributes into logical clusters.
    Input: [{"id": uuid, "label": str, "description": str}, ...]
    Output: [
        {
            "cluster_name": "ESG & Sustainability",
            "attribute_ids": [uuid, uuid, ...],
            "research_question": "What ESG policies, sustainability reports, and carbon targets does {entity} have?"
        },
        ...
    ]
    """
    attr_text = "\n".join(
        f"- {a['label']}: {a.get('description', '')}"
        for a in attributes
    )

    prompt = f"""Group these attributes into logical research clusters. Each cluster should contain
attributes that can be answered by a single, focused research query.

Attributes:
{attr_text}

Rules:
- Create 5-15 clusters (fewer is better if attributes are related)
- Each attribute must appear in exactly one cluster
- Generate a research question template for each cluster (use {{entity}} as placeholder)
- The question should be specific enough to find evidence for ALL attributes in the cluster
- Keep clusters thematically coherent (don't mix financial metrics with ESG policies)

Return JSON:
{{
    "clusters": [
        {{
            "cluster_name": "string",
            "attribute_labels": ["label1", "label2", ...],
            "research_question": "Does {{entity}} have ... ?"
        }}
    ]
}}"""

    resp = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=2000,
    )
    return json.loads(resp.choices[0].message.content)["clusters"]
```

#### Step 2: Cache cluster assignments

Store clusters in the campaign so re-runs reuse the same grouping:

```sql
CREATE TABLE IF NOT EXISTS playbook.attribute_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    cluster_name    TEXT NOT NULL,
    attribute_ids   UUID[] NOT NULL,
    research_question_template TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX attribute_clusters_campaign_idx ON attribute_clusters(campaign_id);
```

#### Step 3: Revised Fan-Out (campaign → cluster-level jobs)

Instead of fanning out `entity x attribute` pairs, fan out `entity x cluster`:

```
ValidationCampaignWorkflow
├── Check staleness for all entity x attribute combos
├── Cluster attributes (if not already clustered)
├── For each entity:
│   ├── For each cluster:
│   │   ├── Check staleness of all attributes in cluster
│   │   ├── If ALL fresh → skip (use cached)
│   │   ├── If ANY stale/expired → enqueue validation_cluster job
│   │   └── Partial cache: carry forward fresh attributes, research the rest
│   └── End cluster loop
└── End entity loop
```

**New job type: `validation_cluster`**

```python
@registry.register("validation_cluster")
class ValidationClusterWorkflow(BaseWorkflow):
    """
    Research a cluster of attributes for one entity.

    payload: {
        "validation_job_id": str,
        "campaign_id": str,
        "entity_id": str,
        "cluster_id": str,
        "attribute_ids": [str, ...],
        "research_question": str,  # with {entity} already substituted
    }
    """
    async def run(self) -> None:
        # 1. Run research with the cluster question
        report_md = await run_research(self.payload["research_question"])

        # 2. Multi-attribute verification from single report
        results = await verify_attributes_from_report(
            entity=entity,
            attributes=attributes,  # all attributes in the cluster
            report_md=report_md,
        )

        # 3. Store results + update knowledge cache
        for attr_id, result in zip(attribute_ids, results):
            await db_insert_result(job_id, entity_id, attr_id, result, report_md)
```

### 3.5 Multi-Attribute Verification from Grouped Research

Instead of one LLM call per attribute, extract ALL attribute verdicts from a single report:

```python
async def verify_attributes_from_report(
    entity: dict,
    attributes: list[dict],
    report_md: str,
) -> list[dict]:
    """
    Given a research report, determine presence of ALL attributes at once.
    Returns list of {"present": bool, "confidence": float, "evidence": str}
    in the same order as the input attributes list.
    """
    attr_list = "\n".join(
        f"{i+1}. {a['label']}: {a.get('description', 'N/A')}"
        for i, a in enumerate(attributes)
    )

    prompt = f"""Entity: {entity['label']}

Based on the research report below, determine whether this entity has each of the following attributes.

Attributes to check:
{attr_list}

Research report:
{report_md[:8000]}

---
For EACH attribute (by number), return:
- present: true/false
- confidence: 0.0-1.0
- evidence: brief quote or explanation from the report

Return JSON array (same order as attributes above):
{{"results": [
    {{"attribute_number": 1, "present": true/false, "confidence": 0.0-1.0, "evidence": "..."}},
    ...
]}}"""

    resp = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=3000,
    )
    raw = json.loads(resp.choices[0].message.content)
    return raw.get("results", [])
```

---

## 4. Revised Workflow — End to End

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CAMPAIGN VALIDATION JOB                          │
│                                                                     │
│  1. CLUSTER ATTRIBUTES (one-time per campaign)                     │
│     └─ LLM groups 80 attributes → ~10 clusters                    │
│                                                                     │
│  2. STALENESS CHECK (batch, all entities x all attribute clusters) │
│     └─ Query master + team KG for cached results                   │
│     └─ Partition into: skip (fresh), research (stale/expired)      │
│                                                                     │
│  3. FAN-OUT: validation_cluster jobs                               │
│     └─ One job per (entity, cluster) where research is needed      │
│     └─ Typically 1000 entities x 3-5 stale clusters = 3,000-5,000 │
│        jobs instead of 80,000                                       │
│                                                                     │
│  4. EACH validation_cluster JOB:                                    │
│     a. Entity dedup check (is this entity already in KG?)          │
│     b. Research with cluster question                              │
│     c. Multi-attribute verification (1 LLM call per cluster)       │
│     d. Store results + update knowledge cache                      │
│     e. Feed to team KG → promote to master if high confidence     │
│                                                                     │
│  5. FINALIZE                                                        │
│     └─ Aggregate scores, update entity_scores, mark job complete   │
└─────────────────────────────────────────────────────────────────────┘
```

**Scale comparison (1,000 entities x 80 attributes):**

| Metric | Current | Proposed |
|--------|---------|----------|
| Research calls (worst case) | 80,000 | ~5,000-10,000 (10 clusters x 1000 entities) |
| Research calls (with 50% cache hit) | 40,000 | ~2,500-5,000 |
| LLM verification calls | 80,000 | ~5,000-10,000 (1 per cluster per entity) |
| Total API calls | 160,000 | ~10,000-20,000 |
| Reduction | — | **~8-16x fewer calls** |

---

## 5. Database Migrations Summary

```sql
-- 1. Team-scope KG tables
ALTER TABLE playbook.kg_entities ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;
ALTER TABLE playbook.kg_relationships ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;
ALTER TABLE playbook.entity_attribute_knowledge ADD COLUMN team_id UUID REFERENCES teams(id) ON DELETE SET NULL;

-- 2. Staleness metadata
ALTER TABLE playbook.entity_attribute_knowledge
    ADD COLUMN research_source TEXT DEFAULT 'campaign',
    ADD COLUMN research_session_count INT DEFAULT 1,
    ADD COLUMN staleness_tier TEXT DEFAULT 'fresh';

-- 3. Trigram extension + index
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX kg_entities_name_trgm_idx ON playbook.kg_entities USING GIN (LOWER(name) gin_trgm_ops);

-- 4. Attribute clusters table
CREATE TABLE IF NOT EXISTS playbook.attribute_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES playbook.campaigns(id) ON DELETE CASCADE,
    cluster_name    TEXT NOT NULL,
    attribute_ids   UUID[] NOT NULL,
    research_question_template TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Staleness function
CREATE OR REPLACE FUNCTION playbook.compute_staleness_tier(last_updated TIMESTAMPTZ)
RETURNS TEXT AS $$
BEGIN
    IF last_updated > NOW() - INTERVAL '3 days' THEN RETURN 'fresh';
    ELSIF last_updated > NOW() - INTERVAL '14 days' THEN RETURN 'warm';
    ELSIF last_updated > NOW() - INTERVAL '30 days' THEN RETURN 'stale';
    ELSE RETURN 'expired';
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 6. Knowledge promotion tracking
CREATE TABLE IF NOT EXISTS playbook.kg_promotions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_team_id  UUID NOT NULL REFERENCES playbook.teams(id),
    entity_id       UUID NOT NULL REFERENCES playbook.kg_entities(id),
    promoted_at     TIMESTAMPTZ DEFAULT NOW(),
    promoted_by     TEXT  -- 'auto' or user sid
);
```

---

## 6. New/Modified Files

| File | Change |
|------|--------|
| `worker/workflows/validation.py` | Replace `validation_pair` with `validation_cluster`. Modify `ValidationCampaignWorkflow` for cluster-based fan-out. |
| `worker/llm.py` | Replace `determine_presence()` with `verify_attributes_from_report()` (multi-attribute). |
| `worker/entity_extraction.py` | Add team_id propagation when storing KG data. |
| `app/db/knowledge.py` | Add team-scoped lookup, staleness queries, batch staleness check. |
| `app/db/knowledge_graph.py` | Add team_id to dedup, add trigram-based candidate search, add LLM dedup confirmation. |
| `app/db/_schema.py` | All migration DDL above. |
| `worker/workflows/attribute_clustering.py` | **New** — LLM attribute clustering logic. |
| `worker/workflows/kg_promotion.py` | **New** — Team → master graph promotion workflow. |

---

## 7. Critical Review — Expert Panel

### 7.1 Knowledge Graph Expert

**Strengths:**
- Team-scoped KG with master graph feed is the right pattern (follows federated KG best practices).
- Promotion based on confidence + independent session count prevents low-quality data from polluting the master graph.
- Staleness tiers are more nuanced than binary TTL.

**Concerns:**
- **Entity resolution across teams is hard.** Team A might call an entity "Google" and Team B "Alphabet Inc." The trigram + LLM dedup handles this at insert time, but what about entities that are *already in different team graphs* and should be the same master entity? **Recommendation:** Add a periodic cross-team reconciliation job that runs the dedup pipeline across all team KGs, not just at insert time.
- **Predicate conflict resolution needs a merge strategy.** When promoting from team → master, what if the master graph already has conflicting relationships? The current `db_upsert_relationship` handles same-family conflicts, but cross-team conflicts need an adjudication step. **Recommendation:** Add a conflict queue for human review when automated confidence is < 0.8.
- **KG entity types are too coarse.** The current enum (`person | company | sports_team | location | product | other`) will cause type collisions. "Apple" is both a company and a product. **Recommendation:** Allow multi-type entities or use a separate `entity_categories` junction table.

### 7.2 Job Queue Expert

**Strengths:**
- Cluster-based fan-out dramatically reduces job count (8-16x).
- Reusing the existing `job_queue` table and Redis Streams pattern is good — no new infra.

**Concerns:**
- **Cluster jobs are heavier than pair jobs.** A `validation_cluster` job does research + multi-attribute LLM verification for ~8 attributes. If it fails mid-way, do you retry the entire cluster? **Recommendation:** Make cluster jobs idempotent — store per-attribute results as they complete, so retries only re-do missing attributes. Use a `cluster_results` staging table that feeds into `validation_results` on completion.
- **Attribute clustering is a prerequisite job.** If the clustering LLM call fails, the entire campaign is blocked. **Recommendation:** Make clustering a separate, retriable job (`attribute_clustering` type) with its own max_attempts. Only proceed to fan-out after clusters are stored.
- **Backpressure risk.** With 1,000 entities x 10 clusters = 10,000 cluster jobs, the initial enqueue is still a large `INSERT`. **Recommendation:** Batch-enqueue in chunks of 500 with `pg_notify` after each chunk, not after the entire batch. The dispatcher can start claiming jobs immediately.
- **Dead letter handling.** The current `on_dead` handler marks the validation_job as failed if a pair dies. With clusters, a single dead cluster only affects ~8 attributes, not the entire job. **Recommendation:** Change `on_dead` to log partial failure and let the campaign continue. Only fail the entire job if >20% of clusters are dead.

### 7.3 SQL / Postgres Expert

**Strengths:**
- `pg_trgm` GIN index for fuzzy matching is the right tool — fast and well-supported.
- `compute_staleness_tier` as an IMMUTABLE function allows use in indexes and WHERE clauses.
- The staleness query with `ORDER BY CASE WHEN team_id = $3 THEN 0 ELSE 1 END` correctly prioritizes team-scoped results.

**Concerns:**
- **`compute_staleness_tier` is NOT actually immutable.** It uses `NOW()`, which changes every call. Postgres won't enforce this, but it means you can't use it in generated columns or functional indexes. **Recommendation:** Either make it STABLE (correct but no index use) or pass the reference timestamp as a parameter: `compute_staleness_tier(last_updated, reference_ts)` where `reference_ts` is frozen at query start.
- **The `entity_attribute_knowledge` table will grow large.** With 1000s of entities × 100 attributes × multiple teams, this table could reach millions of rows. The current PK is `(gwm_id, attribute_label)` which doesn't support team_id. **Recommendation:** Change PK to `(gwm_id, attribute_label, team_id)` using a COALESCE for NULL team_id: `CREATE UNIQUE INDEX ON entity_attribute_knowledge (gwm_id, attribute_label, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid))`. Add a partial index for master-only lookups.
- **`UUID[]` in `attribute_clusters.attribute_ids` is queryable but not referentially enforced.** If an attribute is deleted from the campaign, the cluster still references it. **Recommendation:** Add a trigger or use a junction table `cluster_attributes(cluster_id, attribute_id)` instead. Or accept the denormalization and handle it in application code (filter out missing attributes at runtime).
- **Batch staleness check could be a single query.** Instead of per-entity checks, do a bulk `JOIN unnest(...) AS inp(gwm_id, attribute_label)` against `entity_attribute_knowledge` — same pattern as `db_lookup_knowledge_batch` but with staleness tiers. This avoids N+1 queries during fan-out.
- **Index bloat from LOWER(name) GIN trigram.** For tables > 100K rows, the GIN index can become large. Monitor with `pg_stat_user_indexes` and consider `GiST` instead of `GIN` if write-heavy workloads cause index bloat.

### 7.4 Devil's Advocate (Problem Finder)

**Issue 1: LLM attribute clustering is non-deterministic.**
The same set of 80 attributes might be grouped differently on each run. If the campaign is re-validated, clusters change, cache keys don't match, and you lose all staleness benefits. **Mitigation:** Cache clusters per campaign (already in the plan). But what if attributes are *added* to a campaign between runs? You need incremental re-clustering: append new attributes to existing clusters or create new clusters for orphans, rather than re-clustering from scratch.

**Issue 2: Multi-attribute verification accuracy degrades with cluster size.**
Asking an LLM to evaluate 15 attributes from one report is less accurate than evaluating 3. The model may hallucinate or miss nuances. **Mitigation:** Cap cluster size at 8-10 attributes. If the clustering LLM produces larger clusters, split them. Also: include a confidence calibration step — if any attribute gets confidence < 0.5, flag it for individual re-research.

**Issue 3: Staleness tiers are arbitrary.**
Why 3 days for "fresh" and not 5? Different attribute types have different decay rates — a company's CEO changes rarely, but stock price changes daily. **Mitigation:** Allow per-attribute or per-attribute-cluster staleness overrides. Store `staleness_ttl_hours` on the attribute or cluster level, defaulting to the tier system.

**Issue 4: Master graph promotion creates a "blessing" problem.**
Who decides what gets promoted? The 0.85 confidence + 2 sessions rule is algorithmic, but what about controversial or sensitive facts? If Team A says "Company X has ESG violations" and it gets auto-promoted to the master graph, Team B sees it without context. **Mitigation:** Add a `requires_review` flag on certain predicate families or attribute types. High-sensitivity data goes through a review queue before master promotion.

**Issue 5: The research question quality is a single point of failure.**
If the LLM generates a bad research question for a cluster, ALL attributes in that cluster get poor results. There's no feedback loop. **Mitigation:** After verification, if >50% of attributes in a cluster have confidence < 0.6, re-generate the research question and re-research. Limit to one retry to prevent infinite loops.

**Issue 6: Entity dedup LLM calls can cascade.**
If you import 1,000 entities and each triggers a trigram search + LLM confirmation, that's up to 1,000 LLM calls just for dedup. **Mitigation:** Batch dedup — collect all trigram candidates for the entire import, group by candidate entity, and make one LLM call per candidate group instead of per import entity. E.g., if 50 imports all match "JPMorgan" variants, one LLM call confirms all 50.

**Issue 7: Race condition in team → master promotion.**
Two teams might promote the same entity simultaneously, creating duplicates in the master graph. **Mitigation:** Use `INSERT ... ON CONFLICT` on the master graph with `LOWER(name)` as before, but within an advisory lock scoped to the entity name hash: `pg_advisory_xact_lock(hashtext(LOWER(entity_name)))`.

---

## 8. Implementation Order

| Phase | Work | Depends On | Risk |
|-------|------|------------|------|
| **P1** | Team-scope columns + migrations | Nothing | Low — additive DDL |
| **P2** | Staleness function + lookup refactor | P1 | Low |
| **P3** | `pg_trgm` + trigram dedup layer | P1 | Low |
| **P4** | Attribute clustering (LLM + storage) | Nothing | Medium — LLM quality |
| **P5** | `validation_cluster` workflow | P2, P4 | High — replaces core workflow |
| **P6** | Multi-attribute verification | P5 | Medium — accuracy validation needed |
| **P7** | LLM entity dedup (Layer 3) | P3 | Medium |
| **P8** | Team → Master promotion workflow | P1, P7 | Medium — conflict resolution |
| **P9** | Cross-team reconciliation job | P8 | Low priority, can defer |

**Recommended approach:** P1 → P2 → P3 → P4 in parallel → P5 → P6 → P7 → P8. P9 can be deferred.

---

## 9. Open Questions

1. **Should clusters be team-scoped or global?** If two teams have the same attribute set, should they share cluster definitions? (Recommendation: per-campaign, since attribute sets may differ.)
2. **What is the confidence threshold for auto-promotion?** 0.85 is proposed — should this be configurable per team?
3. **Should staleness tiers be configurable per campaign?** Some campaigns may need faster freshness guarantees.
4. **How should we handle attribute weight in cluster research?** High-weight attributes might warrant their own cluster to ensure thorough research.
5. **Should the master graph be queryable from the frontend, or is it backend-only?** Current KG explorer shows all entities — need to add team filtering.

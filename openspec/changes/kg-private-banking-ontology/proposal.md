## Why

The knowledge graph grows unbounded: entity types are open-ended (`other` catch-all), relationship predicates proliferate without control ("owns a team" vs "buys a team" vs "purchased a team" become three separate things), and trivial relationships (coaching assignments, event attendance) clutter the graph. Private bankers closing sports deals need a curated, high-signal KG -- not an encyclopedia. Without a controlled ontology, the graph becomes un-queryable and the extraction pipeline produces noise that obscures deal-origination signals.

## What Changes

- **Replace open-ended entity types with a closed set of 10 domain-specific types** (person, sports_team, sports_league, company, pe_fund, sports_foundation, transaction_event, location, life_event, media_rights_deal). No `other` or `product` catch-all. Hard ceiling enforced at import time.
- **Redesign relationship families from 5 generic to 7 domain-focused** families: ownership, investment, role, deal_network, affinity, life_event, location. Each family capped at 8 canonical predicates.
- **Add three-tier relevance filtering** (HIGH/MEDIUM/LOW signal) so trivial relationships are dropped before storage. HIGH-signal predicates (owns, invested_in, ceo_of, partnered_on_deal) are always kept. LOW-signal predicates (coaches, competes_with, attended_event) are always dropped.
- **Enforce predicate normalization** so all synonym variants map to a single canonical form. Unknown predicates return `None` and are rejected (no silent fallback to "partnership").
- **Add anti-explosion rules**: max entity types (10), max predicates per family (8), confidence floor (0.50), max predicates per entity pair (3), entity staleness flagging (730 days).
- **Update LLM extraction prompt** to only show HIGH/MEDIUM signal predicates, constraining the LLM to produce curated output.
- **Create compatibility shim** for existing `predicate_normalization.py` imports.

## Capabilities

### New Capabilities
- `kg-ontology`: Controlled ontology module defining allowed entity types, relationship families, canonical predicates, variant mappings, signal levels, relevance rules, and anti-explosion guards. Single source of truth for what belongs in the KG.
- `kg-relevance-filtering`: Three-tier relevance filtering system (HIGH/MEDIUM/LOW signal) with per-family confidence thresholds that decides what relationships and entities are stored vs dropped.
- `kg-predicate-normalization-v2`: Domain-specific predicate normalization with strict rejection of unknown predicates (returns None instead of silent fallback). Priority-ordered cross-family search with fuzzy suffix stripping.

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

- **backend/app/kg_ontology.py** (new): Core ontology module with entity types, families, predicates, normalization, relevance rules
- **backend/worker/entity_extraction.py**: Updated prompt, normalization imports, relevance filtering in `_process_message()`
- **backend/app/predicate_normalization.py**: Becomes thin compatibility shim delegating to `kg_ontology`
- **backend/app/db/knowledge_graph.py**: Symmetric relationship detection updated to use ontology
- **Database**: No schema changes needed (entity_type and predicate are free-text columns already)
- **Frontend**: No changes needed (entity types and predicate families are rendered dynamically)
- **Existing KG data**: Legacy predicates can be migrated via `translate_legacy_predicate()` helper

## 1. Core Ontology Module

- [ ] 1.1 Create `backend/app/kg_ontology.py` with `EntityTypeSpec` dataclass, `ENTITY_TYPES` dict (10 types), `ENTITY_TYPE_MAX` constant, `ALLOWED_ENTITY_TYPE_NAMES` frozenset, and import-time assertion
- [ ] 1.2 Add `SignalLevel` enum (HIGH, MEDIUM, LOW) and `PredicateSpec` dataclass (canonical, signal, symmetric, description)
- [ ] 1.3 Add `RelationshipFamily` dataclass with predicates dict, variants dict, and `normalize()` method
- [ ] 1.4 Define ownership family: 6 canonical predicates (owns, minority_stake_in, co_owns, formerly_owned, controls, subsidiary_of) with ~25 variant mappings
- [ ] 1.5 Define investment family: 6 canonical predicates (invested_in, lp_in, gp_of, co_invested_with, donated_to, exited) with ~25 variant mappings
- [ ] 1.6 Define role family: 7 canonical predicates (ceo_of, board_member_of, founded, executive_at, advisor_to, plays_for, coaches) with ~25 variant mappings
- [ ] 1.7 Define deal_network family: 6 canonical predicates (partnered_on_deal, bid_for, merged_with, competes_with, sponsors, endorsed_by) with ~20 variant mappings
- [ ] 1.8 Define affinity family: 4 canonical predicates (fan_of, attended_event, played_sport, named_in_honor_of) with ~15 variant mappings
- [ ] 1.9 Define life_event family: 4 canonical predicates (married, divorced, inherited_from, succession_from) with ~15 variant mappings
- [ ] 1.10 Define location family: 4 canonical predicates (headquartered_in, resides_in, operates_in, plays_in) with ~15 variant mappings
- [ ] 1.11 Create `RELATIONSHIP_FAMILIES` master registry and import-time assertion on predicate count per family
- [ ] 1.12 Add `AntiExplosionRules` frozen dataclass and `ANTI_EXPLOSION_RULES` instance with all specified limits
- [ ] 1.13 Add `LEGACY_FAMILY_MAP` dict and `translate_legacy_predicate()` migration helper

## 2. Predicate Normalization V2

- [ ] 2.1 Implement `normalize_predicate(raw_predicate, family_hint="")` with three-pass logic: hinted family exact match → priority-ordered cross-family search → fuzzy suffix stripping. Return `None` on failure.
- [ ] 2.2 Define the cross-family priority order: ownership > investment > role > deal_network > life_event > affinity > location
- [ ] 2.3 Implement input normalization: lowercase, strip whitespace, replace spaces/hyphens with underscores

## 3. Relevance Filtering

- [ ] 3.1 Define `RelevanceRule` dataclass with tier (keep/conditional/drop), min_confidence, and reason
- [ ] 3.2 Create `RELEVANCE_RULES` dictionary mapping (family, SignalLevel) → RelevanceRule for all combinations
- [ ] 3.3 Implement `should_keep_relationship(family, predicate, confidence)` with global confidence floor (0.50) and per-family/signal thresholds
- [ ] 3.4 Implement `score_entity_relevance(entity_type, high_signal_rel_count, medium_signal_rel_count, low_signal_only)` scoring formula
- [ ] 3.5 Implement `should_keep_entity()` wrapping `score_entity_relevance()` with `ENTITY_RELEVANCE_FLOOR` (0.40) check

## 4. LLM Prompt Helpers

- [ ] 4.1 Implement `get_entity_types_prompt()` listing all 10 types with rationale
- [ ] 4.2 Implement `get_canonical_predicates_prompt()` listing only HIGH+MEDIUM signal predicates (suppress LOW)
- [ ] 4.3 Implement `get_lm_prompt_section()` combining entity types and predicates into a single prompt section

## 5. Extraction Pipeline Integration

- [ ] 5.1 Update `entity_extraction.py` imports: replace `predicate_normalization` with `kg_ontology` for normalization, relevance filtering, and prompt generation
- [ ] 5.2 Update `ExtractedEntity.type` comment and `ExtractedRelationship.predicate_family` comment to reflect new types and families
- [ ] 5.3 Update `extract_entities_and_relationships()` prompt: use `get_lm_prompt_section()`, new entity type list, new family names in JSON schema
- [ ] 5.4 Update `_process_message()`: add entity type validation (skip entities not in `ALLOWED_ENTITY_TYPE_NAMES`)
- [ ] 5.5 Update `_process_message()`: handle `normalize_predicate()` returning `None` (skip relationship, increment `filtered_by_unknown_predicate` counter)
- [ ] 5.6 Update `_process_message()`: call `should_keep_relationship()` after normalization (skip if False, increment `filtered_by_relevance` counter)
- [ ] 5.7 Update `_process_message()` return dict to include `filtered_by_relevance` and `filtered_by_unknown_predicate` counters
- [ ] 5.8 Update `_relationship_already_exists()`: replace hardcoded `symmetric_families = {"partnership"}` with ontology-based `pred_spec.symmetric` lookup

## 6. Compatibility Shim

- [ ] 6.1 Convert `predicate_normalization.py` to thin wrapper delegating to `kg_ontology.normalize_predicate()`
- [ ] 6.2 Preserve old return contract: always return `tuple[str, str]` (fallback to input when ontology returns None)
- [ ] 6.3 Keep `CANONICAL_PREDICATES` dict as static backward-compatible alias
- [ ] 6.4 Delegate `get_canonical_predicates_prompt()` to `kg_ontology.get_canonical_predicates_prompt()`
- [ ] 6.5 Add deprecation notice in module docstring pointing to `kg_ontology`

## 7. Testing

- [ ] 7.1 Unit tests: closed entity type set and hard limit assertions
- [ ] 7.2 Unit tests: predicate hard limits per family assertions
- [ ] 7.3 Unit tests: normalization — exact match, variant match, cross-family, fuzzy strip, unknown returns None
- [ ] 7.4 Unit tests: `should_keep_relationship()` — all three tiers (keep, conditional, drop) with boundary confidence values
- [ ] 7.5 Unit tests: `should_keep_entity()` / `score_entity_relevance()` — valid types, invalid types, signal counting
- [ ] 7.6 Unit tests: anti-explosion rules structural correctness
- [ ] 7.7 Unit tests: prompt helpers — LOW predicates absent, all entity types present, combined prompt works
- [ ] 7.8 Unit tests: legacy migration helper — all 5 old families map correctly
- [ ] 7.9 Unit tests: compatibility shim — old imports work, old return contract preserved, known predicates delegate correctly
- [ ] 7.10 Integration test: end-to-end extraction with relevance filtering (mock LLM response → verify filtered counts)

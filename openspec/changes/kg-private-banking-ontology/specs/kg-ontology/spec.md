## ADDED Requirements

### Requirement: Closed entity type set with hard ceiling
The system SHALL define exactly 10 allowed entity types for the KG: `person`, `sports_team`, `sports_league`, `company`, `pe_fund`, `sports_foundation`, `transaction_event`, `location`, `life_event`, `media_rights_deal`. No `other` or `product` catch-all type SHALL exist. The system SHALL enforce a hard ceiling of 10 entity types at module import time via assertion. Adding an 11th type MUST fail immediately.

#### Scenario: Entity with valid type is accepted
- **WHEN** the extraction pipeline produces an entity with type `pe_fund`
- **THEN** the entity is accepted for KG storage

#### Scenario: Entity with invalid type is rejected
- **WHEN** the extraction pipeline produces an entity with type `other` or `product`
- **THEN** the entity is dropped and a debug log is emitted

#### Scenario: Adding an 11th entity type fails at import
- **WHEN** a developer adds an 11th entry to `ENTITY_TYPES` without removing one
- **THEN** the module raises an `AssertionError` at import time

### Requirement: Seven domain-specific relationship families
The system SHALL define exactly 7 relationship families: `ownership`, `investment`, `role`, `deal_network`, `affinity`, `life_event`, `location`. Each family SHALL have at most 8 canonical predicates. The system SHALL enforce this limit at import time via assertion.

#### Scenario: All families are present
- **WHEN** the ontology module is imported
- **THEN** `RELATIONSHIP_FAMILIES` contains exactly the 7 families listed above

#### Scenario: Family exceeding 8 predicates fails at import
- **WHEN** a developer adds a 9th predicate to the `ownership` family
- **THEN** the module raises an `AssertionError` at import time

### Requirement: Each entity type has domain rationale and relevance floor
Each entity type definition SHALL include a `rationale` string explaining why the type earns its place in a sports-deal KG, a `keywords` list for classification hints, and a `relevance_floor` score (0.0-1.0) below which entities of that type are pruning candidates.

#### Scenario: Person type has low relevance floor
- **WHEN** the `person` entity type spec is accessed
- **THEN** its `relevance_floor` is 0.4 (person relevance is proven by relationships, not type alone)

#### Scenario: Transaction event type has high relevance floor
- **WHEN** the `transaction_event` entity type spec is accessed
- **THEN** its `relevance_floor` is 0.7 (transaction events must be clearly identified to earn KG inclusion)

### Requirement: Canonical predicates have signal level classification
Each canonical predicate SHALL be classified as `HIGH`, `MEDIUM`, or `LOW` signal via a `SignalLevel` enum. HIGH-signal predicates directly surface deal opportunities. MEDIUM-signal predicates provide supporting context. LOW-signal predicates are noise for the private banking use case.

#### Scenario: Ownership predicates are HIGH signal
- **WHEN** the `owns` predicate spec in the `ownership` family is inspected
- **THEN** its signal level is `SignalLevel.HIGH`

#### Scenario: Coaching is LOW signal
- **WHEN** the `coaches` predicate spec in the `role` family is inspected
- **THEN** its signal level is `SignalLevel.LOW`

#### Scenario: Fan affinity is MEDIUM signal
- **WHEN** the `fan_of` predicate spec in the `affinity` family is inspected
- **THEN** its signal level is `SignalLevel.MEDIUM`

### Requirement: Symmetric predicate annotation
Each predicate spec SHALL include a `symmetric` boolean indicating whether the relationship is bidirectional (A→B implies B→A). This replaces the hardcoded `symmetric_families = {"partnership"}` check.

#### Scenario: co_owns is symmetric
- **WHEN** the `co_owns` predicate spec in the `ownership` family is inspected
- **THEN** its `symmetric` attribute is `True`

#### Scenario: owns is not symmetric
- **WHEN** the `owns` predicate spec in the `ownership` family is inspected
- **THEN** its `symmetric` attribute is `False`

### Requirement: Variant mapping dictionary per family
Each relationship family SHALL include a `variants` dictionary that maps common synonym strings to their canonical predicate name. This is the exhaustive set of allowed synonyms.

#### Scenario: "buys" maps to "owns"
- **WHEN** the `ownership` family's `variants` dict is queried for `"buys"`
- **THEN** it returns `"owns"`

#### Scenario: "purchased" maps to "owns"
- **WHEN** the `ownership` family's `variants` dict is queried for `"purchased"`
- **THEN** it returns `"owns"`

#### Scenario: "committed_capital_to" maps to "invested_in"
- **WHEN** the `investment` family's `variants` dict is queried for `"committed_capital_to"`
- **THEN** it returns `"invested_in"`

### Requirement: Anti-explosion rules dataclass
The system SHALL define an `AntiExplosionRules` frozen dataclass with hard limits: `max_entity_types` (10), `max_predicates_per_family` (8), `global_relationship_confidence_floor` (0.50), `max_entities_per_type_per_team` (500), `max_predicates_per_entity_pair` (3), `min_high_signal_rels_to_retain` (1), `relationship_staleness_days` (730).

#### Scenario: Anti-explosion rules are structurally correct
- **WHEN** `ANTI_EXPLOSION_RULES` is accessed
- **THEN** all fields have the values specified above and the dataclass is frozen (immutable)

### Requirement: Legacy family migration map
The system SHALL provide a `LEGACY_FAMILY_MAP` dict and `translate_legacy_predicate()` function that maps old 5-family schema names to new 7-family names: `employment`→`role`, `transaction`→`investment`, `partnership`→`deal_network`, `ownership`→`ownership`, `location`→`location`.

#### Scenario: Legacy employment predicate is translated
- **WHEN** `translate_legacy_predicate("ceo_of", "employment")` is called
- **THEN** it returns `("ceo_of", "role")`

#### Scenario: Legacy transaction predicate is translated
- **WHEN** `translate_legacy_predicate("invested_in", "transaction")` is called
- **THEN** it returns `("invested_in", "investment")`

### Requirement: LLM prompt generation helpers
The system SHALL provide `get_entity_types_prompt()`, `get_canonical_predicates_prompt()`, and `get_lm_prompt_section()` functions that generate structured prompt sections for the LLM extraction call. `get_canonical_predicates_prompt()` SHALL only list HIGH and MEDIUM signal predicates (LOW-signal predicates are omitted to suppress LLM generation of noise).

#### Scenario: LOW-signal predicates are not in prompt
- **WHEN** `get_canonical_predicates_prompt()` is called
- **THEN** the output string does not contain `coaches` or `competes_with` or `attended_event`

#### Scenario: Entity types prompt lists all 10 types
- **WHEN** `get_entity_types_prompt()` is called
- **THEN** the output string contains all 10 entity type names

#### Scenario: Combined prompt includes both sections
- **WHEN** `get_lm_prompt_section()` is called
- **THEN** the output contains both entity type constraints and predicate constraints

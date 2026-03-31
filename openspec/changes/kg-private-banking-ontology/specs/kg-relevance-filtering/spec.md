## ADDED Requirements

### Requirement: Three-tier relationship relevance filtering
The system SHALL classify every (family, signal_level) combination into one of three tiers: `keep` (store if confidence >= family-specific floor), `conditional` (store only if confidence >= 0.70-0.75), `drop` (never store regardless of confidence). The tier mapping SHALL be defined in a `RELEVANCE_RULES` dictionary keyed by `(family_name, SignalLevel)`.

#### Scenario: HIGH-signal ownership relationship is kept
- **WHEN** a relationship with family `ownership`, predicate `owns`, confidence 0.55 is evaluated
- **THEN** `should_keep_relationship()` returns `True` (above the 0.50 floor for HIGH ownership)

#### Scenario: HIGH-signal relationship below confidence floor is dropped
- **WHEN** a relationship with family `ownership`, predicate `owns`, confidence 0.30 is evaluated
- **THEN** `should_keep_relationship()` returns `False` (below global confidence floor 0.50)

#### Scenario: MEDIUM-signal affinity relationship requires higher confidence
- **WHEN** a relationship with family `affinity`, predicate `fan_of`, confidence 0.65 is evaluated
- **THEN** `should_keep_relationship()` returns `False` (affinity MEDIUM requires 0.75)

#### Scenario: MEDIUM-signal affinity relationship with sufficient confidence is kept
- **WHEN** a relationship with family `affinity`, predicate `fan_of`, confidence 0.80 is evaluated
- **THEN** `should_keep_relationship()` returns `True`

#### Scenario: LOW-signal relationship is always dropped
- **WHEN** a relationship with family `role`, predicate `coaches`, confidence 0.99 is evaluated
- **THEN** `should_keep_relationship()` returns `False`

#### Scenario: Unknown family is rejected
- **WHEN** a relationship with family `unknown_family`, any predicate, any confidence is evaluated
- **THEN** `should_keep_relationship()` returns `False`

#### Scenario: Unknown predicate is rejected
- **WHEN** a relationship with a valid family but unknown predicate is evaluated
- **THEN** `should_keep_relationship()` returns `False`

### Requirement: Global confidence floor
The system SHALL enforce a global confidence floor of 0.50 below which ALL relationships are dropped regardless of signal level or family.

#### Scenario: Any relationship below 0.50 is dropped
- **WHEN** a relationship with confidence 0.45 is evaluated by `should_keep_relationship()`
- **THEN** it returns `False` regardless of family or signal level

### Requirement: Entity relevance scoring
The system SHALL compute an entity relevance score using the formula: `base_score (from entity type relevance_floor) + 0.20 per HIGH-signal relationship (max +0.40) + 0.10 per MEDIUM-signal relationship (max +0.20) - 0.10 if entity has ONLY LOW-signal relationships`. Score is capped at 1.0. Entities scoring below `ENTITY_RELEVANCE_FLOOR` (0.40) are pruning candidates.

#### Scenario: Person with two HIGH-signal relationships scores well
- **WHEN** `score_entity_relevance("person", high_signal_rel_count=2, medium_signal_rel_count=0)` is called
- **THEN** it returns 0.80 (base 0.4 + 2*0.20)

#### Scenario: Location with only LOW-signal relationships scores poorly
- **WHEN** `score_entity_relevance("location", high_signal_rel_count=0, medium_signal_rel_count=0, low_signal_only=True)` is called
- **THEN** it returns 0.20 (base 0.3 - 0.10 penalty) which is below the 0.40 floor

#### Scenario: Unknown entity type scores zero
- **WHEN** `score_entity_relevance("product", high_signal_rel_count=5, medium_signal_rel_count=5)` is called
- **THEN** it returns 0.0

### Requirement: Entity keep/drop decision
The system SHALL provide `should_keep_entity()` that returns `True` only if the entity type is in `ALLOWED_ENTITY_TYPE_NAMES` AND its relevance score is at or above `ENTITY_RELEVANCE_FLOOR` (0.40).

#### Scenario: Person with one HIGH relationship is kept
- **WHEN** `should_keep_entity("person", high_signal_rel_count=1, medium_signal_rel_count=0)` is called
- **THEN** it returns `True`

#### Scenario: Invalid entity type is dropped
- **WHEN** `should_keep_entity("product", high_signal_rel_count=10, medium_signal_rel_count=10)` is called
- **THEN** it returns `False`

### Requirement: Extraction pipeline integrates relevance filtering
The `_process_message()` function in `entity_extraction.py` SHALL apply relevance filtering after predicate normalization. Filtered relationships SHALL be counted in the return dict as `filtered_by_relevance`. The function SHALL also count `filtered_by_unknown_predicate` for relationships where normalization returns `None`.

#### Scenario: LOW-signal relationship is filtered during extraction
- **WHEN** the LLM extracts a relationship with predicate "coaches" and family "role"
- **THEN** the relationship is normalized, `should_keep_relationship()` returns `False`, the relationship is not stored, and `filtered_by_relevance` counter increments

#### Scenario: Unknown predicate is filtered during extraction
- **WHEN** the LLM extracts a relationship with predicate "random_verb" that cannot be normalized
- **THEN** `normalize_predicate()` returns `None`, the relationship is not stored, and `filtered_by_unknown_predicate` counter increments

#### Scenario: Return dict includes filter counters
- **WHEN** extraction completes for a document
- **THEN** the return dict includes keys `filtered_by_relevance` and `filtered_by_unknown_predicate` alongside existing `entities`, `relationships`, and `skipped_duplicates`

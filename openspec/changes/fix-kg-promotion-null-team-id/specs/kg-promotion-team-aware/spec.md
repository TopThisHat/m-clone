## ADDED Requirements

### Requirement: Promotion inserts use master team UUID
The promotion workflow SHALL use `settings.kg_master_team_id` as the `team_id` value when inserting or querying master graph entities and relationships. The workflow SHALL NOT use NULL for `team_id` in any SQL statement.

#### Scenario: Entity promoted to master graph
- **WHEN** a team entity is promoted to the master graph via `promote_entity_to_master()`
- **THEN** the INSERT into `kg_entities` SHALL set `team_id` to `settings.kg_master_team_id`
- **AND** the ON CONFLICT clause SHALL match the index signature `(LOWER(name), team_id)`

#### Scenario: Checking if entity already exists in master
- **WHEN** the promotion workflow checks for an existing master entity
- **THEN** the WHERE clause SHALL use `team_id = $N::uuid` with the master team UUID
- **AND** SHALL NOT use `team_id IS NULL`

#### Scenario: Relationship promoted to master graph
- **WHEN** a team relationship is promoted to the master graph via `promote_relationships_to_master()`
- **THEN** the INSERT into `kg_relationships` SHALL set `team_id` to `settings.kg_master_team_id`

#### Scenario: Checking for existing master relationship
- **WHEN** the promotion workflow checks for an existing active master relationship
- **THEN** the WHERE clause SHALL use `team_id = $N::uuid` with the master team UUID
- **AND** SHALL NOT use `team_id IS NULL`

### Requirement: Master team ID sourced from configuration
The promotion workflow SHALL import the master team ID from `app.config.settings.kg_master_team_id`. The value SHALL be passed as a bound SQL parameter, not interpolated into query strings.

#### Scenario: Configuration import
- **WHEN** `promote_entity_to_master()` or `promote_relationships_to_master()` executes
- **THEN** the master team ID SHALL be read from `settings.kg_master_team_id`
- **AND** SHALL be passed to SQL queries as a positional parameter with `::uuid` cast

### Requirement: Metadata parameter uses correct type cast
The entity promotion INSERT SHALL cast the metadata parameter as `::jsonb` to match the column type.

#### Scenario: Entity inserted with metadata
- **WHEN** a new master entity is created via INSERT
- **THEN** the metadata parameter SHALL use `$N::jsonb` cast in the SQL

### Requirement: Eligibility query enforces promotion thresholds
The `run_promotion_for_team()` function SHALL filter candidate entities by both `PROMOTION_CONFIDENCE_THRESHOLD` (0.85) and `PROMOTION_SESSION_MINIMUM` (2) as documented in the module docstring.

#### Scenario: Entity below confidence threshold
- **WHEN** a team entity has confidence < 0.85
- **THEN** the entity SHALL NOT appear in the eligibility results

#### Scenario: Entity below session minimum
- **WHEN** a team entity has been seen in fewer than 2 research sessions
- **THEN** the entity SHALL NOT appear in the eligibility results

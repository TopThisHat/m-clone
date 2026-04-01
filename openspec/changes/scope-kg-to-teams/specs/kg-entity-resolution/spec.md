## ADDED Requirements

### Requirement: Team-first entity resolution order
The `db_find_or_create_entity` function SHALL resolve entities in the following order: (1) exact name match within team scope, (2) alias match within team scope, (3) exact name match in master scope with copy-to-team, (4) create new team-scoped entity. The function SHALL NOT search across non-master teams.

#### Scenario: Entity found in team scope by name
- **WHEN** Team A already has entity "Apple" and extraction resolves "Apple" for Team A
- **THEN** the existing Team A entity SHALL be returned with resolution mode "team_hit"

#### Scenario: Entity found in team scope by alias
- **WHEN** Team A has entity "Apple Inc." with alias "apple" and extraction resolves "Apple" for Team A
- **THEN** the existing Team A entity SHALL be returned with resolution mode "team_alias_hit"

#### Scenario: Entity found in master scope — copied to team
- **WHEN** Team A has no entity "Apple" but master team has entity "Apple", and extraction resolves "Apple" for Team A
- **THEN** a new team-scoped entity SHALL be created as a copy with `master_entity_id` set to the master entity's id, and returned with resolution mode "master_copy"

#### Scenario: Entity not found anywhere — created new
- **WHEN** neither Team A nor master team has entity "Apple" and extraction resolves "Apple" for Team A
- **THEN** a new team-scoped entity SHALL be created with resolution mode "created"

### Requirement: Resolution mode return value
The `db_find_or_create_entity` function SHALL return a `tuple[str, str]` where the first element is the entity UUID and the second is the resolution mode string (`team_hit`, `team_alias_hit`, `master_copy`, or `created`).

#### Scenario: Caller receives resolution mode
- **WHEN** `db_find_or_create_entity` is called during extraction
- **THEN** the caller SHALL receive both the entity_id and resolution_mode, enabling logging and flagging

### Requirement: team_id required parameter
The `team_id` parameter on `db_find_or_create_entity` SHALL be required (not optional). Callers MUST provide a team_id for every entity resolution call.

#### Scenario: Call without team_id raises error
- **WHEN** `db_find_or_create_entity` is called without team_id
- **THEN** the function SHALL raise a TypeError (required argument missing)

### Requirement: Concurrent extraction safety
The entity resolution function SHALL handle concurrent extraction workers resolving the same entity for the same team using `ON CONFLICT (LOWER(name), team_id) DO UPDATE` to prevent race conditions.

#### Scenario: Two workers resolve same entity simultaneously
- **WHEN** two extraction workers both try to create entity "Apple" for Team A at the same time
- **THEN** exactly one entity record SHALL be created; the second worker's insert SHALL hit ON CONFLICT and update aliases/timestamps

### Requirement: Resolution mode logging
The entity extraction worker SHALL log the resolution mode for every resolved entity using structured logging: `entity_resolved session=<id> team=<id> entity=<name> mode=<mode> id=<uuid>`.

#### Scenario: Master copy logged
- **WHEN** extraction resolves an entity as a master copy
- **THEN** the worker SHALL emit an INFO-level log line with `mode=master_copy`

### Requirement: Relationship dedup includes team scope
The `db_upsert_relationship` function SHALL include `AND team_id = $N::uuid` in the existing-relationship check query. Team A's relationships SHALL NOT be considered duplicates of Team B's relationships.

#### Scenario: Same relationship in two teams
- **WHEN** Team A has relationship "Apple OWNS Beats" and Team B tries to create the same
- **THEN** Team B's relationship SHALL be created as "new" (not "duplicate"), because the dedup check is team-scoped

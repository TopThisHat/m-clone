## ADDED Requirements

### Requirement: Entity flags table
The system SHALL create a `kg_entity_flags` table with columns: id (UUID PK), entity_id (FK to kg_entities), team_id (FK to teams), reason (TEXT), resolved (BOOLEAN), resolved_by (FK to users), resolved_at (TIMESTAMPTZ), created_at (TIMESTAMPTZ). The table SHALL have a unique constraint on `(entity_id, team_id, reason)`.

#### Scenario: Flag created for master-sourced entity
- **WHEN** an entity is created as a copy from master during extraction
- **THEN** a flag record SHALL be inserted with reason "sourced_from_master" and resolved = FALSE

### Requirement: Auto-flagging during extraction
The entity extraction pipeline SHALL automatically create a flag when `db_find_or_create_entity` returns resolution mode "master_copy". The flag function `db_flag_entity_for_review(entity_id, team_id, reason)` SHALL be called by the extraction worker.

#### Scenario: Extraction creates master copy flag
- **WHEN** the extraction worker resolves entity "Apple" as a master copy for Team A
- **THEN** `db_flag_entity_for_review` SHALL be called with entity_id, Team A's id, and reason "sourced_from_master"

#### Scenario: Duplicate flag prevented
- **WHEN** a flag already exists for entity_id + team_id + reason
- **THEN** the insert SHALL use ON CONFLICT DO NOTHING and not create a duplicate

### Requirement: Flag listing endpoint
The system SHALL provide `GET /api/kg/entities/flags?team_id=<uuid>` to list unresolved entity flags for a team. The response SHALL include entity details (name, type) alongside flag metadata.

#### Scenario: List pending flags for team
- **WHEN** Team A has 5 unresolved flags and 3 resolved flags
- **THEN** the endpoint SHALL return only the 5 unresolved flags

#### Scenario: Cross-team flag isolation
- **WHEN** Team A queries flags and Team B has 10 unresolved flags
- **THEN** Team A SHALL see zero of Team B's flags

### Requirement: Flag resolution
The system SHALL support resolving flags via `PATCH /api/kg/entities/flags/{flag_id}` with body `{resolved: true}`. Resolution SHALL record the user's sid and timestamp.

#### Scenario: Admin resolves a flag
- **WHEN** a Team A admin marks a flag as resolved
- **THEN** the flag's `resolved` SHALL be TRUE, `resolved_by` SHALL be the admin's sid, and `resolved_at` SHALL be the current timestamp

### Requirement: Pending flag index
The database SHALL have a partial index `(team_id, resolved) WHERE resolved = FALSE` on the `kg_entity_flags` table for efficient pending-flag queries.

#### Scenario: Pending flag query uses index
- **WHEN** querying `SELECT * FROM kg_entity_flags WHERE team_id = $1 AND resolved = FALSE`
- **THEN** the query planner SHALL use the partial index for efficient lookup

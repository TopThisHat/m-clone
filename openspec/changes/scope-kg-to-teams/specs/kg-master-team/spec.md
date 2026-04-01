## ADDED Requirements

### Requirement: Master team bootstrap
The system SHALL create a dedicated master team with a fixed UUID (`00000000-0000-0000-0000-000000000001`) during schema migration. The UUID SHALL be configurable via the `KG_MASTER_TEAM_ID` environment variable.

#### Scenario: Master team created on migration
- **WHEN** the schema migration runs
- **THEN** a team row with slug `master-kg` and the configured master UUID SHALL exist in the `teams` table

#### Scenario: Master team UUID configurable
- **WHEN** the `KG_MASTER_TEAM_ID` environment variable is set to a custom UUID
- **THEN** the system SHALL use that UUID as the master team identifier in all KG operations

### Requirement: NULL entity migration to master team
The system SHALL migrate all existing `kg_entities` rows with `team_id IS NULL` to `team_id = KG_MASTER_TEAM_ID` during migration.

#### Scenario: NULL entities become master entities
- **WHEN** the migration runs on a database with 100 entities where team_id IS NULL
- **THEN** all 100 entities SHALL have `team_id = KG_MASTER_TEAM_ID` after migration

### Requirement: NULL relationship migration to master team
The system SHALL migrate all existing `kg_relationships` rows with `team_id IS NULL` to `team_id = KG_MASTER_TEAM_ID` during migration.

#### Scenario: NULL relationships become master relationships
- **WHEN** the migration runs on a database with relationships where team_id IS NULL
- **THEN** all such relationships SHALL have `team_id = KG_MASTER_TEAM_ID` after migration

### Requirement: Master entity provenance tracking
The system SHALL add a `master_entity_id UUID REFERENCES kg_entities(id) ON DELETE SET NULL` column to `kg_entities`. This FK links team-scoped entity copies to their master source.

#### Scenario: Team copy links to master entity
- **WHEN** a team entity is created as a copy of a master entity
- **THEN** the team entity's `master_entity_id` SHALL point to the master entity's id

#### Scenario: Master entity deleted — team copies become independent
- **WHEN** a super admin deletes a master entity that has team copies
- **THEN** all team copies SHALL have their `master_entity_id` set to NULL (ON DELETE SET NULL), and the team copies SHALL continue to exist independently

### Requirement: Master team protection
The master team SHALL be protected from standard team operations. Regular team management actions (delete team, add member via standard flow) SHALL be blocked for the master team.

#### Scenario: Regular user cannot access master team graph
- **WHEN** a non-super-admin user passes the master team UUID as team_id
- **THEN** the system SHALL return 403 Forbidden

#### Scenario: Super admin can access master team graph
- **WHEN** a super admin passes the master team UUID as team_id
- **THEN** the system SHALL return the master graph data normally

## ADDED Requirements

### Requirement: Entity uniqueness scoped by team
The system SHALL enforce entity name uniqueness per team via a unique index on `(LOWER(name), team_id)`. Two teams MAY have entities with the same name without constraint violations. The COALESCE-based sentinel index SHALL be dropped and replaced.

#### Scenario: Two teams create entity with same name
- **WHEN** Team A creates entity "Apple" and Team B creates entity "Apple"
- **THEN** both entities are created successfully with distinct UUIDs, each scoped to their respective team

#### Scenario: Same team creates duplicate entity name
- **WHEN** Team A creates entity "Apple" and then tries to create another entity "Apple"
- **THEN** the system SHALL upsert (update aliases, updated_at) via ON CONFLICT rather than creating a duplicate

### Requirement: Relationship uniqueness scoped by team
The system SHALL enforce relationship uniqueness per team via a unique index on `(subject_id, object_id, predicate_family, team_id) WHERE is_active = TRUE`. The existing non-team-scoped `kg_rel_active_family_idx` SHALL be dropped and replaced.

#### Scenario: Two teams create same relationship pattern
- **WHEN** Team A creates relationship "Apple OWNS Beats" and Team B creates relationship "Apple OWNS Beats" (using their own team-scoped entity UUIDs)
- **THEN** both relationships are created successfully, each scoped to their respective team

### Requirement: Intra-team relationship enforcement
The system SHALL enforce that both endpoints (subject_id, object_id) of any relationship belong to the same team as the relationship itself. This SHALL be enforced via a PostgreSQL CHECK constraint using a function `kg_rel_team_check(subject_id, object_id, team_id)`.

#### Scenario: Relationship with cross-team endpoints rejected
- **WHEN** a caller attempts to insert a relationship where subject_id belongs to Team A and object_id belongs to Team B
- **THEN** the database SHALL raise a CheckViolationError and the insert SHALL fail

#### Scenario: Valid intra-team relationship accepted
- **WHEN** a caller inserts a relationship where subject_id, object_id, and team_id all reference the same team
- **THEN** the relationship is inserted successfully

### Requirement: team_id NOT NULL enforcement
The system SHALL enforce `team_id NOT NULL` on `kg_entities` and `kg_relationships` tables. No entity or relationship MAY exist without a team assignment.

#### Scenario: Insert entity without team_id
- **WHEN** a caller attempts to insert a kg_entity with team_id = NULL
- **THEN** the database SHALL reject the insert with a NOT NULL violation

### Requirement: Team deletion guard for KG data
The system SHALL use `ON DELETE RESTRICT` on the team FK for `kg_entities` and `kg_relationships`. Team deletion SHALL be blocked if the team has any KG data.

#### Scenario: Delete team with existing KG entities
- **WHEN** a super admin attempts to delete a team that has KG entities
- **THEN** the deletion SHALL fail with a foreign key restriction error

#### Scenario: Delete team with no KG data
- **WHEN** a super admin deletes a team that has zero KG entities and zero KG relationships
- **THEN** the deletion succeeds

### Requirement: Team-scoped relationship conflict tracking
The system SHALL add `team_id` to the `kg_relationship_conflicts` table. Conflict records SHALL be scoped to the team that owns the conflicting relationships.

#### Scenario: Conflict visibility restricted to team
- **WHEN** Team A has 3 conflicts and Team B has 5 conflicts
- **THEN** a Team A admin querying conflicts SHALL see only Team A's 3 conflicts

### Requirement: Team-scoped mutation queries
All KG mutation queries (UPDATE, DELETE) SHALL include `AND team_id = $N::uuid` in their WHERE clause, enforcing team scope at the database layer in addition to router-level authorization.

#### Scenario: Update entity enforces team scope
- **WHEN** `db_update_kg_entity` is called with entity_id and team_id
- **THEN** the UPDATE query SHALL include `AND team_id = $N::uuid` to prevent cross-team modifications

#### Scenario: Delete entity enforces team scope
- **WHEN** `db_delete_kg_entity` is called with entity_id and team_id
- **THEN** the DELETE query SHALL include `AND team_id = $N::uuid` and only delete the entity if it belongs to the specified team

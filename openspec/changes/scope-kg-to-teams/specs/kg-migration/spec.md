## ADDED Requirements

### Requirement: Migration runs without downtime
The migration SHALL be executable on a running production database without requiring application downtime for steps 1-7 and 10-13. Steps 8-9 (index recreation) SHALL use `CREATE INDEX CONCURRENTLY` where possible to minimize lock duration.

#### Scenario: Application serves requests during migration steps 1-7
- **WHEN** migration steps 1 through 7 are executed
- **THEN** the application SHALL continue serving KG API requests without errors

### Requirement: Pre-migration duplicate detection
Before executing the unique index migration (step 8), the migration SHALL detect and resolve duplicate entity names within the same team scope (including NULL team_id rows that will become master). Duplicates SHALL be merged by keeping the entity with the most relationships and adding the other's name to aliases.

#### Scenario: Duplicate NULL entities detected
- **WHEN** two entities named "Apple" both have team_id IS NULL
- **THEN** the pre-migration check SHALL merge them into one entity before applying the unique index

### Requirement: Step ordering enforcement
The migration steps SHALL be executed in the defined order (1 through 13). Steps 1-4 (schema additions) SHALL run before steps 5-7 (data backfill), which SHALL run before steps 8-9 (index replacement).

#### Scenario: Indexes dropped before data migration causes failure
- **WHEN** an operator attempts to run step 8 before step 5
- **THEN** the new unique index creation SHALL fail because NULL team_id rows violate the non-COALESCE index

### Requirement: Rollback capability for reversible steps
Steps 1-7 and 10-11 SHALL be individually reversible. The migration script SHALL document the exact rollback SQL for each step.

#### Scenario: Rollback step 5 (entity migration)
- **WHEN** an operator needs to rollback step 5
- **THEN** executing `UPDATE kg_entities SET team_id = NULL WHERE team_id = KG_MASTER_TEAM_ID AND master_entity_id IS NULL` SHALL restore the pre-migration state

### Requirement: Conflict table backfill accuracy
The migration SHALL backfill `kg_relationship_conflicts.team_id` from the associated relationship's team_id. Conflicts that cannot be linked to a relationship SHALL default to `KG_MASTER_TEAM_ID`.

#### Scenario: Conflict linked to team relationship
- **WHEN** a conflict references a relationship with team_id = Team-A
- **THEN** the conflict's team_id SHALL be set to Team-A's id

#### Scenario: Orphaned conflict defaults to master
- **WHEN** a conflict cannot be linked to any existing relationship
- **THEN** the conflict's team_id SHALL be set to KG_MASTER_TEAM_ID

### Requirement: NOT NULL enforcement deferred
Step 12 (`ALTER TABLE ... SET NOT NULL`) SHALL be run as a separate migration after production data has been validated to contain zero NULL team_id values. The validation query SHALL be: `SELECT COUNT(*) FROM kg_entities WHERE team_id IS NULL`.

#### Scenario: NOT NULL applied after validation
- **WHEN** the validation query returns 0
- **THEN** the NOT NULL constraint SHALL be applied successfully

#### Scenario: NOT NULL blocked by remaining NULLs
- **WHEN** the validation query returns > 0
- **THEN** the operator SHALL investigate and fix remaining NULLs before applying NOT NULL

### Requirement: Performance indexes created concurrently
Step 13 performance indexes SHALL be created using `CREATE INDEX CONCURRENTLY` to avoid blocking writes during index builds.

#### Scenario: Index creation does not block inserts
- **WHEN** step 13 creates the team_name, team_type, and team_updated indexes
- **THEN** concurrent entity and relationship inserts SHALL not be blocked

## ADDED Requirements

### Requirement: Master team ID endpoint
The system SHALL provide `GET /api/kg/master-team-id` that returns `{"team_id": "<master_uuid>"}`. This endpoint SHALL NOT require authentication so frontend clients can discover the master team UUID.

#### Scenario: Client retrieves master team ID
- **WHEN** any client calls GET /api/kg/master-team-id
- **THEN** the response SHALL contain the configured KG_MASTER_TEAM_ID value

### Requirement: Entity promotion endpoint
The system SHALL provide `POST /api/kg/entities/{entity_id}/promote?team_id=<uuid>` to promote a team entity to the master graph. This SHALL require admin+ role on the team or super admin.

#### Scenario: Promote entity to master
- **WHEN** a Team A admin promotes entity "Apple" to master
- **THEN** a master entity SHALL be created (or updated if already exists), and the team entity's `master_entity_id` SHALL be set to the master entity's id

#### Scenario: Non-admin cannot promote
- **WHEN** a Team A member (non-admin) attempts to promote an entity
- **THEN** the system SHALL return 403 Forbidden

### Requirement: Sync from master endpoint
The system SHALL provide `POST /api/kg/entities/{entity_id}/sync-from-master?team_id=<uuid>` to re-sync a team entity's data from its master source. This SHALL require admin+ role.

#### Scenario: Sync team copy from updated master
- **WHEN** a team entity has `master_entity_id` set and the admin triggers sync
- **THEN** the team entity's name, entity_type, aliases, and description SHALL be updated from the master entity's current values

#### Scenario: Sync entity without master link
- **WHEN** sync is called on an entity with `master_entity_id = NULL`
- **THEN** the system SHALL return 400 Bad Request with detail "Entity has no master link"

### Requirement: Entity merge endpoint
The system SHALL provide `POST /api/kg/entities/merge` accepting `{winner_id, loser_id, team_id}`. The merge SHALL move all relationships from loser to winner, add loser's name to winner's aliases, and delete the loser entity. This SHALL require admin+ role.

#### Scenario: Merge two entities within same team
- **WHEN** admin merges entity B (loser) into entity A (winner) in Team A
- **THEN** all of B's relationships SHALL have their subject_id/object_id updated to A's id, B's name SHALL be added to A's aliases, and B SHALL be deleted

#### Scenario: Cross-team merge rejected
- **WHEN** a caller attempts to merge an entity from Team A with an entity from Team B
- **THEN** the system SHALL return 400 Bad Request

### Requirement: include_master parameter removal
The `include_master` boolean parameter SHALL be removed from all DB functions and router helper functions. Master graph access SHALL be handled by passing `KG_MASTER_TEAM_ID` as the `team_id` parameter.

#### Scenario: Function signatures updated
- **WHEN** `db_list_kg_entities` is called
- **THEN** the function SHALL accept `team_id: str` (required) and SHALL NOT accept an `include_master` parameter

### Requirement: Simplified team access resolution
The `_resolve_team_access` function SHALL return a single `str` (resolved team_id) instead of `tuple[str | None, bool]`. Master team access SHALL require super admin status.

#### Scenario: Regular user resolves to their team
- **WHEN** a regular user with team_id=Team-A calls a KG endpoint
- **THEN** `_resolve_team_access` SHALL return Team-A's id

#### Scenario: Super admin accesses master
- **WHEN** a super admin passes team_id=KG_MASTER_TEAM_ID
- **THEN** `_resolve_team_access` SHALL return the master team UUID

#### Scenario: Regular user blocked from master
- **WHEN** a non-super-admin passes team_id=KG_MASTER_TEAM_ID
- **THEN** the system SHALL return 403

### Requirement: Team-scoped conflicts endpoint
The `GET /api/kg/conflicts` endpoint SHALL require team_id and return only conflicts belonging to the specified team. The `include_master` parameter SHALL be removed.

#### Scenario: Team admin sees only team conflicts
- **WHEN** Team A admin queries conflicts
- **THEN** only conflicts with team_id matching Team A SHALL be returned

### Requirement: Team-scoped stats endpoint
The `GET /api/kg/stats` endpoint SHALL accept a required team_id and return statistics scoped to that team only. The relationship count subquery SHALL filter by team_id.

#### Scenario: Stats reflect team-only data
- **WHEN** Team A has 50 entities and 100 relationships, and the master team has 500 entities
- **THEN** stats for Team A SHALL show 50 entities and 100 relationships (not 550 entities)

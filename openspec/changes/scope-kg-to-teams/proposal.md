## Why

The Knowledge Graph was built globally and progressively retrofitted for team scoping via ALTER TABLE migrations. The result has three critical bugs: (1) the entity unique index uses a `COALESCE(team_id, nil_uuid)` sentinel hack that is structurally dishonest, (2) the relationship unique index omits `team_id` entirely — meaning Team B silently inherits Team A's relationships when both reference the same master entity UUID, and (3) `db_delete_kg_entity` has no team guard at the DB layer, so a team admin can delete a master entity and cascade-destroy every other team's relationships. When Team A creates entity "Apple" and Team B processes a document about "Apple", Team B gets constraint violations or silent data merging. Entities and relationships must be unique per team, not globally.

## What Changes

- **Explicit master team**: Replace the NULL `team_id` sentinel with a dedicated master team row (fixed UUID from env var `KG_MASTER_TEAM_ID`). All currently NULL-team entities are migrated to this master team. `team_id` becomes `NOT NULL` on `kg_entities` and `kg_relationships`. **BREAKING**: `team_id` parameter is now required (not optional) on all KG write functions.
- **Clean unique indexes**: Drop the COALESCE-based `kg_entities_name_team_unique` index and replace with a clean `(LOWER(name), team_id)` index. Drop the non-team-scoped `kg_rel_active_family_idx` and replace with `(subject_id, object_id, predicate_family, team_id) WHERE is_active = TRUE`.
- **Intra-team relationship enforcement**: Add a CHECK constraint via a PG function ensuring both endpoints of any relationship belong to the same team. Cross-team relationships become structurally impossible at the DB level.
- **Master entity copy pattern**: New `master_entity_id` FK on `kg_entities`. When extraction matches a master entity, it creates a team-scoped copy linked via this FK, not a direct reference. Team copies are independent — master updates do not auto-propagate.
- **Entity review flags**: New `kg_entity_flags` table tracks entities needing user review (e.g., entities auto-copied from master during extraction). Frontend surfaces "N entities pending review."
- **Revised entity resolution**: `db_find_or_create_entity` returns `(entity_id, resolution_mode)` tuple. Resolution order: team exact name → team alias → master copy → create new. **BREAKING**: return type changes from `str` to `tuple[str, str]`.
- **API changes**: Remove `include_master` internal parameter from all DB/router functions. Master graph is accessed by passing the master team UUID as `team_id`. New endpoints: `/promote`, `/sync-from-master`, `/merge`, `/flags`. All DB mutation queries add `AND team_id = $N::uuid` enforcement.
- **Conflict table scoping**: Add `team_id` to `kg_relationship_conflicts`. Team admins see only their team's conflicts.
- **Team deletion guard**: Change `ON DELETE SET NULL` to `ON DELETE RESTRICT` on team FK for KG tables. Team deletion blocked if KG entities exist.

## Capabilities

### New Capabilities
- `kg-team-isolation`: Database schema changes enforcing team-level entity and relationship isolation — unique indexes scoped by team_id, NOT NULL enforcement, intra-team CHECK constraint
- `kg-master-team`: Explicit master team pattern replacing NULL team_id sentinel — master team bootstrap, entity migration, master_entity_id provenance FK
- `kg-entity-resolution`: Revised entity resolution algorithm with team-first lookup, master copy pattern, and resolution mode tracking
- `kg-entity-flags`: Entity review flag system for surfacing entities that need user attention (master copies, disambiguation conflicts)
- `kg-team-api`: API endpoint changes for team-scoped KG operations — promote, sync-from-master, merge, flags endpoints; removal of include_master pattern
- `kg-migration`: 13-step database migration plan with rollback strategy for transitioning from global to team-scoped KG

### Modified Capabilities

## Impact

- **Database**: `kg_entities`, `kg_relationships`, `kg_relationship_conflicts` tables restructured. New `kg_entity_flags` table. New indexes and constraints. Migration of all NULL team_id rows.
- **Backend API**: `backend/app/routers/knowledge_graph.py` — all endpoints revised, 4 new endpoints added. `_resolve_team_access` simplified (returns single team_id, no include_master).
- **DB Layer**: `backend/app/db/knowledge_graph.py` — all CRUD functions updated for required team_id. `db_find_or_create_entity` return type changes.
- **Entity Extraction**: `backend/worker/entity_extraction.py` — `_store_extraction_result` updated to handle resolution_mode tuple and flag master copies.
- **Config**: `backend/app/config.py` — new `KG_MASTER_TEAM_ID` setting.
- **Dependencies**: `backend/app/dependencies.py` — `AgentDeps.include_master` removed, `team_ids` usage simplified.
- **Schema**: `backend/app/db/_schema.py` — migration logic for all schema changes.
- **Frontend**: KG explorer pages need to pass team_id explicitly; entity flags UI component needed (deferred to separate change).

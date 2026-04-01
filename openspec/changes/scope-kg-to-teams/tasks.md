## 1. Schema Migration — Master Team & Column Additions

- [ ] 1.1 Add `KG_MASTER_TEAM_ID` to `app/config.py` with default `00000000-0000-0000-0000-000000000001`
- [ ] 1.2 Add master team bootstrap INSERT to `_schema.py` migration (ON CONFLICT DO NOTHING)
- [ ] 1.3 Add `master_entity_id UUID REFERENCES kg_entities(id) ON DELETE SET NULL` column to `kg_entities`
- [ ] 1.4 Add `team_id UUID REFERENCES teams(id)` column to `kg_relationship_conflicts`
- [ ] 1.5 Create `kg_entity_flags` table with unique constraint `(entity_id, team_id, reason)`

## 2. Data Migration — NULL to Master Team

- [ ] 2.1 Add pre-migration duplicate detection query for NULL-team entities with same LOWER(name)
- [ ] 2.2 Add migration: `UPDATE kg_entities SET team_id = KG_MASTER_TEAM_ID WHERE team_id IS NULL`
- [ ] 2.3 Add migration: `UPDATE kg_relationships SET team_id = KG_MASTER_TEAM_ID WHERE team_id IS NULL`
- [ ] 2.4 Add migration: backfill `kg_relationship_conflicts.team_id` from associated relationships
- [ ] 2.5 Add migration: default remaining NULL conflict team_ids to KG_MASTER_TEAM_ID

## 3. Index & Constraint Migration

- [ ] 3.1 Drop COALESCE-based `kg_entities_name_team_unique` index and old `kg_entities_name_idx`
- [ ] 3.2 Create clean `kg_entities_name_team_unique` on `(LOWER(name), team_id)`
- [ ] 3.3 Drop non-team-scoped `kg_rel_active_family_idx`
- [ ] 3.4 Create team-scoped `kg_rel_active_family_team_idx` on `(subject_id, object_id, predicate_family, team_id) WHERE is_active`
- [ ] 3.5 Create `kg_rel_team_check` PG function for intra-team relationship validation
- [ ] 3.6 Add CHECK constraint `kg_rel_intra_team_check` to `kg_relationships`
- [ ] 3.7 Change FK `ON DELETE SET NULL` to `ON DELETE RESTRICT` on `kg_entities.team_id` and `kg_relationships.team_id`
- [ ] 3.8 Add NOT NULL constraint on `kg_entities.team_id` and `kg_relationships.team_id` (deferred step)
- [ ] 3.9 Create performance indexes: `(team_id, LOWER(name))`, `(team_id, entity_type)`, `(team_id, updated_at DESC)`, `(master_entity_id)`, `(team_id, subject_id)`, `(team_id, object_id)`, conflicts `(team_id, detected_at DESC)`, flags `(team_id, resolved) WHERE resolved = FALSE`

## 4. DB Layer — knowledge_graph.py Rewrite

- [ ] 4.1 Rewrite `db_find_or_create_entity` with 4-phase resolution (team name → team alias → master copy → create) returning `tuple[str, str]`
- [ ] 4.2 Add `db_flag_entity_for_review(entity_id, team_id, reason)` function
- [ ] 4.3 Add `db_list_entity_flags(team_id)` function
- [ ] 4.4 Add `db_resolve_entity_flag(flag_id, resolved_by)` function
- [ ] 4.5 Update `db_upsert_relationship` to include `AND team_id = $N::uuid` in dedup check
- [ ] 4.6 Update `db_upsert_relationship` to catch `CheckViolationError` for intra-team constraint
- [ ] 4.7 Update `db_update_kg_entity` to add `AND team_id = $N::uuid` in WHERE clause
- [ ] 4.8 Update `db_delete_kg_entity` to add `AND team_id = $N::uuid` in WHERE clause
- [ ] 4.9 Update `db_list_kg_entities` to remove `include_master` parameter, require `team_id`
- [ ] 4.10 Update `db_get_entity_relationships` to remove `include_master`, require `team_id`
- [ ] 4.11 Update `db_search_kg` to remove `include_master`, require `team_id`
- [ ] 4.12 Update `db_get_kg_stats` to remove `include_master`, require `team_id`, fix relationship count subquery to filter by team
- [ ] 4.13 Update `db_list_kg_conflicts` to remove `include_master`, require `team_id`
- [ ] 4.14 Update `db_get_kg_graph` to remove `include_master`, require `team_id`
- [ ] 4.15 Update `db_get_deal_partners` to remove `include_master`, require `team_id`
- [ ] 4.16 Update `db_find_similar_entities` to remove fallback to NULL team_id
- [ ] 4.17 Add `db_promote_entity_to_master(entity_id, team_id)` function
- [ ] 4.18 Add `db_sync_entity_from_master(entity_id, team_id)` function
- [ ] 4.19 Add `db_merge_kg_entities(winner_id, loser_id, team_id)` function

## 5. Entity Extraction Pipeline

- [ ] 5.1 Update `_store_extraction_result` to handle `tuple[str, str]` return from `db_find_or_create_entity`
- [ ] 5.2 Add resolution mode logging in `_store_extraction_result` for each resolved entity
- [ ] 5.3 Add `db_flag_entity_for_review` call when resolution_mode == "master_copy"
- [ ] 5.4 Update `_relationship_already_exists` to include team_id in dedup query

## 6. API Router — knowledge_graph.py

- [ ] 6.1 Simplify `_resolve_team_access` to return `str` instead of `tuple[str | None, bool]`
- [ ] 6.2 Add master team UUID check in `_resolve_team_access` (require super admin)
- [ ] 6.3 Update all existing endpoint handlers to use simplified `_resolve_team_access` (single team_id, no include_master)
- [ ] 6.4 Add `GET /api/kg/master-team-id` endpoint (no auth required)
- [ ] 6.5 Add `POST /api/kg/entities/{entity_id}/promote` endpoint
- [ ] 6.6 Add `POST /api/kg/entities/{entity_id}/sync-from-master` endpoint
- [ ] 6.7 Add `POST /api/kg/entities/merge` endpoint with MergeEntitiesRequest model
- [ ] 6.8 Add `GET /api/kg/entities/flags` endpoint
- [ ] 6.9 Add `PATCH /api/kg/entities/flags/{flag_id}` endpoint
- [ ] 6.10 Update `GET /api/kg/entities/{entity_id}` to pass team_id to DB layer

## 7. Dependencies & Config

- [ ] 7.1 Remove `include_master` from `AgentDeps` in `dependencies.py`
- [ ] 7.2 Update `get_agent_deps` to remove `include_master` parameter
- [ ] 7.3 Update all callers of `get_agent_deps` that pass `include_master`
- [ ] 7.4 Update `db/__init__.py` exports for new functions

## 8. Tests

- [ ] 8.1 Write isolation tests: Team A entity invisible to Team B; Team A relationship invisible to Team B
- [ ] 8.2 Write resolution mode tests: team_hit, team_alias_hit, master_copy, created
- [ ] 8.3 Write intra-team constraint test: cross-team relationship insertion fails with CheckViolationError
- [ ] 8.4 Write concurrent extraction test: two workers resolving same entity produce exactly one record
- [ ] 8.5 Write API authorization tests: regular user blocked from master team, super admin allowed
- [ ] 8.6 Write team deletion guard test: DELETE team with KG entities fails with RESTRICT
- [ ] 8.7 Write entity flag tests: auto-flag on master_copy, list/resolve flags
- [ ] 8.8 Write migration tests: NULL entities migrated, unique index works post-migration
- [ ] 8.9 Write promote/sync/merge endpoint tests
- [ ] 8.10 Write relationship dedup test: same relationship in two teams not treated as duplicate

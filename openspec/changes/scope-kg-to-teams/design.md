## Context

The KG schema was designed globally and incrementally patched for multi-tenancy. The current state:

- `kg_entities`: has `team_id` added via ALTER TABLE, with a COALESCE-based unique index `(LOWER(name), COALESCE(team_id, '00000000...'::uuid))`. NULL team_id means "master graph."
- `kg_relationships`: has `team_id` added later, but the unique index `(subject_id, object_id, predicate_family) WHERE is_active` is NOT team-scoped. Two teams referencing the same master entity UUID collide.
- `kg_relationship_conflicts`: no team_id — conflicts from all teams are co-mingled.
- `db_find_or_create_entity`: searches `(team_id = $2 OR team_id IS NULL)`, causing teams to silently inherit master entities and merge data across team boundaries.
- `db_delete_kg_entity`: no team_id guard — cascade deletes reach across teams.

A 5-expert design team (KG expert, API designer, LLM expert, Python dev, Product Owner) debated three options across 5 rounds and reached consensus on "Option C: Explicit Master Team." Full debate transcript: `docs/kg-team-scoping-design.md`.

## Goals / Non-Goals

**Goals:**
- Hard team isolation: Team A's entities are invisible to Team B, even with the same name
- Clean schema: no COALESCE hacks, no NULL sentinels, team_id NOT NULL everywhere
- Master graph as a real team: explicit, configurable UUID, accessed via standard team_id parameter
- Intra-team relationship integrity enforced at DB level (CHECK constraint)
- Master entity copy pattern with provenance tracking (master_entity_id FK)
- Entity review flags for surfacing auto-copied master entities to users
- Zero-downtime migration with rollback strategy for each step

**Non-Goals:**
- Cross-team relationships (requires separate design with dual-admin approval)
- Entity merge UI (deferred — schema supports it, endpoint added, frontend not in scope)
- Auto-propagation of master updates to team copies (explicit sync only)
- Frontend KG explorer changes (beyond passing team_id — deferred to separate change)
- KG permissions model overhaul (current admin/owner role check is sufficient)

## Decisions

### D1: Explicit master team over NULL sentinel
**Decision**: Create a real master team row with fixed UUID `00000000-0000-0000-0000-000000000001` stored in env var `KG_MASTER_TEAM_ID`. Migrate all NULL team_id rows to this team.

**Alternatives considered**:
- *Option A (strict isolation, no sharing)*: Every entity in exactly one team, no master graph. Rejected: kills the value of super-admin curated canonical entities.
- *Option B (fix indexes, keep NULL sentinel)*: Just add team_id to unique indexes with COALESCE. Rejected: papers over the structural problem; COALESCE is a PostgreSQL anti-pattern that hurts query planning.

**Rationale**: Option C gives clean schema (team_id NOT NULL, no COALESCE), preserves master graph value, and enables team-level overrides via master_entity_id FK.

### D2: Intra-team-only relationships
**Decision**: Both endpoints of any relationship MUST belong to the same team, enforced by a PG CHECK constraint function (`kg_rel_team_check`).

**Rationale**: If teams can reference master entity UUIDs directly in relationships, the relationship unique constraint still collides across teams. Intra-team-only means entity UUIDs never overlap across teams, so the unique constraint naturally isolates.

### D3: Copy-on-resolve for master entities
**Decision**: When extraction matches a master entity, create a team-scoped copy with `master_entity_id` FK pointing to the master. The team copy is independent — editable, deletable without affecting master.

**Alternatives considered**:
- *Reference model*: Team relationships point directly to master entity UUIDs. Rejected: breaks intra-team constraint, creates ownership ambiguity, cascade-delete hazard.
- *User-approval-required model*: Block extraction until user approves master match. Rejected: breaks async extraction pipeline; extraction must be fire-and-forget.

**Rationale**: Copy-on-resolve is automatic (no pipeline changes needed) and creates a clear ownership boundary. The `resolution_mode = "master_copy"` return value plus `kg_entity_flags` table lets the UI surface these for review without blocking extraction.

### D4: ON DELETE RESTRICT for team FK
**Decision**: Change `ON DELETE SET NULL` to `ON DELETE RESTRICT` on the team FK for `kg_entities` and `kg_relationships`. Team deletion is blocked if KG data exists.

**Rationale**: With team_id NOT NULL, SET NULL would violate the NOT NULL constraint anyway. RESTRICT forces admins to explicitly handle KG data before deleting a team (promote to master or delete entities).

### D5: Resolution mode return value
**Decision**: Change `db_find_or_create_entity` return type from `str` to `tuple[str, str]` where second element is the resolution mode (`team_hit`, `team_alias_hit`, `master_copy`, `created`).

**Alternatives considered**:
- *Separate tracking table*: Log resolution events in a separate table. Rejected: adds write overhead for every entity resolution.
- *Metadata field*: Store resolution mode in entity metadata JSONB. Rejected: pollutes the entity record with operational data.

**Rationale**: Return value is the lightest-weight approach. Callers that don't need the mode can destructure as `entity_id, _ = await db_find_or_create_entity(...)`.

### D6: include_master elimination
**Decision**: Remove the `include_master: bool` parameter from all DB and router functions. Master graph is accessed by passing `KG_MASTER_TEAM_ID` as the `team_id` parameter.

**Rationale**: "Master" is just another team. The include_master flag was a leaky abstraction that complicated every query. With master as a real team, standard team_id filtering handles everything.

## Risks / Trade-offs

- **[Migration risk: duplicate names after NULL→master migration]** → If two entities named "Apple" exist (one with team_id=NULL, one with team_id=some-team), the NULL one migrates to master team cleanly since they have different team_ids. But if two entities with team_id=NULL share the same LOWER(name), the new unique index will fail. → **Mitigation**: Pre-migration dedup query to merge duplicate NULL-team entities before migration.

- **[Performance: CHECK constraint on every relationship insert]** → The `kg_rel_team_check` function does two index lookups per insert. → **Mitigation**: Both lookups hit the `(team_id, id)` or `(id, team_id)` index which is O(log n). At current volumes (<100K entities), overhead is <1ms per insert. Monitor and consider deferring to DEFERRED constraints if batch insert performance degrades.

- **[Breaking change: db_find_or_create_entity return type]** → All callers must be updated to handle tuple return. → **Mitigation**: Only 2 call sites exist (entity_extraction.py `_store_extraction_result` and `_process_chunk`). Both are updated in this change.

- **[Master team as attack surface]** → The master team UUID is predictable (fixed). An attacker could try to pass it as team_id. → **Mitigation**: `_resolve_team_access` explicitly checks `if team_id == KG_MASTER_TEAM_ID: require super_admin`. No regular user can access master team.

- **[Entity copy proliferation]** → If master has 10K entities and 50 teams each process documents, worst case = 500K entity copies. → **Mitigation**: Copies are only created when extraction matches a master entity. Teams processing unique entities create no copies. The copy pattern is lazy, not eager.

## Migration Plan

13-step migration (see `docs/kg-team-scoping-design.md` for exact SQL):

| Step | Action | Reversible? | Downtime? |
|------|--------|-------------|-----------|
| 1 | Insert master team row | Yes | None |
| 2 | Add master_entity_id column | Yes (drop) | None |
| 3 | Add team_id to conflicts table | Yes (drop) | None |
| 4 | Create kg_entity_flags table | Yes (drop) | None |
| 5 | UPDATE NULL entities → master team | Yes (UPDATE back) | None |
| 6 | UPDATE NULL relationships → master team | Yes (UPDATE back) | None |
| 7 | Backfill conflict team_id | Yes | None |
| 8 | Drop old entity unique index, create clean one | No* | Brief lock |
| 9 | Drop old relationship unique index, create team-scoped | No* | Brief lock |
| 10 | Add kg_rel_team_check function + constraint | Yes (drop) | None |
| 11 | Change FK ON DELETE to RESTRICT | Yes (change back) | None |
| 12 | SET NOT NULL on team_id columns | No* | None |
| 13 | Add performance indexes (CONCURRENTLY) | Yes (drop) | None |

*Reversible with manual intervention (re-create old indexes). Take pg_dump of KG tables before starting.

Steps 1-7 and 10-13 are zero-downtime. Steps 8-9 require brief exclusive locks — use `CREATE INDEX CONCURRENTLY` where possible (note: CONCURRENTLY cannot be used inside a transaction block).

## Open Questions

- **Q1**: Should the master team appear in team-list API responses? Current recommendation: no — filter it out of `db_list_user_teams` unless the user is a super admin.
- **Q2**: Should the entity flags UI be part of this change or deferred? Current recommendation: defer frontend work, implement only the backend API endpoint.
- **Q3**: For the `POST /api/kg/entities/merge` endpoint, should we support merging entities across teams (e.g., merge team entity into master)? Current recommendation: no — intra-team only for v1.

## Context

The KG promotion workflow (`backend/worker/workflows/kg_promotion.py`) promotes high-confidence team-scoped entities and relationships to the master graph. It was written during Phase 1 when master graph entries had `team_id = NULL`.

Phase 2 migration (`backend/app/db/_schema.py` lines 1634-1700) changed the schema:
- All NULL `team_id` values migrated to `MASTER_TEAM_ID` (`00000000-0000-0000-0000-000000000001`)
- `team_id` column set to NOT NULL
- Unique index changed from `COALESCE(team_id, sentinel)` to clean `(LOWER(name), team_id)`

The promotion workflow was never updated, so every promotion attempt now fails.

## Goals / Non-Goals

**Goals:**
- Fix all 5 SQL statements in `kg_promotion.py` to use the master team UUID instead of NULL
- Align the ON CONFLICT clause with the current `kg_entities_name_team_unique` index
- Maintain the existing promotion logic (advisory locks, alias merging, conflict queue)

**Non-Goals:**
- Changing promotion thresholds or criteria
- Modifying the schema or indexes
- Adding new promotion features or API endpoints

## Decisions

### Use `settings.kg_master_team_id` instead of hardcoding the UUID

**Rationale**: The master team UUID is already centralized in `app.config.Settings.kg_master_team_id`. Other code paths (entity extraction, knowledge graph DB layer) already use this pattern. Hardcoding would create a maintenance burden.

**Alternative considered**: Hardcode `00000000-0000-0000-0000-000000000001` directly in SQL — rejected because the config is the single source of truth and other modules already depend on it.

### Import settings as function-local import (lazy-import pattern)

**Rationale**: Import `from app.config import settings` inside each function body, not at module level. This matches the existing pattern in `kg_promotion.py` where `from app.db._pool import _acquire` is imported inside function bodies. Worker modules use lazy imports to avoid circular dependency risks at startup. The value is read at call time.

**Alternative considered**: Module-level import — rejected because it is inconsistent with the lazy-import convention used throughout the `worker/` package.

### Pass master_team_id as a query parameter, not string interpolation

**Rationale**: All existing SQL in the file uses positional parameters (`$1`, `$2`, etc.). Adding `master_team_id` as an additional bound parameter maintains SQL injection safety and consistency.

## Risks / Trade-offs

- **[Low] Parameter index shift**: Adding `master_team_id` as a new parameter shifts `$N` indices in the INSERT statements. Careful to update all parameter positions **and** the Python argument lists at each call site.
  - Mitigation: Each function has a small number of parameters; review each statement end-to-end. Verify Python call site argument count matches SQL parameter count.

- **[Low] Metadata jsonb cast**: The entity INSERT was missing `::jsonb` cast on `$4` (metadata). This is a pre-existing issue that must be fixed alongside the team_id changes to prevent type mismatch errors.

- **[Low] Advisory lock still uses name hash only**: The advisory lock on `hashtext(LOWER(name))` doesn't include team_id. This is correct — the lock prevents concurrent promotions of the same-named entity from different teams, which is the desired behavior.

- **[Low] Relationship FOR UPDATE race**: The relationship lookup uses `FOR UPDATE` row lock, which doesn't protect the "no existing row" case. Two concurrent promotions of the same relationship could both pass the existence check. This is caught by the unique index (`kg_rel_active_family_idx`), so no data corruption — but the second insert would raise an exception. This is a pre-existing issue, not introduced by this fix.

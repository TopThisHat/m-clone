## Why

The KG promotion workflow (`kg_promotion.py`) was written before the Phase 2 schema migration that made `team_id` NOT NULL on `kg_entities` and `kg_relationships`. It still assumes master graph entities have `team_id = NULL`, but the master team now uses a real UUID (`00000000-0000-0000-0000-000000000001`). This causes ON CONFLICT errors and NOT NULL constraint violations whenever entity promotion runs, completely blocking the team-to-master promotion pipeline.

## What Changes

- Replace all `team_id IS NULL` checks in `kg_promotion.py` with `team_id = $N::uuid` using the master team UUID from `settings.kg_master_team_id`
- Replace all `NULL` literal inserts for `team_id` with the master team UUID parameter
- Fix `ON CONFLICT ((LOWER(name)))` to match the current unique index signature `(LOWER(name), team_id)`
- Add `::jsonb` cast to the metadata parameter in the entity INSERT (was missing, causes type mismatch)
- Fix `run_promotion_for_team()` eligibility query to enforce `PROMOTION_CONFIDENCE_THRESHOLD` and `PROMOTION_SESSION_MINIMUM` — currently defined but not applied
- Import `settings` from `app.config` in `kg_promotion.py` using function-local imports (matching existing lazy-import pattern)

## Capabilities

### New Capabilities

- `kg-promotion-team-aware`: Align the KG promotion workflow with the Phase 2 team-scoped schema where master graph uses a real team UUID instead of NULL

### Modified Capabilities

<!-- No existing spec-level requirements are changing, only implementation alignment with the current schema -->

## Impact

- **Code**: `backend/worker/workflows/kg_promotion.py` — 5 SQL fix locations (lines 68, 101-103, 171, 199) + eligibility query fix (lines 222-233)
- **Dependencies**: Requires `app.config.settings.kg_master_team_id` (already exists)
- **Database**: No schema changes needed — the index and constraints are already correct from Phase 2
- **Risk**: Low — the current code is already broken; this fix aligns it with the schema and enforces documented promotion criteria

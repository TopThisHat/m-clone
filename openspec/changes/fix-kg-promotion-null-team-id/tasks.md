## 1. Fix Entity Promotion SQL

- [ ] 1.1 Add function-local import `from app.config import settings` in `promote_entity_to_master()` and load `master_team_id = settings.kg_master_team_id`
- [ ] 1.2 Fix line 68: Replace `WHERE LOWER(name) = LOWER($1) AND team_id IS NULL` with `WHERE LOWER(name) = LOWER($1) AND team_id = $2::uuid` and pass `master_team_id` as second argument to `fetchrow()`
- [ ] 1.3 Fix lines 101-109: Replace `VALUES ($1, $2, $3, $4, NULL)` with `VALUES ($1, $2, $3, $4::jsonb, $5::uuid)` passing `master_team_id` as 5th argument. Add `::jsonb` cast on metadata parameter ($4). Fix ON CONFLICT from `((LOWER(name)))` to `(LOWER(name), team_id)`
- [ ] 1.4 Update all parameter indices in `promote_entity_to_master()` to account for the new `master_team_id` parameter
- [ ] 1.5 Verify the Python argument lists at each `fetchrow()`/`execute()` call site match the SQL parameter count

## 2. Fix Relationship Promotion SQL

- [ ] 2.1 Add function-local import `from app.config import settings` in `promote_relationships_to_master()` and load `master_team_id = settings.kg_master_team_id`
- [ ] 2.2 Fix line 171: Replace `AND team_id IS NULL` with `AND team_id = $4::uuid` and add `master_team_id` as 4th argument to the `fetchrow()` call at line 166
- [ ] 2.3 Fix line 199: Replace `VALUES (..., NULL)` with `VALUES (..., $8::uuid)` and add `master_team_id` as 8th argument to the `execute()` call at line 194
- [ ] 2.4 Verify the Python argument lists at each call site match the SQL parameter count

## 3. Fix Eligibility Query Thresholds

- [ ] 3.1 Update the eligibility query in `run_promotion_for_team()` (lines 222-233) to filter by `confidence >= PROMOTION_CONFIDENCE_THRESHOLD` — the constant is defined but not enforced
- [ ] 3.2 Update the eligibility query to filter by `research_session_count >= PROMOTION_SESSION_MINIMUM` (or equivalent join/subquery) — the constant is defined but not enforced
- [ ] 3.3 Pass the threshold values as bound SQL parameters

## 4. Update Module Docstring

- [ ] 4.1 Update the module docstring at top of `kg_promotion.py` to remove references to `team_id = NULL` and reflect that master graph uses the configured master team UUID

## 5. Verification

- [ ] 5.1 Verify all SQL statements in `kg_promotion.py` have no remaining `NULL` references for `team_id`
- [ ] 5.2 Verify ON CONFLICT clause matches the `kg_entities_name_team_unique` index signature `(LOWER(name), team_id)`
- [ ] 5.3 Verify all Python argument lists match their SQL parameter counts (no `$N` without a corresponding argument)
- [ ] 5.4 Verify metadata parameter has `::jsonb` cast
- [ ] 5.5 Verify eligibility query enforces both threshold constants

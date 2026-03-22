## Why

When a user shares a research report with a team, the Knowledge Graph is never updated — the `POST /{session_id}/teams` endpoint shares the session and notifies members but never publishes the report to the `entity_extraction` stream. This means team-scoped KG stays empty for shared reports, which is the primary way teams consume research. Additionally, the validation finalization path publishes to KG without the campaign's `team_id`, the entity extraction worker silently drops failed extractions (always ACKs in `finally`), and there is no way to bulk-retry dead jobs. These gaps undermine the reliability of the entire job → KG pipeline.

## What Changes

- **KG trigger on session share**: When a session is shared to a team (`POST /{session_id}/teams`), publish its `report_markdown` to the `entity_extraction` stream with the team's `team_id`. This is the critical fix — shared reports will now flow into the team-scoped KG.
- **team_id passthrough in validation finalization**: `finalize_validation_job()` currently calls `publish_for_extraction(validation_job_id, combined_report)` without `team_id`. Look up the campaign's `team_id` from the `validation_jobs` → `campaigns` join and pass it through.
- **Extraction worker failure resilience**: The extraction worker always ACKs Redis messages in its `finally` block, even when `_process_message()` raises. Failed extractions are silently lost. Change to only ACK on success; on failure, NACK/don't ACK so the message is redelivered to another consumer (or the same one after timeout).
- **Bulk retry dead jobs API**: Add `POST /api/campaigns/{campaign_id}/retry-dead` to reset all dead jobs in a campaign back to pending in one call, complementing the existing per-job retry endpoint.
- **Dispatcher startup pending sweep**: Add a one-time scan for stale `claimed`/`running` jobs at dispatcher startup (before entering the poll loop) to immediately reclaim jobs orphaned by a prior crash.

## Capabilities

### New Capabilities
- `kg-share-trigger`: Publishing shared session reports to the entity extraction stream with team-scoped KG routing
- `pipeline-resilience`: Extraction failure handling, bulk dead-job retry, team_id passthrough in validation finalization, dispatcher startup sweep

### Modified Capabilities
<!-- No existing specs -->

## Impact

- **Backend API**: `app/routers/sessions.py` (share endpoint), `app/routers/jobs.py` (new bulk retry endpoint)
- **Backend core**: `app/job_queue.py` (finalize_validation_job team_id lookup), `app/streams.py` (no changes needed — `publish_for_extraction` already accepts `team_id`)
- **Worker**: `worker/entity_extraction.py` (ACK-on-success-only pattern)
- **Dispatcher**: `job_runner/dispatcher.py` (startup sweep)
- **No frontend changes, no schema changes, no new dependencies**

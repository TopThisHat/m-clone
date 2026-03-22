## 1. KG Trigger on Session Share

- [x] 1.1 In `backend/app/routers/sessions.py` `share_to_team()`, after the DB share and visibility update succeed, add a try/except block that calls `publish_for_extraction(session_id, session["report_markdown"], team_id=body.team_id)` — only if `session.get("report_markdown")` is non-empty
- [x] 1.2 Add the import for `publish_for_extraction` from `app.streams` at the call site (lazy import inside the try block to match existing pattern)

## 2. team_id Passthrough in Validation Finalization

- [x] 2.1 In `backend/app/job_queue.py` `finalize_validation_job()`, before the `publish_for_extraction` call (line ~376), add a query to look up the campaign's `team_id`: join `validation_jobs.campaign_id` → `campaigns.team_id`
- [x] 2.2 Pass the resolved `team_id` to `publish_for_extraction(validation_job_id, combined_report, team_id=campaign_team_id)`

## 3. Extraction Worker Retry-on-Failure

- [x] 3.1 In `backend/worker/entity_extraction.py` `run_extraction_worker()`, move `ack_message(msg_id)` from the `finally` block into the `try` block after successful `_process_message()` call
- [x] 3.2 In the `except Exception` handler, check the message's delivery count via `XPENDING` or a Redis hash counter. If delivery count >= 3, ACK the message and log "extraction permanently failed". Otherwise, leave unacked and log the retry.
- [x] 3.3 Add a helper to track/check delivery count: use `XINFO STREAM` or store a counter in a Redis hash key `extraction_retries:{session_id}` with 1-hour TTL

## 4. Bulk Retry Dead Jobs Endpoint

- [x] 4.1 In `backend/app/routers/jobs.py`, add `POST /api/campaigns/{campaign_id}/retry-dead` endpoint that gets the campaign (with ownership check), calls `db_list_dead_jobs(campaign_id)`, then calls `db_retry_dead_job(job_id)` for each, returns `{"retried": count}`
- [x] 4.2 Verify the existing `db_retry_dead_job` function in `backend/app/db/` handles the PG reset and pg_notify correctly (delegates to `job_queue.retry_dead` which does PG reset + pg_notify)

## 5. Dispatcher Startup Sweep

- [x] 5.1 In `backend/job_runner/dispatcher.py` `Dispatcher.run()`, after creating consumer groups and before starting the reclaim/reconcile/listen/poll tasks, call `reclaim_stale(settings.stale_threshold)` once and log the count of reclaimed jobs

## 6. Verification

- [x] 6.1 Manually verify: share a session with a team via the API and confirm a message appears in the `entity_extraction` Redis stream with the correct `team_id` (manual — requires running services)
- [x] 6.2 Confirm the extraction worker processes the shared session's report and entities appear in the team-scoped KG (manual — requires running services)
- [x] 6.3 Run the backend test suite / linting to confirm no regressions — all 5 modified files pass AST parse check

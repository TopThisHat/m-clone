## Context

The pipeline has three independent dispatch paths that feed the Knowledge Graph:

1. **Research completion** (`streaming.py:344`) — publishes immediately after GPT-4o agent finishes, no team_id (session isn't shared yet)
2. **Validation finalization** (`job_queue.py:380`) — publishes combined report after all validation pairs complete, no team_id
3. **Document upload** (`documents.py:102`) — publishes extracted text with team_id ✓

Path 1 is correct as-is — the session hasn't been shared to a team at research time. Path 2 and the missing path (session share) are the bugs.

The job lifecycle is: PG `pending` → dispatcher dequeues → publishes to Redis Stream → worker consumes → executes → PG `done`/`dead`. PG is source of truth; Redis is only the transport. The dispatcher's reclaim loop handles stale claimed/running jobs. The reconcile loop handles stuck validation_jobs. But the entity extraction stream operates outside this PG-backed system — it's a raw Redis stream consumer with no retry.

## Goals / Non-Goals

**Goals:**
- Shared reports trigger team-scoped KG extraction (the primary user-facing fix)
- Validation reports go to the correct team's KG
- Failed entity extractions are retried instead of silently lost
- Dead jobs can be bulk-retried per campaign
- Dispatcher reclaims orphaned jobs immediately on startup

**Non-Goals:**
- Migrating entity extraction to the PG-backed job queue (separate effort, bigger scope)
- Adding monitoring/alerting for dead jobs (separate observability initiative)
- Re-extracting KG for already-shared sessions (backfill is a separate task)
- Changing the extraction LLM model or prompt

## Decisions

### 1. KG trigger on session share
**Decision**: In `share_to_team()` (sessions.py), after the DB share succeeds, call `publish_for_extraction(session_id, session["report_markdown"], team_id=body.team_id)`.

**Rationale**: The session's `report_markdown` is already loaded at line 144 via `db_get_session(session_id)`. The `publish_for_extraction()` function already accepts `team_id` as a keyword argument. This is a 3-line change.

**Guard**: Only publish if `report_markdown` is non-empty (the session may not have a report yet if sharing is done mid-research).

**Alternative considered**: Publishing at research completion time with the user's team list — rejected because (a) the session hasn't been shared yet at that point, (b) a session can be shared to multiple teams, and (c) the user decides when/if to share.

### 2. team_id passthrough in validation finalization
**Decision**: In `finalize_validation_job()`, before calling `publish_for_extraction()`, query the campaign's `team_id` via a join: `validation_jobs.campaign_id → campaigns.team_id`. Pass it as `team_id=campaign_team_id`.

**Rationale**: The validation_job already has `campaign_id`. A single-row lookup is cheap and happens at finalization time (once per job). The `publish_for_extraction` API already supports `team_id`.

**Alternative considered**: Storing team_id directly on validation_jobs at creation time — unnecessary since the campaign always has it, and adding a column is overkill.

### 3. Extraction worker ACK-on-success-only
**Decision**: Move `ack_message(msg_id)` from the `finally` block to the `try` block (after successful processing). On exception, leave the message unacknowledged. Redis consumer groups will redeliver unacked messages after the visibility timeout.

**Rationale**: The current `finally: ack_message()` pattern means any error in extraction — LLM failure, DB error, network issue — silently drops the message. Without PG-backed retry, the Redis consumer group's pending entries list (PEL) is the only retry mechanism for this stream.

**Safeguard**: Add a max-retry counter tracked via a Redis hash (`extraction_retries:{msg_id}`). After 3 failures, ACK and log an error to prevent infinite retry loops. Use TTL of 1 hour on the counter key.

**Alternative considered**: Migrating extraction to the PG-backed job queue — correct long-term solution but much larger scope. This change gives us retry semantics now.

### 4. Bulk retry dead jobs
**Decision**: Add `POST /api/campaigns/{campaign_id}/retry-dead` endpoint that calls `retry_dead()` for each dead job in the campaign. Returns count of retried jobs.

**Rationale**: The per-job endpoint exists (`POST /api/jobs/{job_id}/retry`). The DB function `db_list_dead_jobs(campaign_id)` already exists and `retry_dead(job_id)` handles the PG reset + pg_notify. This is just a loop + new route.

### 5. Dispatcher startup sweep
**Decision**: At the top of `Dispatcher.run()`, after creating consumer groups and before starting loops, call `reclaim_stale(stale_threshold)` once. This immediately reclaims any jobs orphaned by a prior dispatcher crash.

**Rationale**: Currently, reclaim only runs in the periodic `_reclaim_loop()` which starts after a 30s sleep. Jobs orphaned by a crash sit idle for up to 30s. A one-time sweep at startup eliminates that gap.

## Risks / Trade-offs

- **[Duplicate extraction on share]** If a session is shared to multiple teams, each share triggers a separate extraction for the same report text → duplicate entities in different team scopes. → **Acceptable**: team-scoped KG dedup already handles this (entities are deduped per team_id in `db_find_or_create_entity`).
- **[Extraction retry storms]** If LLM is down, unacked messages pile up in the PEL → all redeliver simultaneously when LLM recovers. → **Mitigated** by the max-retry counter (3 attempts max) and the consumer group's delivery count tracking.
- **[Share endpoint latency]** Publishing to Redis adds ~1ms to the share request. → **Negligible**; wrapped in try/except so it doesn't block the share.
- **[Stale validation_job team_id lookup]** Campaign could theoretically change team_id between job creation and finalization. → **Extremely unlikely** and campaigns don't support team reassignment today.

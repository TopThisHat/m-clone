## ADDED Requirements

### Requirement: Entity extraction worker SHALL retry failed extractions
The entity extraction worker SHALL NOT acknowledge Redis messages when processing fails. Failed messages MUST remain in the consumer group's pending entries list (PEL) for automatic redelivery.

#### Scenario: Extraction succeeds
- **WHEN** `_process_message()` completes successfully
- **THEN** the worker SHALL ACK the Redis message

#### Scenario: Extraction fails with retries remaining
- **WHEN** `_process_message()` raises an exception and the message has been delivered fewer than 3 times
- **THEN** the worker SHALL NOT ACK the Redis message
- **AND** the error SHALL be logged at ERROR level
- **AND** the message SHALL be eligible for redelivery by the consumer group

#### Scenario: Extraction fails after max retries
- **WHEN** `_process_message()` raises an exception and the message has been delivered 3 or more times
- **THEN** the worker SHALL ACK the Redis message to prevent infinite retry
- **AND** the failure SHALL be logged at ERROR level with "extraction permanently failed" message

### Requirement: Bulk retry dead jobs per campaign
The system SHALL expose `POST /api/campaigns/{campaign_id}/retry-dead` to reset all dead jobs for a campaign back to `pending` in a single API call.

#### Scenario: Campaign has dead jobs
- **WHEN** an authenticated user with campaign access calls `POST /api/campaigns/{campaign_id}/retry-dead`
- **AND** the campaign has N dead jobs
- **THEN** the system SHALL reset all N dead jobs to `pending` status with attempts=0
- **AND** return `{"retried": N}`

#### Scenario: Campaign has no dead jobs
- **WHEN** a user calls `POST /api/campaigns/{campaign_id}/retry-dead`
- **AND** the campaign has no dead jobs
- **THEN** the system SHALL return `{"retried": 0}`

### Requirement: Dispatcher SHALL reclaim orphaned jobs at startup
The dispatcher SHALL perform a one-time reclaim sweep for stale `claimed`/`running` jobs immediately at startup, before entering the poll loop.

#### Scenario: Dispatcher starts with orphaned jobs from prior crash
- **WHEN** the dispatcher starts and there are jobs in `claimed` or `running` status with stale heartbeats
- **THEN** the dispatcher SHALL reset those jobs to `pending` before starting the poll loop
- **AND** log the number of reclaimed jobs

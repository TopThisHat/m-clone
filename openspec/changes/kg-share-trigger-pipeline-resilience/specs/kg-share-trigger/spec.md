## ADDED Requirements

### Requirement: Sharing a session to a team SHALL trigger KG extraction
When a session with a non-empty `report_markdown` is shared to a team via `POST /{session_id}/teams`, the system SHALL publish the report to the `entity_extraction` Redis stream with the target `team_id`, so that entities and relationships are extracted into the team-scoped Knowledge Graph.

#### Scenario: Session with report shared to team triggers KG extraction
- **WHEN** a user shares a session that has a non-empty `report_markdown` to a team
- **THEN** the system SHALL call `publish_for_extraction(session_id, report_markdown, team_id=team_id)` after the share DB operation succeeds

#### Scenario: Session without report shared to team does not trigger extraction
- **WHEN** a user shares a session that has no `report_markdown` (null or empty) to a team
- **THEN** the system SHALL NOT publish to the entity_extraction stream

#### Scenario: KG extraction failure does not block the share operation
- **WHEN** the `publish_for_extraction()` call fails (Redis down, network error)
- **THEN** the share operation SHALL still succeed (the share DB record and notifications are already committed)
- **AND** the failure SHALL be logged at WARNING level

### Requirement: Validation finalization SHALL pass team_id to KG extraction
When `finalize_validation_job()` publishes the combined report to the entity_extraction stream, it SHALL include the campaign's `team_id` so entities are stored in the correct team scope.

#### Scenario: Validation completes for a team-scoped campaign
- **WHEN** a validation job for a campaign with `team_id` is finalized with status `done`
- **THEN** the system SHALL look up the campaign's `team_id` via `validation_jobs.campaign_id → campaigns.team_id`
- **AND** pass `team_id=campaign_team_id` to `publish_for_extraction()`

#### Scenario: Validation completes for a personal campaign
- **WHEN** a validation job for a campaign with no `team_id` (personal campaign) is finalized
- **THEN** the system SHALL call `publish_for_extraction()` with `team_id=None` (current behavior preserved)

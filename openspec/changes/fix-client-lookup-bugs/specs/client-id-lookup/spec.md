## MODIFIED Requirements

### Requirement: Fuzzy client table schema reference
The DB query layer SHALL reference `galileo.fuzzy_client` (not `playbook.fuzzy_client`) for all fuzzy client name searches.

#### Scenario: SQL query targets correct schema
- **WHEN** `search_fuzzy_client()` executes
- **THEN** the SQL query uses `FROM galileo.fuzzy_client`

#### Scenario: Schema health check validates correct table
- **WHEN** `verify_client_lookup_prerequisites()` runs at startup
- **THEN** it checks for the existence of `galileo.fuzzy_client` (not `playbook.fuzzy_client`)

#### Scenario: Index creation targets correct schema
- **WHEN** schema initialization creates the trigram GIN index
- **THEN** the index is created on `galileo.fuzzy_client.name`

### Requirement: Companies field typed as list of strings
The `CandidateResult.companies` field SHALL be typed as `list[str] | None` to match the PostgreSQL `text[]` column type.

#### Scenario: DB layer returns companies as list
- **WHEN** `search_fuzzy_client()` maps a database row to `CandidateResult`
- **THEN** `companies` is a `list[str]` (or `None` if the column is null)

#### Scenario: LLM prompt displays companies as comma-separated string
- **WHEN** the LLM adjudication prompt is built with candidates
- **THEN** companies are formatted as a comma-joined string (e.g., "Goldman Sachs, Morgan Stanley")

#### Scenario: Tool output displays companies as comma-separated string
- **WHEN** `lookup_client` formats its response for the agent
- **THEN** candidate companies are displayed as a comma-joined string

### Requirement: Integration test schema references
All integration tests SHALL reference `galileo.fuzzy_client` for seed data insertion and cleanup.

#### Scenario: Test seed data uses correct schema
- **WHEN** integration tests insert seed data for fuzzy client tests
- **THEN** the INSERT statement targets `galileo.fuzzy_client`

#### Scenario: Test cleanup uses correct schema
- **WHEN** integration tests clean up after fuzzy client tests
- **THEN** the DELETE statement targets `galileo.fuzzy_client`

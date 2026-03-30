## ADDED Requirements

### Requirement: Agent system prompt lists lookup_client tool
The research agent system prompt SHALL include `lookup_client` in its "You have access to" tool list with a description matching its registry entry.

#### Scenario: Agent receives lookup_client in tool guidance
- **WHEN** the research agent system prompt is loaded
- **THEN** the tool list includes `lookup_client` with guidance on its purpose (resolve a person's name to a GWM client ID)

### Requirement: Agent calls lookup_client for each person in a multi-person query
When a user asks the research agent to check client IDs for multiple people, the agent SHALL call `lookup_client` once per person, using parallel tool calls where possible.

#### Scenario: User asks to check client IDs for a list of people
- **WHEN** the user asks "give me all NFL owners and check if they have client IDs"
- **THEN** the agent researches NFL owners first, then calls `lookup_client` in parallel batches for each person found

#### Scenario: User asks to check a single person
- **WHEN** the user asks "does John Smith have a client ID?"
- **THEN** the agent calls `lookup_client` once with name="John Smith"

#### Scenario: Agent does not refuse bulk lookups
- **WHEN** the user asks the agent to look up client IDs for 10+ people
- **THEN** the agent SHALL NOT refuse, say it cannot do bulk lookups, or limit itself to a single call

### Requirement: System prompt includes client lookup query guidance section
The system prompt SHALL include a dedicated section explaining how to handle client lookup queries, including that `lookup_client` is single-name and must be called once per person.

#### Scenario: Guidance section present in system prompt
- **WHEN** the system prompt is rendered
- **THEN** it contains a "Client Lookup Queries" section that instructs the agent to call `lookup_client` once per person and batch calls in parallel

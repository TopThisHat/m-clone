## ADDED Requirements

### Requirement: KG Chat orchestrator with structured tools
The system SHALL provide a `KGChatOrchestrator` that accepts natural language questions about the knowledge graph and returns natural language answers using LLM tool-calling with 6 structured KG tools. The orchestrator SHALL NOT generate dynamic SQL.

#### Scenario: Natural language entity search
- **WHEN** user asks "Who works at Blackstone?"
- **THEN** the orchestrator SHALL call `search_kg_entities` and `get_entity_relationships` tools, then synthesize a natural language answer listing the people with role relationships to Blackstone

#### Scenario: Multi-hop connection query
- **WHEN** user asks "What connects Tiger Capital to SportsCo?"
- **THEN** the orchestrator SHALL call `find_connections` with both entity IDs and return the shortest path(s) as a natural language description

#### Scenario: Aggregation query
- **WHEN** user asks "How many sports teams are in the graph?"
- **THEN** the orchestrator SHALL call `aggregate_kg` with `entity_count_by_type` and return the count in natural language

#### Scenario: LLM failure fallback
- **WHEN** the LLM API call fails or times out
- **THEN** the system SHALL fall back to the existing `db_query_kg()` keyword search and return results with a message: "I couldn't process that as a conversation, but here's what I found by keyword search"

### Requirement: Six structured KG tools
The system SHALL provide exactly 6 tools to the LLM: `search_kg_entities`, `get_entity_relationships`, `find_connections`, `aggregate_kg`, `get_entity_details`, and `explore_neighborhood`. All tools SHALL validate parameters before SQL execution.

#### Scenario: search_kg_entities uses trigram fuzzy matching
- **WHEN** the tool is called with query "Tger" (typo)
- **THEN** the tool SHALL use `pg_trgm` similarity to return "Tiger Capital" and "Tiger Global" as fuzzy matches

#### Scenario: find_connections returns shortest paths
- **WHEN** the tool is called with source and target entity IDs
- **THEN** the tool SHALL return up to 5 shortest paths using BFS traversal limited to the specified max_hops (default 3)

#### Scenario: aggregate_kg uses pre-defined queries only
- **WHEN** the tool is called with an aggregation type
- **THEN** the tool SHALL execute a hardcoded SQL query for that aggregation type; no dynamic SQL SHALL be generated

#### Scenario: Tool parameter validation
- **WHEN** a tool is called with an invalid entity_id (not a valid UUID)
- **THEN** the tool SHALL return a validation error without executing any SQL

### Requirement: SSE streaming chat endpoint
The system SHALL expose `POST /api/kg/chat` as an SSE streaming endpoint that streams text deltas, tool execution events, and graph highlighting events.

#### Scenario: Streaming text response
- **WHEN** user sends a chat message
- **THEN** the endpoint SHALL stream `text_delta` events as the LLM generates its response, followed by a `done` event

#### Scenario: Tool execution visibility
- **WHEN** the LLM invokes a tool during response generation
- **THEN** the endpoint SHALL emit a `tool_call_start` event (with tool name) followed by a `tool_result` event

#### Scenario: Graph highlight events
- **WHEN** the LLM's response references specific entities
- **THEN** the endpoint SHALL emit `kg_highlight` events containing entity IDs that the frontend can use to highlight nodes on the graph

#### Scenario: Path highlight events
- **WHEN** the LLM describes a connection path between entities
- **THEN** the endpoint SHALL emit `kg_path` events containing the ordered entity-predicate-entity chain for frontend path visualization

### Requirement: Conversation history persistence
The system SHALL persist chat conversation history in PostgreSQL tables `kg_chat_sessions` and `kg_chat_messages`, scoped to team_id and user.

#### Scenario: New conversation creates session
- **WHEN** user sends a message without a `conversation_id`
- **THEN** the system SHALL create a new `kg_chat_sessions` record and return the session ID in the `start` SSE event

#### Scenario: Follow-up messages use conversation context
- **WHEN** user sends "what about their board members?" after asking about a company
- **THEN** the orchestrator SHALL receive the full conversation history and resolve "their" to the company from the previous turn

#### Scenario: Session expiry
- **WHEN** a chat session is older than 30 days
- **THEN** the system SHALL automatically delete the session and its messages

### Requirement: Entity disambiguation
The system SHALL use the `disambiguation_context` field to resolve ambiguous entity references and present clarification options to the user when multiple matches exist.

#### Scenario: Ambiguous entity reference
- **WHEN** user asks about "John Smith" and multiple entities match
- **THEN** the orchestrator SHALL present each match with its disambiguation context and ask the user to specify which one

### Requirement: Schema-aware system prompt
The system SHALL inject the full KG ontology (10 entity types, 6 predicate families with canonical predicates) into the LLM system prompt, generated from `kg_ontology.py` at runtime.

#### Scenario: Ontology changes reflected automatically
- **WHEN** a new entity type or predicate family is added to `kg_ontology.py`
- **THEN** the system prompt SHALL include the new type/family without code changes to the chat module

### Requirement: Rate limiting and cost control
The system SHALL enforce rate limits on chat usage: 30 messages per minute per user, 50 messages per session, and max 6 tool calls per LLM turn.

#### Scenario: Rate limit exceeded
- **WHEN** a user sends more than 30 messages in one minute
- **THEN** the system SHALL return HTTP 429 with a retry-after header

#### Scenario: Tool call loop prevention
- **WHEN** the LLM attempts more than 6 tool calls in a single turn
- **THEN** the orchestrator SHALL stop tool execution and return the partial result with a message indicating the query was too complex

### Requirement: Chat UI panel
The frontend SHALL display the chat interface as a persistent left sidebar panel on the KG explore page with message history, starter prompts, and action buttons.

#### Scenario: Empty state shows starter prompts
- **WHEN** the chat panel is opened with no conversation history
- **THEN** the panel SHALL display example queries: "Who works at Blackstone?", "Show me all ownership chains", "What connects Acme to GlobalCorp?"

#### Scenario: Action buttons in responses
- **WHEN** the chatbot response references specific entities
- **THEN** the response SHALL include clickable action buttons: "Focus [entity] in graph" and "Show all on graph"

#### Scenario: Chat and entity detail coexist
- **WHEN** the chat panel is open and user clicks a node
- **THEN** the entity detail panel SHALL open on the right side as an overlay without closing the chat panel

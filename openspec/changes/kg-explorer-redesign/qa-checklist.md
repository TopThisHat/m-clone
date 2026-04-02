# KG Explorer Redesign — QA Checklist

## Workstream 1: Chat Backend (Tasks #1-#5, #8)

### DB Migration (#1, #8)
- [ ] `kg_chat_sessions` table created with columns: id (UUID PK), team_id, user_sid, created_at, updated_at
- [ ] `kg_chat_messages` table created with columns: id (UUID PK), session_id (FK), role, content, tool_calls (JSONB), tool_call_id, entity_highlights (JSONB), created_at
- [ ] FK `session_id` CASCADE on delete (messages auto-deleted when session deleted)
- [ ] Index on `(session_id, created_at)` for efficient message retrieval
- [ ] Sessions scoped to `team_id` — no cross-team access
- [ ] Rollback migration exists and reverses all changes cleanly

### DB Layer — kg_chat_sessions.py (#2)
- [ ] `create_session(team_id, user_sid)` → returns UUID session ID
- [ ] `get_session(session_id)` → returns session dict or None
- [ ] `add_message(session_id, role, content, tool_calls?, tool_call_id?, entity_highlights?)` → returns message ID
- [ ] `get_messages(session_id)` → returns list ordered by `created_at` ASC
- [ ] `delete_session(session_id)` → cascades to messages
- [ ] `cleanup_expired_sessions()` → deletes sessions >30 days old, returns count
- [ ] All functions use parameterized queries (no f-strings or string interpolation in SQL)

### KG Tools — kg_tools.py (#3)
- [ ] **search_kg_entities**: Uses `pg_trgm` similarity, accepts query + team_id + limit, returns name/type/id/score
- [ ] **get_entity_relationships**: Accepts entity_id + family? + direction? + team_id, validates UUID format
- [ ] **find_connections**: BFS recursive CTE, max_hops default=3, returns up to 5 shortest paths
- [ ] **aggregate_kg**: Pre-defined queries ONLY (hardcoded allowlist), rejects unknown types
- [ ] **get_entity_details**: Batch UUID fetch, validates all UUIDs, includes disambiguation_context
- [ ] **explore_neighborhood**: Wraps existing `db_get_neighbors`, respects team_id scoping
- [ ] **ALL tools**: Validate UUID parameters before executing SQL
- [ ] **ALL tools**: Use parameterized queries — zero SQL string concatenation
- [ ] **SQL injection test**: All 6 tools handle `'; DROP TABLE` payloads safely

### KGChatOrchestrator — kg_chat.py (#4)
- [ ] Follows `ResearchOrchestrator` pattern (same streaming/tool-calling structure)
- [ ] Uses `gpt-4.1` model (not gpt-5.1)
- [ ] System prompt includes full ontology from `kg_ontology.py` (entity types + predicate families)
- [ ] System prompt is generated at runtime (picks up ontology changes automatically)
- [ ] Tool-calling loop with streaming: processes tool calls iteratively
- [ ] Emits `TextDelta` events for streamed text
- [ ] Emits `ToolCallStart` event when tool is invoked (includes tool name)
- [ ] Emits `ToolResult` event when tool completes
- [ ] Emits `kg_highlight` events with entity IDs from tool results
- [ ] Emits `kg_path` events with entity-predicate-entity chains
- [ ] Max 6 tool calls per turn — stops with partial result message if exceeded
- [ ] Graceful fallback to `db_query_kg()` keyword search on LLM failure
- [ ] Fallback message: "I couldn't process that as a conversation, but here's what I found by keyword search"

### SSE Endpoint — kg_chat router (#5)
- [ ] `POST /api/kg/chat` endpoint exists and streams SSE
- [ ] Accepts `team_id` and validates membership
- [ ] Creates new session if no `conversation_id` provided, returns session ID in `start` event
- [ ] Sends full conversation history to orchestrator for context continuity
- [ ] Rate limiting: 30 msg/min/user via Redis counter, returns 429 with retry-after
- [ ] Rate limiting: 50 messages per session
- [ ] `GET /api/kg/chat/sessions` — lists user's sessions
- [ ] `GET /api/kg/chat/sessions/{id}/messages` — returns message history
- [ ] `DELETE /api/kg/chat/sessions/{id}` — deletes session
- [ ] Router registered in `app/main.py`

## Workstream 2: Chat Frontend (Tasks #6-#7)

### KGChat.svelte (#6)
- [ ] Left sidebar panel (not right, not bottom)
- [ ] Message list is scrollable, auto-scrolls to bottom on new messages
- [ ] Empty state shows starter prompts: "Who works at Blackstone?", "Show me all ownership chains", "What connects Acme to GlobalCorp?"
- [ ] Message input with Send button at bottom
- [ ] Streaming response rendering (text appears incrementally)
- [ ] Tool execution indicator shown during `tool_call_start` / `tool_result` events
- [ ] Action buttons in assistant messages: "Focus [entity] in graph", "Show all on graph"
- [ ] Conversation management: auto-create session on first message, persist conversation_id
- [ ] Chat icon button in top bar toggles panel
- [ ] Svelte 5 runes: `$state`, `$derived`, `$props` (NOT `export let`)

### Graph Highlighting Integration (#7)
- [ ] `kg_highlight` SSE events set `highlightedNodeIds` on ForceGraph
- [ ] `kg_path` SSE events visualize paths on graph
- [ ] "Focus [entity] in graph" button calls `focusOnNode()`
- [ ] "Show all on graph" highlights all entity IDs from response
- [ ] Chat panel (left) and entity detail panel (right) can coexist simultaneously

## Workstream 3: Command Palette (Tasks #9-#10)

### GET /api/kg/suggest Endpoint (#9)
- [ ] Accepts `q` (query string), `team_id`, `limit` parameters
- [ ] Uses `pg_trgm` similarity for fuzzy matching
- [ ] Response time <50ms for teams with ≤5000 entities
- [ ] Results include: name, entity_type, id, relationship_count
- [ ] Results sorted by trigram similarity score descending
- [ ] Scoped to team_id (no cross-team leakage)
- [ ] GIN trigram index on `kg_entities.name` exists (CREATE INDEX IF NOT EXISTS)
- [ ] Input sanitized — SQL injection safe

### CommandPalette.svelte (#10)
- [ ] Centered modal overlay (not sidebar)
- [ ] Search input focused on open, placeholder "Search Knowledge Graph..."
- [ ] Debounced API calls: 150ms delay
- [ ] Grouped results: Entities section, Filters section
- [ ] Entity results show: name, entity type badge, relationship count
- [ ] Filter suggestions when query matches entity type or predicate family
- [ ] Keyboard navigation: Arrow Up/Down + Enter to select
- [ ] Escape closes palette
- [ ] Entity selection: focusOnNode() + open detail panel + close palette
- [ ] Filter selection: apply filter + close palette
- [ ] Triggers: Cmd+K, Ctrl+K (non-Mac), "/" (when no input focused), search pill click
- [ ] Svelte 5 runes

## Workstream 4: Upload Wizard (Tasks #11-#13)

### UploadWizard.svelte (#11-#13)
- [ ] Modal (not slide-out panel) — centered overlay
- [ ] Closes on Cancel button or backdrop click
- [ ] **Step 1**: Three file type cards — Document, Dataset, Image
  - [ ] Document card: PDF, DOCX — "AI reads your file, identifies people, companies, locations, and relationships, then adds them to your team's graph"
  - [ ] Dataset card: CSV, Excel — "Maps columns to entities and relationships"
  - [ ] Image card: PNG, JPEG, GIF, WebP — "OCR extracts text, then identifies entities"
  - [ ] Clicking card stores type and advances to Step 2
- [ ] **Step 2**: Drag-and-drop zone filtered by selected file type
  - [ ] File name and size displayed after selection
  - [ ] Invalid file type shows error with accepted formats
  - [ ] "Extract & Add to KG" button triggers upload to `POST /api/documents/upload?mode=kg`
- [ ] **Step 3**: Live processing status
  - [ ] Checkmark: "File received (X MB)"
  - [ ] Spinner: "Extracting text...", "Identifying entities..."
  - [ ] Completion: "Done: X entities, Y relationships added"
  - [ ] "View in graph" button closes modal, refreshes graph, focuses new entities
- [ ] Upload button in top bar opens wizard (NOT old slide-out panel)
- [ ] Old slide-out upload panel code removed
- [ ] Svelte 5 runes

## Workstream 5: Bug Fix — Node Drag (#14)

### Manual Drag Implementation (#14)
- [ ] Node dragging works WITHOUT `@sigma/node-drag` package
- [ ] Manual implementation via sigma mouse events (downNode, mousemove, mouseup)
- [ ] Dragged node position fixed in layout during drag
- [ ] Drag released returns node to layout control (or keeps fixed, per UX decision)
- [ ] No regressions: click, double-click, right-click still work on nodes

## Cross-Cutting Checks

### Security
- [ ] No SQL injection in any new endpoint (all parameterized queries)
- [ ] No XSS in chat message rendering (sanitize HTML in user/assistant content)
- [ ] Rate limiting enforced (30 msg/min, 50/session)
- [ ] Team scoping: all KG data access filtered by team_id
- [ ] No dynamic SQL generation in aggregate_kg tool

### Code Quality
- [ ] Consistent with existing code style (asyncpg patterns, FastAPI routers)
- [ ] No dead code from removed features (old slide-out panels, old search)
- [ ] Proper error handling with appropriate HTTP status codes (400, 403, 404, 429)
- [ ] Logging at appropriate levels (info for operations, warning for fallbacks, error for failures)

### Integration
- [ ] Chat + detail panel coexist (left + right simultaneously)
- [ ] Keyboard shortcuts don't conflict: Escape closes topmost, Cmd+K opens palette, "/" opens palette
- [ ] Graph highlighting from chat and from command palette both work
- [ ] Upload wizard refreshes graph data after completion

## 1. Layout Overhaul (Phase 1)

- [ ] 1.1 Refactor explore/+page.svelte top bar: remove all filter chips, type dropdowns, family dropdowns, Deal Partners button, Advanced Filters from header. Keep only: Back link, Team Badge, search pill placeholder, Chat icon button, Upload icon button.
- [ ] 1.2 Create FilterStrip.svelte component: collapsible bottom strip with node/edge count pill (color-coded: green ≤100, amber 101-300, red 301+), expand toggle, entity type chips, predicate family chips, Deal Partners toggle, Metadata filter popover, Clear All button.
- [ ] 1.3 Create ZoomRail.svelte component: vertical icon button rail (Zoom In, Zoom Out, Fit to View, Reset Layout) positioned on left edge of graph area with z-index above graph.
- [ ] 1.4 Convert entity detail panel from pushing layout (w-80 flex column) to right-edge overlay (position absolute/fixed, z-index above graph). Ensure it opens on node click and closes on background click.
- [ ] 1.5 Remove current slide-out query panel and slide-out upload panel from explore page. Remove associated state variables (queryPanelOpen, uploadPanelOpen) and the panel-competition logic.
- [ ] 1.6 Remove current minimap SVG (150x100 grid). Remove minimapVisible state and associated rendering code.
- [ ] 1.7 Add keyboard shortcut handler: Escape closes topmost panel, "?" opens shortcut cheat sheet modal (when no input focused).
- [ ] 1.8 Make graph canvas fill full viewport between top bar and bottom filter strip (flex-1, min-h-0).

## 2. Upload Wizard (Phase 1 — parallel with Layout)

- [ ] 2.1 Create UploadWizard.svelte modal component with 3-step flow: Step 1 (type cards), Step 2 (drop zone), Step 3 (processing status).
- [ ] 2.2 Implement Step 1: three file type cards (Document, Dataset, Image) with accepted formats and AI processing explanation text. Clicking a card stores selected type and advances to Step 2.
- [ ] 2.3 Implement Step 2: drag-and-drop zone filtered by selected file type. Show selected file with name and size. "Extract & Add to KG" button triggers upload. File type validation with error message for mismatched types.
- [ ] 2.4 Implement Step 3: live processing status display. Show checkmark for file received, spinner for extraction stages, completion message with entity/relationship counts. "View in graph" button closes modal, refreshes graph, and focuses new entities.
- [ ] 2.5 Wire Upload icon button in top bar to open UploadWizard modal instead of slide-out panel.

## 3. WebGL Renderer Migration (Phase 2)

- [ ] 3.1 Install npm dependencies: sigma@^3.0.0, graphology@^0.25.4, graphology-layout-forceatlas2@^0.10.1, graphology-layout@^0.6.1. Remove d3-force, d3-selection, d3-zoom if no longer needed elsewhere. NOTE: Do NOT install @sigma/node-drag — this scoped package does not exist on npm for Sigma v3. Node drag must be implemented manually (see task 3.9).
- [ ] 3.2 Rewrite ForceGraph.svelte core: replace D3 SVG rendering with Sigma.js v3 WebGL renderer and graphology data layer. Preserve identical $props interface (nodes, edges, highlightedNodeIds, selectedNodeId, theme, all callbacks). Mount Sigma on a div element instead of SVG.
- [ ] 3.3 Implement ForceAtlas2 Web Worker layout: initialize FA2Layout worker on graph mount, configure gravity/scaling/barnesHut parameters, implement auto-stop on convergence, cleanup on component destroy.
- [ ] 3.4 Implement data sync via $effect: incremental graphology updates when nodes/edges props change (add new, remove missing, update attributes). No full graph rebuilds. Call renderer.refresh() once per update batch.
- [ ] 3.5 Implement node interaction events: map clickNode, doubleClickNode, rightClickNode, enterNode, leaveNode to existing callback props (onNodeClick, onNodeDblClick, onNodeContextMenu, onNodeHover).
- [ ] 3.6 Implement edge interaction events: map clickEdge, enterEdge, leaveEdge for tooltips and selection. Position HTML tooltip overlay at mouse coordinates from sigma events.
- [ ] 3.7 Implement highlighting via graphology attributes: set node/edge 'highlighted' attribute, apply dimming to non-highlighted elements. Single renderer.refresh() call per highlight change.
- [ ] 3.8 Implement camera controls: fitToView() via bounding box calculation + camera.animate(), focusOnNode() via node position lookup + camera.animate(), zoom in/out via camera.ratio adjustment.
- [ ] 3.9 Implement node drag manually using Sigma v3 built-in events (@sigma/node-drag does not exist on npm). Use renderer.on('downNode') to start drag, renderer.getMouseCaptor().on('mousemovebody') to track movement with viewportToGraph() coordinate conversion, and mouseup to end drag. Set graphology node attribute 'fixed: true' during drag to pin the node in ForceAtlas2 layout. Prevent default camera pan while dragging.
- [ ] 3.10 Implement label LOD: configure labelRenderedSizeThreshold (8), edgeLabelRenderedSizeThreshold (15). Add custom labelSelector for degree-based priority at medium zoom.
- [ ] 3.11 Implement entity-type node colors with theme support: apply typeColors as graphology node attributes, update on theme change without rebuild.
- [ ] 3.12 Remove 500-node hard cap and 150-node initial load limit. Remove WARN_THRESHOLD and BLOCK_THRESHOLD constants and associated warning/blocking UI.
- [ ] 3.13 Verify all existing context menu, edge tooltip, and selection behaviors work with new renderer. Fix any HTML overlay positioning differences.

## 4. True Minimap (Phase 2)

- [ ] 4.1 Create KGMinimap.svelte component: secondary Sigma renderer in a fixed-position div (bottom-right, 120x80), sharing the same graphology instance, with labels disabled and reduced node size.
- [ ] 4.2 Implement viewport rectangle overlay: listen to main renderer camera 'updated' events, map camera viewport to minimap coordinates, draw rectangle on canvas overlay.
- [ ] 4.3 Auto-show minimap when node count > 50, hide when below. Add toggle icon button.

## 5. KG Chat Backend (Phase 3)

- [ ] 5.1 Create database migration: add kg_chat_sessions table (id, team_id, user_sid, created_at, updated_at) and kg_chat_messages table (id, session_id, role, content, tool_calls, tool_call_id, entity_highlights, created_at). Add index on (session_id, created_at).
- [ ] 5.2 Create app/db/kg_chat_sessions.py: functions for create_session, get_session, add_message, get_messages, delete_session, cleanup_expired_sessions (>30 days).
- [ ] 5.3 Ensure pg_trgm extension is enabled and GIN trigram index exists on kg_entities.name (CREATE INDEX IF NOT EXISTS).
- [ ] 5.4 Create app/agent/kg_tools.py: implement 6 tools — search_kg_entities (trigram similarity), get_entity_relationships (with family/direction filter), find_connections (BFS recursive CTE), aggregate_kg (pre-defined queries only), get_entity_details (batch UUID fetch), explore_neighborhood (wraps db_get_neighbors).
- [ ] 5.5 Create app/agent/kg_chat.py: KGChatOrchestrator class following ResearchOrchestrator pattern. Build schema-aware system prompt from kg_ontology.py. Implement tool-calling loop with streaming. Emit TextDelta, ToolCallStart, ToolResult events. Add graceful fallback to db_query_kg() on LLM failure.
- [ ] 5.6 Add kg_highlight and kg_path SSE event emission: after tool execution, inspect results for entity IDs and relationship paths, emit structured highlight/path events.
- [ ] 5.7 Create app/routers/kg_chat.py: POST /api/kg/chat SSE endpoint with team_id authorization, conversation_id handling (new vs. existing session), rate limiting (30 msg/min/user via Redis counter), and streaming response.
- [ ] 5.8 Add GET /api/kg/chat/sessions (list user's sessions), GET /api/kg/chat/sessions/{id}/messages (get history), DELETE /api/kg/chat/sessions/{id} (delete session) endpoints.
- [ ] 5.9 Register kg_chat router in app/main.py.

## 6. KG Chat Frontend (Phase 3)

- [ ] 6.1 Create KGChat.svelte component: left sidebar panel with message list (scrollable), starter prompts in empty state, message input with Send button, streaming response rendering.
- [ ] 6.2 Implement SSE client for POST /api/kg/chat: handle text_delta (append to current message), tool_call_start/tool_result (show tool execution indicator), kg_highlight (emit highlight event to graph), kg_path (emit path event to graph), done (finalize message).
- [ ] 6.3 Add action buttons in assistant messages: "Focus [entity] in graph" calls focusOnNode(), "Show all on graph" calls highlighting with entity IDs from kg_highlight events.
- [ ] 6.4 Implement conversation management: auto-create session on first message, persist conversation_id, support starting new conversations. Optional: session list sidebar.
- [ ] 6.5 Wire Chat icon button in top bar to toggle KGChat panel. Ensure chat and entity detail panels can coexist (chat=left, detail=right overlay).
- [ ] 6.6 Connect kg_highlight SSE events to ForceGraph: when chat emits entity IDs, set highlightedNodeIds to those IDs so the graph highlights matching nodes.

## 7. Command Palette (Phase 4)

- [ ] 7.1 Create GET /api/kg/suggest endpoint in backend: accepts q (prefix), team_id, limit params. Returns entities sorted by trigram similarity with name, entity_type, id, relationship_count. Target <50ms response.
- [ ] 7.2 Create frontend/src/lib/api/knowledgeGraph.ts suggest() function wrapping the new endpoint.
- [ ] 7.3 Create CommandPalette.svelte component: centered modal overlay with search input, debounced API calls (150ms), grouped results (Entities section, Filters section), keyboard navigation (arrow keys + Enter), Escape to close.
- [ ] 7.4 Wire Cmd+K and "/" keyboard shortcuts to open CommandPalette. Wire search pill in top bar as click trigger.
- [ ] 7.5 Implement result selection: entity selection calls focusOnNode() + opens detail panel + closes palette. Filter selection applies the filter + closes palette.

## 8. Integration Testing & Polish (Phase 5)

- [ ] 8.1 Test WebGL rendering at scale: load graphs with 500, 1000, 2000 nodes, verify 60fps, verify label LOD behavior at different zoom levels.
- [ ] 8.2 Test chat → graph highlighting integration: send chat queries, verify kg_highlight events light up correct nodes, verify kg_path events draw paths.
- [ ] 8.3 Test upload wizard end-to-end: upload PDF, CSV, and image files, verify Step 3 status updates, verify "View in graph" focuses new entities.
- [ ] 8.4 Test command palette fuzzy search: verify trigram matching for typos, verify keyboard navigation, verify entity focus on selection.
- [ ] 8.5 Test keyboard shortcuts: Escape closes panels in correct order, "?" shows cheat sheet, Cmd+K opens palette, "/" opens palette when no input focused.
- [ ] 8.6 Test light/dark theme switching with new Sigma renderer: verify colors update without rebuild.
- [ ] 8.7 Verify chat and entity detail panels coexist (left + right simultaneously).

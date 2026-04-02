## Why

The Knowledge Graph explore page has critical usability and performance problems identified through direct user feedback. The SVG-based D3.js renderer becomes unusable beyond 150 nodes (CPU-bound, 2400+ DOM mutations per tick). The minimap doesn't reflect actual node positions. The query feature is pure SQL `LIKE` matching with no intelligence — it "fails a lot and doesn't answer anything." The upload flow provides no guidance on what to upload or what happens. The header crams 14+ controls into one row, and the slide-out panels for query/upload "look really weird." Users benchmark against Neo4j Bloom and find the current tool unprofessional. Addressing this now is critical for product credibility with B2B customers.

## What Changes

- **BREAKING**: Replace D3.js SVG force-directed graph renderer with Sigma.js v3 + graphology WebGL2 engine. ForceAtlas2 layout runs in a Web Worker. Target: 2000+ nodes / 5000+ edges at 60fps. Remove the 500-node hard cap entirely.
- **BREAKING**: Remove the current minimap (broken grid SVG). Replace with color-coded node count pill and optional true minimap via secondary Sigma renderer sharing the same graphology instance.
- Overhaul page layout: reduce header to 4 items (Back, Team Badge, Search, action buttons), move all filters to collapsible bottom strip, add left-edge zoom rail, entity detail panel overlays graph instead of pushing it.
- Replace slide-out upload panel with 3-step wizard modal: choose file type (with explanation of what AI does), drop file, live processing status with entity count results.
- Replace SQL `LIKE` query endpoint with AI-powered chatbot: new `KGChatOrchestrator` with 6 structured tools, gpt-4.1 model, SSE streaming with `kg_highlight` and `kg_path` events, conversation history in PostgreSQL, graceful fallback to keyword search.
- Replace header search input with command palette (Cmd+K): fuzzy trigram search, grouped results (entities/relationships/filters), debounced 150ms, new `/api/kg/suggest` endpoint.
- Add keyboard shortcuts: Escape to close panels, arrow keys for search navigation, `?` for shortcut cheat sheet.

## Capabilities

### New Capabilities
- `kg-webgl-renderer`: WebGL2 graph rendering via Sigma.js v3 + graphology, replacing D3.js SVG. Includes ForceAtlas2 Web Worker layout, label LOD, node/edge interaction events, and true minimap.
- `kg-chat`: AI-powered conversational graph query system. KGChatOrchestrator with 6 structured tools, SSE streaming, conversation history, graph highlighting events, and graceful fallback.
- `kg-command-palette`: Cmd+K command palette for fuzzy entity/relationship search with trigram matching, grouped results, and type-ahead suggestions via new `/api/kg/suggest` endpoint.
- `kg-upload-wizard`: 3-step modal wizard for KG document upload replacing the slide-out panel. Explains AI processing, shows live status, and links to new graph entities.
- `kg-layout-overhaul`: Redesigned explore page layout with minimal header, collapsible bottom filter strip, left zoom rail, overlay entity detail panel, and keyboard shortcuts.

### Modified Capabilities
<!-- No existing specs to modify -->

## Impact

- **Frontend**: `ForceGraph.svelte` (653 lines) rewritten against Sigma.js API. `explore/+page.svelte` (1411 lines) restructured for new layout. New components: `KGChat.svelte`, `UploadWizard.svelte`, `CommandPalette.svelte`, `ZoomRail.svelte`, `FilterStrip.svelte`.
- **Backend**: New `app/agent/kg_chat.py` (orchestrator), `app/agent/kg_tools.py` (6 tools), `app/routers/kg_chat.py` (SSE endpoint), `app/db/kg_chat_sessions.py` (conversation persistence). New `/api/kg/suggest` endpoint. New `kg_chat_sessions` and `kg_chat_messages` tables.
- **Dependencies**: Add `sigma@^3.0.0`, `graphology@^0.25.4`, `graphology-layout-forceatlas2@^0.10.1`, `@sigma/node-drag@^3.0.0`. Remove D3 force/selection dependencies (d3-force, d3-selection, d3-zoom — ~80kb). Net bundle change: +90kb.
- **Database**: New tables `kg_chat_sessions`, `kg_chat_messages`. Ensure `pg_trgm` extension and GIN trigram index on `kg_entities.name`.
- **API**: New SSE endpoint `POST /api/kg/chat`. New `GET /api/kg/suggest`. Existing `GET /api/kg/query` retained as fallback.
- **LLM Cost**: gpt-4.1 at ~$0.005/turn, rate limited 30 msg/min/user. Estimated $5/day at 1000 queries.

## Context

The KG explore page (`/knowledge-graph/explore`) is the primary graph visualization and exploration tool for the platform. It currently uses D3.js v7.9.0 with SVG rendering in a 653-line `ForceGraph.svelte` component. The page layout (`explore/+page.svelte`, 1411 lines) crams 14+ controls into the header and uses competing slide-out right panels for query and upload. The query endpoint (`GET /api/kg/query`) is pure SQL `LIKE` matching with no LLM involvement. User feedback rates the experience as "clunky" and benchmarks against Neo4j Bloom.

The backend uses PostgreSQL exclusively for graph storage (no Neo4j). Entity extraction uses GPT-5.1 via Redis Streams workers. The platform already has a `ResearchOrchestrator` pattern for LLM tool-calling with SSE streaming, which the chatbot will replicate.

**Constraints**: SvelteKit 2 + Svelte 5 (runes), TailwindCSS, FastAPI backend, asyncpg (no ORM), existing `pydantic-ai` agent patterns.

## Goals / Non-Goals

**Goals:**
- Achieve 60fps rendering at 2000+ nodes / 5000+ edges (10x current capacity)
- Move force layout computation off the main thread entirely
- Provide AI-powered conversational graph exploration that answers natural language questions
- Make upload self-explanatory with clear before/during/after feedback
- Declutter the UI to a professional, Bloom-competitive experience
- Ship incrementally — each phase delivers independent user value

**Non-Goals:**
- Embedding-based semantic search (pgvector) — deferred to future phase
- Neo4j or any graph database migration — PostgreSQL remains the store
- Graph editing/creation from the chatbot (read-only queries only)
- Mobile/responsive layout optimization
- Real-time collaborative graph viewing (multi-user)
- Community detection / automatic clustering (deferred to future phase)

## Decisions

### D1: Sigma.js v3 + graphology over alternatives

**Choice**: Sigma.js v3 with graphology data layer and ForceAtlas2 Web Worker layout.

**Alternatives considered**:
- **force-graph (vasturiano)**: Canvas 2D, no WebGL — still CPU-bound for edge rendering at scale. Main-thread layout.
- **Cytoscape.js**: Canvas 2D renderer, strong API but bioinformatics-focused UX. Main-thread layout.
- **cosmos**: GPU-computed layout via WebGL compute shaders. Impressive but beta, limited interaction API, risky dependency.
- **VivaGraph**: WebGL but unmaintained since 2020.

**Rationale**: Sigma v3 is the only production-grade option combining WebGL2 rendering, Web Worker layout, rich interaction events, and active maintenance. It owns a canvas element (no DOM conflict with Svelte), has TypeScript-first APIs, and graphology provides a clean graph data layer with battle-tested algorithms (ForceAtlas2, Louvain communities, betweenness centrality).

### D2: Structured tools over dynamic SQL for chatbot

**Choice**: 6 pre-defined tools with validated parameters, no LLM-generated SQL.

**Alternatives considered**:
- **Text-to-SQL**: LLM generates raw SQL against the schema. ~70% accuracy on novel schemas, SQL injection risk, hard to audit.
- **Hybrid**: LLM generates parameterized query templates. Better safety but still fragile with schema changes.

**Rationale**: The 6 tools cover all query patterns (search, relationships, paths, aggregation, details, neighborhood). The LLM's job is to decompose natural language into tool call sequences, which it does reliably (>95% accuracy). Structured tools are auditable, safe, and don't break when the schema evolves.

### D3: gpt-4.1 over gpt-5.1 for chatbot

**Choice**: gpt-4.1 for query decomposition.

**Rationale**: Query decomposition into structured tool calls is a well-constrained task. gpt-4.1 handles it reliably at ~5x lower cost than gpt-5.1. Entity extraction (which requires understanding unstructured text) stays on gpt-5.1. Estimated cost: $0.005/turn, $5/day at 1000 queries.

### D4: Command palette over inline search

**Choice**: Cmd+K overlay modal replacing the header search input.

**Rationale**: The header is the root UX problem — too many controls in one row. A command palette removes the search input from the header (saves ~25% of header width), provides a richer result display (grouped, with metadata), and follows established UX patterns (VS Code, Linear, Notion). Uses the existing trigram GIN index for fuzzy matching.

### D5: Chat panel on left, detail panel overlays right

**Choice**: Chatbot opens as a persistent left sidebar. Entity detail panel overlays the right edge without pushing the graph.

**Alternatives considered**:
- **Both panels on right**: Current approach — panels compete, can't view entity details while chatting.
- **Chat as bottom drawer**: Vertical space is more limited than horizontal on most monitors.
- **Chat as floating window**: Adds draggable window management complexity.

**Rationale**: Left sidebar for chat keeps the graph center-stage. Right overlay for entity details means both can be open simultaneously. The graph is never pushed/resized — overlays maintain a stable layout.

### D6: Conversation state in PostgreSQL, not Redis

**Choice**: `kg_chat_sessions` and `kg_chat_messages` tables in PostgreSQL.

**Rationale**: Consistent with the platform's data model (all persistent state in PostgreSQL). Redis is used for ephemeral state (cache, streams) but chat history needs durability and queryability. Sessions are tied to team_id for access control.

## Risks / Trade-offs

- **Sigma.js migration scope** — A full rendering engine swap touches every interaction (click, hover, drag, context menu, selection, zoom). Estimated 5-6 days but could extend if custom node renderers are needed for the current visual design (type badges, glow effects). → **Mitigation**: Keep visual styling minimal in Phase 3, enhance in Phase 6.

- **ForceAtlas2 vs D3 force layout quality** — ForceAtlas2 produces different layouts than D3's forceManyBody. Users may notice the graph "looks different." → **Mitigation**: Tune FA2 parameters (gravity, scaling, barnesHut) to approximate current layout feel. Both are force-directed — the difference is subtle.

- **LLM latency on first chatbot response** — gpt-4.1 tool-calling adds 1-3s latency before first text token. → **Mitigation**: SSE streaming shows tool execution progress ("Searching entities...") immediately. Partial results stream as they arrive.

- **Cmd+K conflicts with browser shortcuts** — On some browsers/OS combinations, Cmd+K is used for address bar focus. → **Mitigation**: Also support `/` as an alternative trigger (GitHub pattern). Trap the event only when the explore page has focus.

- **Chat history storage growth** — At 50 messages/session × 1000 sessions/day, the messages table grows ~50k rows/day. → **Mitigation**: Auto-expire sessions older than 30 days. Add `created_at` index for efficient cleanup queries.

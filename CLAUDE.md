# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Playbook Research** is a B2B research intelligence platform combining real-time AI-powered research (GPT-4o/Claude), enterprise collaboration (teams, comments, sharing), and a data validation platform ("Scout") for entity/attribute verification.

## Development Commands

### Infrastructure (start first)
```bash
docker compose up -d   # Start PostgreSQL (port 5432) and Redis (port 6379)
```

### Backend (Python/FastAPI)
```bash
cd backend
python -m app.main          # Start API server (uses uv for package management)
python -m worker.run        # Start DBOS durable workflow worker (async validation jobs)
```

### Frontend (SvelteKit)
```bash
cd frontend
npm run dev        # Start dev server
npm run check      # Type checking + Svelte validation
npm run build      # Production build
```

### Scout App (secondary SvelteKit app)
```bash
cd scout-app
npm run dev        # Start on port 5174
```

## Environment Configuration

Copy `.env.example` (root) and `backend/.env.example`. Key variables:
- `OPENAI_API_KEY` — Required for GPT-4o agent
- `TAVILY_API_KEY` — Web search tool
- `ANTHROPIC_API_KEY` — Optional Claude model support
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection
- `JWT_SECRET` — Session token signing
- `DEV_AUTH_BYPASS=true` — Skip OIDC for local dev (enables `POST /api/auth/dev-login`)
- `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` — SSO (production)

## Architecture

### System Components

```
frontend/         SvelteKit 2 + Svelte 5 + TailwindCSS — main user UI
scout-app/        SvelteKit — entity validation management UI
backend/app/      FastAPI — REST API + SSE streaming
backend/worker/   DBOS durable workflows — async validation orchestration
PostgreSQL        Primary datastore
Redis             Cache + session store
```

### Core Research Flow (main feature)

1. Frontend POSTs to `POST /api/research` and opens SSE stream
2. `backend/app/agent/` runs a mandatory 4-phase agentic loop:
   - **Phase 0**: `create_research_plan` (define research angles)
   - **Phase 1**: Execute ≥4 research tool calls (`web_search`, `wiki_lookup`, `get_financials`, `search_uploaded_documents`)
   - **Phase 2**: `evaluate_research_completeness` (confidence check)
   - **Phase 3**: Targeted deep-dives if gaps remain
   - **Phase 4**: Write final markdown report with citations
3. Agent events stream in real-time to frontend via SSE
4. Results persist to `sessions` table with full message history and trace steps

### Scout / Validation Flow (secondary feature)

Campaigns define entities × attributes to validate. Validation jobs:
1. Created via `POST /api/jobs`
2. **DBOS Worker** (`backend/worker/`) orchestrates entity × attribute pairs durably
3. Checks `entity_attribute_knowledge` global cache (gwm_id × attribute) before running research
4. Runs `run_research()` for cache misses, caches results
5. LLM determines presence/score; results stored with confidence and citations
6. Campaign scheduler (60s polling loop in `backend/app/scheduler.py`) auto-triggers due runs

### Key Backend Files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app init, router registration, startup/shutdown |
| `backend/app/db.py` | All asyncpg database queries (no ORM) |
| `backend/app/agent/` | Pydantic-AI agent definition, tools, and research logic |
| `backend/app/auth.py` | JWT validation + OIDC/SSO middleware |
| `backend/app/scheduler.py` | Background loop for monitors and campaign scheduling |
| `backend/app/routers/` | FastAPI route handlers (research, sessions, teams, campaigns, jobs, etc.) |
| `backend/worker/` | DBOS workflow definitions for durable async job execution |

### Key Frontend Files

| Path | Purpose |
|------|---------|
| `frontend/src/routes/` | SvelteKit pages and layouts |
| `frontend/src/lib/api/` | Typed API client functions wrapping fetch calls |
| `frontend/src/lib/stores/` | Svelte stores for global state |
| `frontend/src/lib/components/` | Reusable UI components |

### Database Schema (PostgreSQL, raw asyncpg — no ORM)

Core: `users`, `sessions` (reports + message history + trace), `agent_memory`, `research_jobs`
Collaboration: `teams`, `team_members`, `session_teams`, `comments`, `pinned_sessions`, `notifications`, `team_activity`
Validation: `campaigns`, `entities`, `attributes`, `validation_jobs`, `validation_results`, `entity_scores`, `entity_attribute_knowledge`
Monitoring: `monitors`

All schema is managed directly in `backend/app/db.py` via raw SQL.

### Authentication

- **Local dev**: Set `DEV_AUTH_BYPASS=true`, use `POST /api/auth/dev-login`
- **Production**: OIDC/SSO via `authlib`, JWT via `python-jose`
- Auth middleware in `backend/app/auth.py` injects `current_user` into all protected routes

### Human-in-the-Loop Clarification

The agent may pause mid-research to ask clarifying questions. Frontend polls for pending clarifications; user answers are submitted to `POST /api/research/clarify/{clarification_id}` to resume the agent.

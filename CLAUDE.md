# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Memory tracking
export BEADS_DIR=/path/to/your/project/.beads
Use 'bd' for task tracking

# Team rules
Always plan your work first
Implement your plan
Validate all features were implemented

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
uv run python -m app.main          # Start API server (uses uv for package management)
uv run ython -m worker.run        # Start DBOS durable workflow worker (async validation jobs)
```

### Frontend (SvelteKit)
```bash
cd frontend
npm run dev        # Start dev server
npm run check      # Type checking + Svelte validation
npm run build      # Production build
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
frontend/         SvelteKit 2 + Svelte 5 + TailwindCSS — main user UI (Scout at /campaigns)
backend/app/      FastAPI — REST API + SSE streaming
backend/worker/   DBOS durable workflows — async validation orchestration
PostgreSQL        Primary datastore
Redis             Cache + session store
```


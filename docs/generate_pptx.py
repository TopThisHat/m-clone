"""
Generates Playbook-Research-Architecture.pptx
Run: python3 docs/generate_pptx.py
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import os

# ── Palette ────────────────────────────────────────────────────────────────────
NAVY   = RGBColor(0x0a, 0x16, 0x28)
NAVY2  = RGBColor(0x0f, 0x20, 0x40)
NAVY3  = RGBColor(0x16, 0x2d, 0x50)
GOLD   = RGBColor(0xc9, 0xa8, 0x4c)
GOLD2  = RGBColor(0xe8, 0xc7, 0x6a)
WHITE  = RGBColor(0xf1, 0xf5, 0xf9)
SLATE  = RGBColor(0x94, 0xa3, 0xb8)
GREEN  = RGBColor(0x22, 0xc5, 0x5e)
PURPLE = RGBColor(0xa8, 0x55, 0xf7)
ORANGE = RGBColor(0xf9, 0x73, 0x16)
TEAL   = RGBColor(0x14, 0xb8, 0xa6)
BLUE   = RGBColor(0x60, 0xa5, 0xfa)
RED    = RGBColor(0xef, 0x44, 0x44)

W = Inches(13.33)   # widescreen 16:9
H = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H

blank = prs.slide_layouts[6]   # completely blank


# ── Helpers ────────────────────────────────────────────────────────────────────

def add_slide():
    return prs.slides.add_slide(blank)

def bg(slide, color=NAVY):
    sh = slide.shapes.add_shape(1, 0, 0, W, H)
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()

def rect(slide, l, t, w, h, fill, line=None, lw=Pt(0)):
    sh = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line:
        sh.line.color.rgb = line
        sh.line.width = lw
    else:
        sh.line.fill.background()
    return sh

def txt(slide, text, l, t, w, h, color=WHITE, size=18, bold=False,
        align=PP_ALIGN.LEFT, wrap=True):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return tb

def htxt(slide, text, t, color=WHITE, size=28, bold=True):
    """Full-width centered heading."""
    txt(slide, text, 0.3, t, 12.7, 0.6, color=color, size=size,
        bold=bold, align=PP_ALIGN.CENTER)

def accent_bar(slide, color=GOLD):
    rect(slide, 0, 0, 13.33, 0.08, fill=color)
    rect(slide, 0, 7.42, 13.33, 0.08, fill=color)

def bullet_box(slide, title, items, l, t, w, h,
               title_color=GOLD, item_color=WHITE,
               box_color=NAVY2, item_size=13, title_size=14,
               dot_color=None):
    rect(slide, l, t, w, h, fill=box_color, line=NAVY3, lw=Pt(1))
    txt(slide, title, l+0.1, t+0.05, w-0.2, 0.35,
        color=title_color, size=title_size, bold=True)
    item_h = (h - 0.45) / max(len(items), 1)
    for i, item in enumerate(items):
        dot = (dot_color or title_color)
        bullet = "▸ "
        txt(slide, bullet + item,
            l+0.15, t+0.45 + i*item_h, w-0.25, item_h,
            color=item_color, size=item_size)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — TITLE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GOLD)

# Gold P logo box
rect(sl, 5.92, 1.2, 1.5, 1.5, fill=GOLD)
txt(sl, "P", 5.92, 1.2, 1.5, 1.5, color=NAVY, size=64, bold=True, align=PP_ALIGN.CENTER)

txt(sl, "Playbook Research",
    1, 2.95, 11.33, 0.9, color=WHITE, size=44, bold=True, align=PP_ALIGN.CENTER)
txt(sl, "AI-Powered Research Platform — System Architecture",
    1, 3.85, 11.33, 0.55, color=GOLD, size=22, bold=False, align=PP_ALIGN.CENTER)

# Tagline pills
for i, (label, color) in enumerate([
    ("FastAPI Backend", GREEN), ("SvelteKit Frontend", BLUE),
    ("PydanticAI Agent", ORANGE), ("PostgreSQL + Redis", PURPLE),
    ("AWS-Ready", TEAL),
]):
    x = 1.0 + i * 2.25
    rect(sl, x, 4.7, 2.1, 0.42, fill=color)
    txt(sl, label, x, 4.7, 2.1, 0.42, color=NAVY, size=11,
        bold=True, align=PP_ALIGN.CENTER)

txt(sl, "Version 1.0  ·  Confidential",
    1, 6.9, 11.33, 0.35, color=SLATE, size=11, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — PLATFORM OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GOLD)
htxt(sl, "Platform Overview", 0.12, color=GOLD, size=26)

boxes = [
    ("🔬  Research Agent", GREEN,
     ["Mandatory 4-phase research loop",
      "6 specialised tools (web, wiki, finance, docs)",
      "Real-time SSE streaming to browser",
      "Self-evaluation & confidence scoring",
      "Inline citation detection & conflict warnings"]),
    ("👥  Team Collaboration", BLUE,
     ["Create & manage teams with RBAC",
      "Share sessions privately, to team, or public",
      "Threaded comments with @mention notifications",
      "Pin sessions to team workspace",
      "Team activity feed"]),
    ("🧠  Memory & Learning", ORANGE,
     ["Post-research entity extraction (GPT-4o-mini)",
      "Cross-session context enrichment",
      "User-defined domain research rules",
      "BM25 full-text search over uploaded PDFs",
      "Usage tracking & cost dashboard"]),
    ("☁️  Production Infrastructure", PURPLE,
     ["AWS Secrets Manager credential rotation",
      "PostgreSQL RDS + ElastiCache Redis",
      "OIDC SSO (any provider)",
      "Docker Compose for local dev",
      "Async webhook jobs for external integrations"]),
]

for i, (title, color, items) in enumerate(boxes):
    col = i % 2
    row = i // 2
    bullet_box(sl, title, items,
               l=0.3 + col*6.7, t=0.85 + row*3.05,
               w=6.5, h=2.9,
               title_color=color, box_color=NAVY2)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — SYSTEM ARCHITECTURE DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GOLD)
htxt(sl, "System Architecture", 0.12, color=GOLD, size=26)

diagram_path = os.path.join(os.path.dirname(__file__), "architecture-diagram.png")
if os.path.exists(diagram_path):
    sl.shapes.add_picture(diagram_path, Inches(0.15), Inches(0.75),
                          Inches(13.0), Inches(6.55))
else:
    txt(sl, "⚠ Run generate_diagram.py first to embed the diagram image.",
        1, 3.5, 11, 0.5, color=RED, size=16, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — RESEARCH AGENT DEEP DIVE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, ORANGE)
htxt(sl, "Research Agent — Mandatory 4-Phase Loop", 0.12, color=ORANGE, size=24)

phases = [
    ("0", "PLAN", GOLD,
     "create_research_plan tool called first — always.\nStructures scope, key questions, and source strategy."),
    ("1", "EXECUTE", GREEN,
     "Minimum 4 research tool calls with different queries.\nweb_search · wiki_lookup · get_financials · search_docs · sec_edgar"),
    ("2", "EVALUATE", BLUE,
     "evaluate_research_completeness self-assessment.\nScores confidence 0–100 across breadth, depth, recency, conflict."),
    ("3", "DIG DEEPER", ORANGE,
     "If confidence < 85% → targeted follow-up searches.\nFills identified gaps before writing begins."),
    ("4", "REPORT", PURPLE,
     "Final markdown report with inline citations.\nConflict warnings flagged if >25% numeric variance detected."),
]

for i, (num, phase, color, desc) in enumerate(phases):
    x = 0.3 + i * 2.6
    rect(sl, x, 0.85, 2.4, 0.55, fill=color)
    txt(sl, f"Phase {num}", x, 0.85, 2.4, 0.55,
        color=NAVY, size=14, bold=True, align=PP_ALIGN.CENTER)
    txt(sl, phase, x, 1.4, 2.4, 0.4,
        color=color, size=12, bold=True, align=PP_ALIGN.CENTER)
    rect(sl, x, 1.8, 2.4, 3.8, fill=NAVY2, line=color, lw=Pt(1.5))
    txt(sl, desc, x+0.08, 1.9, 2.25, 3.6,
        color=WHITE, size=11, wrap=True)
    if i < 4:
        txt(sl, "→", x+2.4, 1.5, 0.2, 0.4, color=SLATE, size=18, bold=True)

# SSE Events section
rect(sl, 0.3, 5.75, 12.7, 1.5, fill=NAVY2, line=GOLD, lw=Pt(1))
txt(sl, "Real-time SSE Events streamed to browser:",
    0.45, 5.78, 5, 0.35, color=GOLD, size=12, bold=True)
events = [
    "start", "tool_call_start", "tool_executing", "tool_result",
    "text_delta", "chart_data", "conflict_warning", "final_report", "done",
]
for i, ev in enumerate(events):
    col = i % 5
    row = i // 5
    rect(sl, 0.45 + col*2.5, 6.2 + row*0.45, 2.3, 0.38, fill=NAVY3, line=ORANGE, lw=Pt(1))
    txt(sl, ev, 0.45 + col*2.5, 6.2 + row*0.45, 2.3, 0.38,
        color=ORANGE, size=10, bold=True, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — AGENT TOOLS
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, ORANGE)
htxt(sl, "Agent Tools", 0.12, color=ORANGE, size=26)

tools = [
    ("create_research_plan",       GOLD,   "Structures investigation scope, key questions, and source strategy before any research begins."),
    ("web_search",                  GREEN,  "Tavily API — up-to-date web results with automatic snippet extraction and URL tracking."),
    ("wiki_lookup",                 BLUE,   "Wikipedia API — encyclopedic background on companies, industries, and concepts."),
    ("get_financials",              TEAL,   "Yahoo Finance (yfinance) — price history, fundamentals, and chart payloads streamed to UI."),
    ("search_uploaded_documents",   ORANGE, "BM25 Okapi full-text search over user-uploaded PDFs extracted and cached in Redis."),
    ("sec_edgar_search",            PURPLE, "SEC EDGAR filing lookup — 10-K, 10-Q, 8-K for public company regulatory data."),
    ("evaluate_research_completeness", RED, "Self-assessment tool. Scores breadth, depth, recency, source diversity (0–100)."),
]

for i, (name, color, desc) in enumerate(tools):
    row = i % 4
    col = i // 4
    y = 0.85 + row * 1.62
    x = 0.3  + col * 6.55
    rect(sl, x, y, 6.3, 1.5, fill=NAVY2, line=color, lw=Pt(1.5))
    rect(sl, x, y, 6.3, 0.42, fill=color)
    txt(sl, name, x+0.1, y, 6.1, 0.42, color=NAVY, size=12, bold=True)
    txt(sl, desc, x+0.1, y+0.46, 6.1, 1.0, color=WHITE, size=11, wrap=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, PURPLE)
htxt(sl, "Database Schema — 12 Tables (PostgreSQL)", 0.12, color=PURPLE, size=24)

tables = [
    ("users",            GOLD,   ["sid (PK)", "display_name, email", "avatar_url, theme", "last_login"]),
    ("sessions",         GREEN,  ["id UUID (PK)", "title, query", "report_markdown (TEXT)", "message_history (JSONB)", "trace_steps (JSONB)", "owner_sid (FK→users)", "visibility: private|team|public", "is_public, usage_tokens"]),
    ("agent_memory",     ORANGE, ["id UUID (PK)", "session_id (FK→sessions)", "entity, entity_type", "facts (JSONB array)"]),
    ("research_jobs",    TEAL,   ["id UUID (PK)", "query, webhook_url", "status: queued|running|done|failed", "result_markdown, error"]),
    ("teams",            BLUE,   ["id UUID (PK)", "slug (UNIQUE)", "display_name, description", "created_by (FK→users)"]),
    ("team_members",     PURPLE, ["team_id + sid (PK)", "role: owner|admin|member|viewer", "joined_at"]),
    ("session_teams",    RED,    ["session_id + team_id (PK)", "shared_at"]),
    ("comments",         GOLD,   ["id UUID (PK)", "session_id (FK)", "author_sid (FK)", "body, mentions (JSONB)", "parent_id (self-FK for threads)"]),
    ("pinned_sessions",  GREEN,  ["sid + session_id + team_id (PK)", "pinned_at"]),
    ("notifications",    ORANGE, ["id UUID (PK)", "recipient_sid (FK)", "type, payload (JSONB)", "read (BOOLEAN)"]),
    ("team_activity",    BLUE,   ["id UUID (PK)", "team_id (FK)", "actor_sid (FK)", "action, payload (JSONB)"]),
]

cols = 4
for i, (name, color, fields) in enumerate(tables):
    row = i // cols
    col = i % cols
    x = 0.25 + col * 3.28
    y = 0.85 + row * 2.2
    h = 2.05
    rect(sl, x, y, 3.1, h, fill=NAVY2, line=color, lw=Pt(1.5))
    rect(sl, x, y, 3.1, 0.38, fill=color)
    txt(sl, name, x+0.08, y+0.02, 2.95, 0.36, color=NAVY, size=12, bold=True)
    for j, f in enumerate(fields[:6]):
        txt(sl, "· " + f, x+0.1, y+0.42+j*0.26, 2.9, 0.26, color=WHITE, size=9)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — SESSION SHARING & TEAMS
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, BLUE)
htxt(sl, "Session Sharing Model & Team RBAC", 0.12, color=BLUE, size=24)

# Visibility model
rect(sl, 0.3, 0.85, 8.3, 6.4, fill=NAVY2, line=BLUE, lw=Pt(1.5))
txt(sl, "Session Visibility Model", 0.45, 0.88, 8.0, 0.4,
    color=BLUE, size=14, bold=True)

vis = [
    ("private", SLATE, "Only the owner can access.\nDefault state for new sessions."),
    ("team",    GOLD,  "Shared to one or more teams.\nAny team member can view via /share/{id}.\nRequires JWT auth + team membership check."),
    ("public",  GREEN, "is_public=TRUE.\nAccessible by anyone without auth.\nPermanent URL: /share/{uuid}"),
]

for i, (state, color, desc) in enumerate(vis):
    y = 1.5 + i * 1.75
    rect(sl, 0.5, y, 2.0, 1.5, fill=color)
    txt(sl, state.upper(), 0.5, y, 2.0, 1.5,
        color=NAVY, size=20, bold=True, align=PP_ALIGN.CENTER)
    txt(sl, desc, 2.65, y+0.1, 5.7, 1.35, color=WHITE, size=12, wrap=True)
    if i < 2:
        txt(sl, "↓", 1.5, y+1.5, 1.0, 0.25, color=SLATE, size=14, align=PP_ALIGN.CENTER)

# RBAC roles
rect(sl, 8.8, 0.85, 4.2, 6.4, fill=NAVY2, line=PURPLE, lw=Pt(1.5))
txt(sl, "Team RBAC Roles", 8.95, 0.88, 3.9, 0.4,
    color=PURPLE, size=14, bold=True)

roles = [
    ("owner",  GOLD,   "Full control: edit team,\nmanage members, delete sessions"),
    ("admin",  ORANGE, "Manage members, share/unshare\nsessions, moderate comments"),
    ("member", GREEN,  "View team sessions, share\nown sessions to team, comment"),
    ("viewer", BLUE,   "Read-only: view shared sessions\nand comments, no write access"),
]
for i, (role, color, desc) in enumerate(roles):
    y = 1.5 + i * 1.4
    rect(sl, 8.95, y, 1.5, 1.25, fill=color)
    txt(sl, role.upper(), 8.95, y, 1.5, 1.25,
        color=NAVY, size=13, bold=True, align=PP_ALIGN.CENTER)
    txt(sl, desc, 10.55, y+0.1, 2.3, 1.1, color=WHITE, size=11, wrap=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 8 — FRONTEND ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, BLUE)
htxt(sl, "Frontend Architecture — SvelteKit", 0.12, color=BLUE, size=26)

# Route tree
bullet_box(sl, "Route Structure", [
    "+layout.server.ts  →  JWT guard, user hydration, redirect to /login",
    "/(app)/+page.svelte  →  Research workspace (main chat + session list)",
    "/(app)/teams/[slug]  →  Team dashboard, members, pinned sessions",
    "/(app)/notifications  →  Notification inbox (polled every 30s)",
    "/share/[id]/+page.ts  →  SvelteKit fetch (cookies forwarded) → read-only report",
    "/login  +  /auth/callback  →  OIDC redirect & token exchange",
    "/dashboard  →  Usage stats: tokens, cost, top queries",
], 0.3, 0.85, 6.3, 3.9, title_color=BLUE, item_size=11)

# Key components
bullet_box(sl, "Key Components", [
    "ChatThread.svelte  →  SSE listener, streaming tokens, trace steps",
    "ResearchSwimlane.svelte  →  Visual tool-call timeline",
    "$lib/api/sessions.ts  →  Typed REST client (credentials: include)",
    "$lib/stores/  →  Svelte stores: chat messages, trace, session state",
    "Polling  →  setInterval 30s → GET /api/notifications",
], 6.75, 0.85, 6.3, 3.9, title_color=BLUE, item_size=11)

# Auth flow
bullet_box(sl, "Authentication Flow", [
    "1. +layout.server.ts reads jwt cookie on every request",
    "2. No JWT → redirect to /login (public paths exempt)",
    "3. /login → GET /api/auth/login → OIDC provider redirect",
    "4. OIDC callback → exchange code → upsert user → set jwt cookie",
    "5. All fetch() calls use credentials:'include' (same-origin cookies)",
    "6. JWT decoded by FastAPI get_current_user / get_optional_user deps",
], 0.3, 4.9, 12.7, 2.35, title_color=PURPLE, item_size=11)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 9 — AWS INFRASTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, TEAL)
htxt(sl, "AWS Infrastructure & Credential Rotation", 0.12, color=TEAL, size=24)

# Secrets Manager
rect(sl, 0.3, 0.85, 6.2, 6.4, fill=NAVY2, line=TEAL, lw=Pt(1.5))
txt(sl, "AWS Secrets Manager", 0.45, 0.88, 5.9, 0.4,
    color=TEAL, size=14, bold=True)

sm_items = [
    ("DB Secret", PURPLE,
     '{\n  "host": "rds.amazonaws.com",\n  "port": 5432,\n  "username": "app",\n  "password": "...",\n  "dbname": "research"\n}'),
    ("Redis Secret", RED,
     '{\n  "url": "rediss://cluster:6379",\n  "auth_token": "..."\n}'),
]
for i, (label, color, code) in enumerate(sm_items):
    y = 1.45 + i * 2.9
    rect(sl, 0.45, y, 5.9, 2.65, fill=NAVY3, line=color, lw=Pt(1))
    txt(sl, label, 0.55, y+0.05, 5.7, 0.38, color=color, size=12, bold=True)
    txt(sl, code, 0.55, y+0.42, 5.7, 2.15, color=SLATE, size=10)

# Rotation flow
rect(sl, 6.75, 0.85, 6.3, 6.4, fill=NAVY2, line=GOLD, lw=Pt(1.5))
txt(sl, "Automatic Rotation Recovery", 6.9, 0.88, 6.0, 0.4,
    color=GOLD, size=14, bold=True)

steps = [
    (GOLD,   "AWS rotates secret (scheduled or on-demand)"),
    (SLATE,  "Old password still valid during rotation window"),
    (RED,    "Pool.acquire() → new connection → Postgres rejects"),
    (ORANGE, "asyncpg raises InvalidPasswordError"),
    (GREEN,  "_acquire() catches → calls _reset_pool()"),
    (GREEN,  "Pool closed, secret cache evicted"),
    (TEAL,   "get_db_secret() → Secrets Manager → fresh creds"),
    (GREEN,  "New pool created with new DSN + ssl='require'"),
    (WHITE,  "Request retried — transparent to caller"),
]
for i, (color, step) in enumerate(steps):
    y = 1.45 + i * 0.62
    rect(sl, 6.9, y, 0.38, 0.5, fill=color)
    txt(sl, str(i+1), 6.9, y, 0.38, 0.5,
        color=NAVY, size=11, bold=True, align=PP_ALIGN.CENTER)
    txt(sl, step, 7.35, y+0.05, 5.55, 0.5, color=WHITE, size=11)

txt(sl, "Same pattern for Redis (AuthenticationError → _reset_client())",
    6.9, 7.05, 6.15, 0.35, color=TEAL, size=11)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — DATA FLOWS
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GREEN)
htxt(sl, "Key Data Flows", 0.12, color=GREEN, size=26)

flows = [
    ("Research Execution", GREEN, [
        "1. User submits query → POST /api/research",
        "2. Redis: check for cached PDF context",
        "3. DB: load agent_memory for context enrichment",
        "4. Agent executes 4-phase loop with tools",
        "5. SSE events stream tokens + tool calls to browser",
        "6. final_report event → client saves session",
        "7. Background: extract entities → agent_memory",
    ]),
    ("Comment & Notifications", ORANGE, [
        "1. User posts comment with @username",
        "2. Backend regex-parses @mentions",
        "3. Notification row created per mentioned user",
        "4. Frontend polls GET /api/notifications every 30s",
        "5. Badge appears on notification icon",
        "6. User clicks → reads → PATCH /read",
    ]),
    ("PDF Document Search", BLUE, [
        "1. User uploads PDF → POST /api/documents/upload",
        "2. pdfplumber extracts text → stored in Redis (24h TTL)",
        "3. Session key returned to frontend",
        "4. Research request includes pdf_session_key",
        "5. search_uploaded_documents tool: BM25 search over text",
        "6. Relevant chunks injected into agent context",
    ]),
    ("Async Webhook Jobs", PURPLE, [
        "1. Caller: POST /api/research/async + webhook_url",
        "2. Job row created (status: queued) → job_id returned",
        "3. BackgroundTask: run agent loop async",
        "4. On complete: POST result_markdown to webhook_url",
        "5. Caller: GET /api/research/jobs/{id} to poll status",
        "6. Job statuses: queued → running → done|failed",
    ]),
]

for i, (title, color, steps) in enumerate(flows):
    col = i % 2
    row = i // 2
    bullet_box(sl, title, steps,
               l=0.3 + col*6.55, t=0.85 + row*3.2,
               w=6.3, h=3.05,
               title_color=color, item_size=11)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 11 — API REFERENCE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, SLATE)
htxt(sl, "API Reference", 0.12, color=GOLD, size=26)

endpoints = [
    # (method, path, desc, color)
    ("POST",  "/api/research",                     "Stream research SSE  ·  model, query, depth, rules, pdf_session_key",     GREEN),
    ("POST",  "/api/research/async",               "Async job + webhook  ·  returns job_id for polling",                      GREEN),
    ("GET",   "/api/research/jobs/{id}",           "Poll async job status",                                                    TEAL),
    ("GET",   "/api/sessions",                     "List sessions for current user",                                           BLUE),
    ("POST",  "/api/sessions",                     "Create new session",                                                       BLUE),
    ("GET",   "/api/sessions/{id}",                "Get session (owner/team check enforced)",                                  BLUE),
    ("PATCH", "/api/sessions/{id}",                "Update title / report / visibility",                                       BLUE),
    ("DELETE","/api/sessions/{id}",                "Delete session",                                                           BLUE),
    ("POST",  "/api/sessions/{id}/share",          "Make session public  →  returns share_url",                                GOLD),
    ("POST",  "/api/sessions/{id}/teams",          "Share session to team  →  visibility=team",                                GOLD),
    ("GET",   "/api/share/{id}",                   "Public/team read-only  ·  auth optional (team check if authed)",           GOLD),
    ("POST",  "/api/documents/upload",             "Upload PDF  →  Redis cached  →  returns session_key",                     ORANGE),
    ("GET",   "/api/teams",                        "List user's teams",                                                        PURPLE),
    ("POST",  "/api/teams",                        "Create team (caller becomes owner)",                                       PURPLE),
    ("GET",   "/api/teams/{slug}",                 "Get team + member list",                                                   PURPLE),
    ("POST",  "/api/teams/{slug}/members",         "Add member with role",                                                     PURPLE),
    ("GET",   "/api/notifications",                "Unread notification list (poll every 30s)",                                TEAL),
    ("PATCH", "/api/notifications/{id}/read",      "Mark single notification read",                                            TEAL),
    ("GET",   "/api/usage/summary",                "Token usage, cost, top queries dashboard stats",                           SLATE),
    ("GET",   "/health",                           "Health check  →  {status: ok, version: 1.0.0}",                           GREEN),
]

method_colors = {"GET": GREEN, "POST": BLUE, "PATCH": ORANGE, "DELETE": RED}
rows_per_col = 10
for i, (method, path, desc, _) in enumerate(endpoints):
    col = i // rows_per_col
    row = i % rows_per_col
    x = 0.25 + col * 6.55
    y = 0.82 + row * 0.64
    mc = method_colors.get(method, SLATE)
    rect(sl, x, y, 0.85, 0.5, fill=mc)
    txt(sl, method, x, y, 0.85, 0.5,
        color=NAVY, size=9, bold=True, align=PP_ALIGN.CENTER)
    txt(sl, path, x+0.9, y+0.02, 2.5, 0.28, color=GOLD2, size=8.5, bold=True)
    txt(sl, desc, x+0.9, y+0.26, 5.5, 0.28, color=SLATE, size=8)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 12 — KEY ARCHITECTURAL DECISIONS
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GOLD)
htxt(sl, "Key Architectural Decisions", 0.12, color=GOLD, size=26)

decisions = [
    ("SSE over WebSocket", GOLD,
     ["One-way streaming fits research output perfectly",
      "Works through all proxies and CDNs without upgrade",
      "Compatible with serverless (no persistent connection)",
      "Native browser EventSource API — no extra library"]),
    ("asyncpg Direct (no ORM)", GREEN,
     ["Maximum async performance — no sync blocking",
      "Advisory locks for safe concurrent schema migrations",
      "Full JSONB support for message_history & trace_steps",
      "Simple typed queries without abstraction overhead"]),
    ("Mandatory Research Phases", ORANGE,
     ["Prevents shallow one-shot responses",
      "Forces self-evaluation before writing",
      "Minimum 4 tool calls ensures breadth",
      "Conflict detection adds credibility signals"]),
    ("Graceful Degradation", BLUE,
     ["Redis unavailable → in-memory fallback (app keeps running)",
      "DB not configured → endpoints return empty (not 500)",
      "OIDC not set → dev bypass for local development",
      "Each service fails independently, not catastrophically"]),
    ("Secret Rotation at Runtime", TEAL,
     ["No restart required when AWS rotates credentials",
      "Auth errors detected on next pool.acquire()",
      "Single retry after re-fetching from Secrets Manager",
      "asyncio.Lock prevents thundering-herd on reset"]),
    ("RBAC + Visibility Model", PURPLE,
     ["3-tier session visibility: private → team → public",
      "4-tier team roles: owner → admin → member → viewer",
      "Permanent share URLs: /share/{uuid} never changes",
      "Team membership verified server-side on every request"]),
]

for i, (title, color, points) in enumerate(decisions):
    col = i % 3
    row = i // 3
    bullet_box(sl, title, points,
               l=0.25 + col*4.35, t=0.82 + row*3.1,
               w=4.2, h=2.95,
               title_color=color, item_size=11)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 13 — DEPLOYMENT GUIDE
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GREEN)
htxt(sl, "Deployment Guide", 0.12, color=GREEN, size=26)

bullet_box(sl, "Local Development (Docker Compose)", [
    "docker compose up -d  →  starts Postgres 16 + Redis 7",
    "cp backend/.env.example backend/.env  →  fill in API keys",
    "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/research",
    "REDIS_URL=redis://localhost:6379",
    "DEV_AUTH_BYPASS=true  →  skip OIDC for local testing",
    "cd backend && uvicorn app.main:app --reload",
    "cd frontend && npm install && npm run dev",
], 0.3, 0.85, 6.2, 4.0, title_color=GREEN, item_size=11)

bullet_box(sl, "AWS Production", [
    "Set AWS_SECRET_NAME=prod/myapp/db (JSON: host/port/username/password/dbname)",
    "Set AWS_ELASTICACHE_SECRET_NAME=prod/myapp/redis (JSON: url/auth_token)",
    "Set AWS_REGION=us-east-1 (or your region)",
    "SSL auto-enabled for Postgres; TLS (rediss://) auto-enabled for Redis",
    "DATABASE_URL and REDIS_URL are ignored when AWS secrets are set",
    "Credential rotation handled automatically — no restarts needed",
    "Health check: GET /health  →  use for ECS/ALB target group",
], 6.7, 0.85, 6.3, 4.0, title_color=TEAL, item_size=11)

bullet_box(sl, "Required Environment Variables", [
    "OPENAI_API_KEY  —  GPT-4o for research + memory extraction",
    "TAVILY_API_KEY  —  web search tool",
    "JWT_SECRET  —  HS256 signing key (change from default in prod!)",
    "ALLOWED_ORIGINS  —  CORS whitelist (JSON array of URLs)",
    "OIDC_ISSUER + OIDC_CLIENT_ID + OIDC_CLIENT_SECRET  —  SSO",
    "APP_BASE_URL  —  used for OIDC redirect URI construction",
    "ANTHROPIC_API_KEY  —  optional, enables Claude Sonnet model",
], 0.3, 5.05, 12.7, 2.2, title_color=GOLD, item_size=11)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 14 — THANK YOU / QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════
sl = add_slide()
bg(sl)
accent_bar(sl, GOLD)

rect(sl, 5.42, 1.8, 2.5, 2.5, fill=GOLD)
txt(sl, "P", 5.42, 1.8, 2.5, 2.5, color=NAVY, size=100, bold=True, align=PP_ALIGN.CENTER)

txt(sl, "Playbook Research",
    1, 4.5, 11.33, 0.7, color=WHITE, size=38, bold=True, align=PP_ALIGN.CENTER)
txt(sl, "Questions?",
    1, 5.2, 11.33, 0.55, color=GOLD, size=26, align=PP_ALIGN.CENTER)

for i, (label, val, color) in enumerate([
    ("Backend",    "FastAPI + PydanticAI + asyncpg", GREEN),
    ("Frontend",   "SvelteKit + TypeScript",         BLUE),
    ("AI Models",  "GPT-4o + Claude Sonnet 4.6",     ORANGE),
    ("Infra",      "PostgreSQL + Redis + AWS",        PURPLE),
]):
    x = 0.6 + i * 3.1
    rect(sl, x, 6.1, 2.95, 0.85, fill=NAVY2, line=color, lw=Pt(1.5))
    txt(sl, label, x+0.1, 6.13, 2.75, 0.35, color=color, size=11, bold=True)
    txt(sl, val,   x+0.1, 6.48, 2.75, 0.4,  color=WHITE, size=10)


# ── Save ───────────────────────────────────────────────────────────────────────
out = "docs/Playbook-Research-Architecture.pptx"
prs.save(out)
print(f"Saved {out}  ({len(prs.slides)} slides)")

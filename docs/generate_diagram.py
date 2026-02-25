"""
Generates architecture-diagram.png for the Playbook Research platform.
Run: python3 docs/generate_diagram.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ── Palette ────────────────────────────────────────────────────────────────────
NAVY     = "#0a1628"
NAVY2    = "#0f2040"
NAVY3    = "#162d50"
GOLD     = "#c9a84c"
GOLD2    = "#e8c76a"
SLATE    = "#94a3b8"
WHITE    = "#f1f5f9"
GREEN    = "#22c55e"
PURPLE   = "#a855f7"
ORANGE   = "#f97316"
RED      = "#ef4444"
TEAL     = "#14b8a6"

fig, ax = plt.subplots(figsize=(22, 14))
fig.patch.set_facecolor(NAVY)
ax.set_facecolor(NAVY)
ax.set_xlim(0, 22)
ax.set_ylim(0, 14)
ax.axis("off")

def box(x, y, w, h, color, alpha=1.0, radius=0.25):
    rect = FancyBboxPatch((x, y), w, h,
                          boxstyle=f"round,pad=0,rounding_size={radius}",
                          linewidth=0, facecolor=color, alpha=alpha, zorder=2)
    ax.add_patch(rect)

def outline_box(x, y, w, h, edgecolor, facecolor=NAVY2, lw=1.5, radius=0.3):
    rect = FancyBboxPatch((x, y), w, h,
                          boxstyle=f"round,pad=0,rounding_size={radius}",
                          linewidth=lw, edgecolor=edgecolor, facecolor=facecolor,
                          zorder=2)
    ax.add_patch(rect)

def label(x, y, text, color=WHITE, size=8, bold=False, ha="center", va="center", zorder=5):
    weight = "bold" if bold else "normal"
    ax.text(x, y, text, color=color, fontsize=size, fontweight=weight,
            ha=ha, va=va, zorder=zorder, wrap=True)

def arrow(x1, y1, x2, y2, color=SLATE, lw=1.2, style="->"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, connectionstyle="arc3,rad=0.0"),
                zorder=3)

def section_header(x, y, w, text, color):
    box(x, y, w, 0.5, color, alpha=0.85)
    label(x + w/2, y + 0.25, text, color=NAVY, size=8, bold=True)

# ══════════════════════════════════════════════════════════════════════════════
# TITLE
# ══════════════════════════════════════════════════════════════════════════════
label(11, 13.5, "Playbook Research — System Architecture", color=GOLD, size=16, bold=True)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 1 — USERS / CLIENTS  (x: 0.3 – 3.7)
# ══════════════════════════════════════════════════════════════════════════════
outline_box(0.3, 1.0, 3.4, 11.8, GOLD, facecolor="#0c1e38")
label(2.0, 12.55, "CLIENTS", color=GOLD, size=9, bold=True)

# Browser
section_header(0.55, 11.2, 2.9, "Browser", GOLD2)
for i, (icon, txt) in enumerate([
    ("◉", "Research Chat (SSE stream)"),
    ("◫", "Team Workspace"),
    ("⊞", "Session Share View"),
    ("↑", "PDF Upload"),
]):
    y = 10.65 - i * 0.52
    label(0.85, y, icon, color=GOLD, size=9)
    label(2.1, y, txt, color=WHITE, size=7.5, ha="center")

# External API callers
section_header(0.55, 8.15, 2.9, "External Callers", TEAL)
for i, txt in enumerate(["Webhook Receiver", "3rd-party Integrations"]):
    label(2.0, 7.62 - i*0.52, txt, color=WHITE, size=7.5)

# Legend
label(2.0, 1.8, "── SSE Stream", color=GOLD, size=7)
label(2.0, 1.4, "── REST / JSON", color=TEAL, size=7)
label(2.0, 1.0, "── Auth Cookie", color=PURPLE, size=7)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 2 — FRONTEND  (x: 4.0 – 7.8)
# ══════════════════════════════════════════════════════════════════════════════
outline_box(4.0, 1.0, 3.8, 11.8, "#60a5fa", facecolor="#0c1e38")
label(5.9, 12.55, "FRONTEND — SvelteKit", color="#60a5fa", size=9, bold=True)

section_header(4.25, 11.2, 3.3, "Routes", "#60a5fa")
routes = [
    ("/(app)/",        "Main App Shell"),
    ("+page.svelte",   "Research Workspace"),
    ("/teams/[slug]",  "Team Dashboard"),
    ("/share/[id]",    "Read-only Report"),
    ("/login",         "OIDC Login"),
    ("/dashboard",     "Usage Stats"),
    ("/notifications", "Notification Inbox"),
]
for i, (route, desc) in enumerate(routes):
    y = 10.65 - i * 0.52
    label(5.35, y, route, color=GOLD2, size=7, ha="center")
    label(6.6,  y, desc,  color=SLATE, size=7, ha="center")

section_header(4.25, 6.85, 3.3, "Key Components", "#60a5fa")
comps = ["ChatThread.svelte (SSE listener)",
         "ResearchSwimlane.svelte",
         "+layout.server.ts (JWT guard)",
         "api/sessions.ts (REST client)"]
for i, c in enumerate(comps):
    label(5.9, 6.3 - i*0.52, c, color=WHITE, size=7)

section_header(4.25, 4.45, 3.3, "Auth Flow", "#60a5fa")
label(5.9, 4.0,  "JWT httpOnly cookie", color=WHITE, size=7)
label(5.9, 3.52, "OIDC callback handler", color=WHITE, size=7)
label(5.9, 3.04, "30s notification poll", color=WHITE, size=7)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 3 — BACKEND  (x: 8.2 – 14.4)
# ══════════════════════════════════════════════════════════════════════════════
outline_box(8.2, 1.0, 6.2, 11.8, GREEN, facecolor="#0c1e38")
label(11.3, 12.55, "BACKEND — FastAPI (Python / asyncio)", color=GREEN, size=9, bold=True)

# API Routers
section_header(8.45, 11.2, 5.7, "API Routers", GREEN)
routers = [
    ("/api/research",      "SSE stream + async webhook"),
    ("/api/sessions",      "CRUD + share + pin"),
    ("/api/share/{id}",    "Public/team read-only"),
    ("/api/teams",         "RBAC team management"),
    ("/api/auth",          "JWT + OIDC"),
    ("/api/documents",     "PDF upload → Redis"),
    ("/api/comments",      "Threaded + @mentions"),
    ("/api/notifications", "Inbox + mark-read"),
]
for i, (ep, desc) in enumerate(routers):
    y = 10.65 - i * 0.52
    label(9.8,  y, ep,   color=GOLD2, size=7, ha="center")
    label(11.8, y, desc, color=SLATE, size=7, ha="center")

# Research Agent
section_header(8.45, 6.3, 5.7, "Research Agent (PydanticAI)", ORANGE)
phases = [
    "Phase 0 · create_research_plan",
    "Phase 1 · Execute ≥4 tools (web/wiki/fin/docs)",
    "Phase 2 · evaluate_research_completeness",
    "Phase 3 · Dig deeper if confidence < 85%",
    "Phase 4 · Write report + inline citations",
]
for i, p in enumerate(phases):
    label(11.3, 5.75 - i*0.45, p, color=WHITE, size=7)

# Agent Tools
section_header(8.45, 3.4, 5.7, "Agent Tools", ORANGE)
tools = ["web_search (Tavily)", "wiki_lookup (Wikipedia)", "get_financials (yfinance)",
         "search_uploaded_documents (BM25)", "sec_edgar_search"]
for i, t in enumerate(tools):
    label(11.3, 2.88 - i*0.4, "• " + t, color=WHITE, size=7)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 4 — DATA / INFRA  (x: 14.7 – 21.7)
# ══════════════════════════════════════════════════════════════════════════════
outline_box(14.7, 1.0, 7.0, 11.8, PURPLE, facecolor="#0c1e38")
label(18.2, 12.55, "DATA & INFRASTRUCTURE", color=PURPLE, size=9, bold=True)

# PostgreSQL
section_header(14.95, 11.2, 3.0, "PostgreSQL (RDS)", "#818cf8")
tables = ["sessions  •  agent_memory",
          "teams  •  team_members",
          "session_teams  •  users",
          "comments  •  notifications",
          "pinned_sessions  •  team_activity",
          "research_jobs"]
for i, t in enumerate(tables):
    label(16.45, 10.65 - i*0.5, t, color=WHITE, size=7)

# Redis
section_header(14.95, 7.9, 3.0, "Redis / ElastiCache", RED)
label(16.45, 7.4, "PDF text cache (TTL 24h)", color=WHITE, size=7)
label(16.45, 6.95, "Key: pdf:{session_key}", color=SLATE, size=7)
label(16.45, 6.5, "In-memory fallback ✓", color=WHITE, size=7)

# AWS Secrets
section_header(14.95, 5.75, 3.0, "AWS Secrets Manager", TEAL)
label(16.45, 5.28, "DB creds + auto-rotation", color=WHITE, size=7)
label(16.45, 4.83, "Redis token + auto-rotation", color=WHITE, size=7)
label(16.45, 4.38, "InvalidPasswordError → retry", color=SLATE, size=7)

# External AI APIs
section_header(18.2, 11.2, 3.2, "External AI APIs", GOLD2)
apis = ["OpenAI GPT-4o (research + memory)",
        "Anthropic Claude Sonnet",
        "Tavily Search API",
        "Yahoo Finance (yfinance)",
        "Wikipedia API",
        "SEC EDGAR"]
for i, a in enumerate(apis):
    label(19.8, 10.65 - i*0.5, a, color=WHITE, size=7)

# OIDC
section_header(18.2, 7.9, 3.2, "Identity Provider (OIDC)", PURPLE)
label(19.8, 7.4, "Any OpenID Connect provider", color=WHITE, size=7)
label(19.8, 6.95, "→ JWT issued (HS256, 24h)", color=WHITE, size=7)
label(19.8, 6.5, "Dev bypass mode ✓", color=WHITE, size=7)

# Infra
section_header(18.2, 5.75, 3.2, "Deployment", SLATE)
label(19.8, 5.28, "Docker Compose (local)", color=WHITE, size=7)
label(19.8, 4.83, "AWS ECS / RDS / ElastiCache", color=WHITE, size=7)
label(19.8, 4.38, "Health: GET /health", color=SLATE, size=7)

# ══════════════════════════════════════════════════════════════════════════════
# ARROWS — left to right flow
# ══════════════════════════════════════════════════════════════════════════════
# Clients → Frontend
arrow(3.7, 10.3, 4.0, 10.3, color=GOLD)        # SSE research
arrow(3.7, 9.3,  4.0, 9.3,  color=TEAL)        # REST
arrow(3.7, 8.5,  4.0, 8.5,  color=PURPLE)      # Auth

# Frontend → Backend
arrow(7.8, 10.3, 8.2, 10.3, color=GOLD)
arrow(7.8, 9.3,  8.2, 9.3,  color=TEAL)
arrow(7.8, 7.5,  8.2, 7.5,  color=PURPLE)

# Backend → PostgreSQL
arrow(14.4, 10.0, 14.7, 10.0, color="#818cf8")
arrow(14.4, 9.3,  14.7, 9.3,  color="#818cf8")

# Backend → Redis
arrow(14.4, 7.5, 14.95, 7.5, color=RED)

# Backend → AWS Secrets
arrow(14.4, 5.0, 14.95, 5.0, color=TEAL)

# Backend → External AI APIs
arrow(14.4, 11.0, 18.2, 11.0, color=GOLD2)

# Backend → OIDC
arrow(14.4, 7.9, 18.2, 7.9, color=PURPLE)

# ══════════════════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════════════════
plt.tight_layout(pad=0)
plt.savefig("docs/architecture-diagram.png", dpi=180, bbox_inches="tight",
            facecolor=NAVY)
print("Saved docs/architecture-diagram.png")

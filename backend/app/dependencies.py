from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import wikipediaapi
from fastapi import Cookie, HTTPException, Header, status

from app.auth import decode_jwt
from app.config import settings


# ── HTTP Request Context (auth + team scope) ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request context with authenticated user and optional team scope.

    Combines JWT auth and X-Team-Id header extraction into a single
    dependency.  Pass ``ctx.team_id`` to DB functions using ``_acquire_team()``
    for row-level security enforcement.
    """

    user: dict[str, Any]
    team_id: str | None

    @property
    def user_sid(self) -> str:
        return self.user["sub"]


async def get_request_context(
    jwt: str | None = Cookie(default=None, alias="jwt"),
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
) -> RequestContext:
    """Combined dependency: authenticate user + validate team membership.

    If X-Team-Id is provided, verifies the user is a member of that team.
    Raises 403 if the user is not a team member, preventing spoofing.
    """
    if not jwt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user = decode_jwt(jwt)

    if x_team_id:
        from app.db import db_is_team_member
        if not await db_is_team_member(x_team_id, user["sub"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of the specified team",
            )

    return RequestContext(user=user, team_id=x_team_id)


# ── Agent Dependencies (research agent) ─────────────────────────────────────


@dataclass
class AgentDeps:
    tavily_api_key: str
    wiki: wikipediaapi.Wikipedia
    doc_context: str = ""
    doc_texts: list[str] = field(default_factory=list)
    uploaded_filenames: list[str] = field(default_factory=list)
    uploaded_doc_metadata: list[dict] = field(default_factory=list)
    research_plan: list[str] = field(default_factory=list)
    evaluation_count: int = 0
    tool_cache: dict = field(default_factory=dict)
    source_urls: set = field(default_factory=set)
    source_titles: dict[str, str] = field(default_factory=dict)  # url → title
    query_complexity: str = "standard"
    # Enhanced feature fields
    chart_payloads: list[dict] = field(default_factory=list)
    source_claims: dict[str, list[str]] = field(default_factory=dict)
    # Track items_found across evaluations to detect stalled progress
    progress_history: list[int] = field(default_factory=list)
    memory_context: str = ""
    user_rules: list[str] = field(default_factory=list)
    # Clarification fields
    # Bridge for agent-level ask_clarification (set by FunctionToolCallEvent handler)
    pending_clarification_id: str | None = None
    # Bridge for tool-level clarifications (tools put SSE strings here; streaming layer drains it)
    tool_sse_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # All clarification IDs created in this session — used for cleanup on stream disconnect
    active_clarification_ids: list = field(default_factory=list)
    # Team context for KG queries
    team_id: str | None = None  # Deprecated: use team_ids instead
    team_ids: list[str] = field(default_factory=list)
    include_master: bool = False


_DEPTH_MAP = {"fast": "simple", "balanced": "standard", "deep": "deep"}


def get_agent_deps(
    doc_context: str = "",
    doc_texts: list[str] | None = None,
    uploaded_filenames: list[str] | None = None,
    uploaded_doc_metadata: list[dict] | None = None,
    memory_context: str = "",
    depth: str = "balanced",
    user_rules: list[str] | None = None,
    team_ids: list[str] | None = None,
    include_master: bool = False,
    # Deprecated alias — will be removed
    pdf_context: str = "",
) -> AgentDeps:
    resolved_context = doc_context or pdf_context
    return AgentDeps(
        tavily_api_key=settings.tavily_api_key,
        wiki=wikipediaapi.Wikipedia(
            language="en",
            user_agent="m-clone-research-agent/1.0",
        ),
        doc_context=resolved_context,
        doc_texts=doc_texts or [],
        uploaded_filenames=uploaded_filenames or [],
        uploaded_doc_metadata=uploaded_doc_metadata or [],
        memory_context=memory_context,
        query_complexity=_DEPTH_MAP.get(depth, "standard"),
        user_rules=user_rules or [],
        team_ids=team_ids or [],
        include_master=include_master,
    )

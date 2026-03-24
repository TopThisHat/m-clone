import asyncio
from dataclasses import dataclass, field

import wikipediaapi

from app.config import settings


@dataclass
class AgentDeps:
    tavily_api_key: str
    wiki: wikipediaapi.Wikipedia
    pdf_context: str = ""
    uploaded_filenames: list[str] = field(default_factory=list)
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
    pdf_context: str = "",
    uploaded_filenames: list[str] | None = None,
    memory_context: str = "",
    depth: str = "balanced",
    user_rules: list[str] | None = None,
    team_ids: list[str] | None = None,
    include_master: bool = False,
) -> AgentDeps:
    return AgentDeps(
        tavily_api_key=settings.tavily_api_key,
        wiki=wikipediaapi.Wikipedia(
            language="en",
            user_agent="m-clone-research-agent/1.0",
        ),
        pdf_context=pdf_context,
        uploaded_filenames=uploaded_filenames or [],
        memory_context=memory_context,
        query_complexity=_DEPTH_MAP.get(depth, "standard"),
        user_rules=user_rules or [],
        team_ids=team_ids or [],
        include_master=include_master,
    )

"""KG Chat router — SSE streaming chat endpoint and session management.

Follows the patterns in routers/research.py and routers/knowledge_graph.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.kg_chat import (
    KGChatOrchestrator,
    KGFinalResult,
    KGHighlight,
    KGPath,
    KGTextDelta,
    KGToolCallStart,
    KGToolResult,
)
from app.agent.streaming import TextDeltaBatcher
from app.auth import get_current_user
from app.config import settings
from app.db import (
    db_add_chat_message,
    db_create_chat_session,
    db_delete_chat_session,
    db_get_chat_messages,
    db_get_chat_session,
    db_is_super_admin,
    db_is_team_member,
    db_list_chat_sessions,
    db_list_user_teams,
)

_SESSION_MAX_MESSAGES = 50

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/chat", tags=["kg-chat"])

# Rate-limit window in seconds and max messages per window
_RATE_WINDOW_SECS = 60
_RATE_MAX_MESSAGES = 30


# ── Request / response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    team_id: str | None = None


# ── Team resolution (mirrors knowledge_graph.py pattern) ─────────────────────

async def _resolve_team(user: dict[str, Any], team_id: str | None) -> str:
    """Resolve and validate team access. Returns a concrete team_id."""
    sid = user["sub"]

    if team_id:
        if team_id == settings.kg_master_team_id:
            if not await db_is_super_admin(sid):
                raise HTTPException(
                    status_code=403,
                    detail="Super admin access required for master graph",
                )
            return team_id
        is_sa = await db_is_super_admin(sid)
        if not is_sa and not await db_is_team_member(team_id, sid):
            raise HTTPException(status_code=403, detail="Not a member of this team")
        return team_id

    teams = await db_list_user_teams(sid)
    if teams:
        return str(teams[0]["id"])
    raise HTTPException(
        status_code=403,
        detail="You must be part of a team to use KG chat",
    )


# ── Rate limiting via Redis ───────────────────────────────────────────────────

async def _check_rate_limit(user_sid: str) -> None:
    """Enforce 30 messages/min per user via Redis INCR + EXPIRE."""
    try:
        from app.redis_client import get_redis
        redis = await get_redis()
        if redis is None:
            return  # Skip rate limiting if Redis unavailable
        key = f"kg_chat_rate:{user_sid}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _RATE_WINDOW_SECS)
        if count > _RATE_MAX_MESSAGES:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {_RATE_MAX_MESSAGES} messages per minute",
                headers={"Retry-After": str(_RATE_WINDOW_SECS)},
            )
    except HTTPException:
        raise
    except Exception:
        logger.debug("Rate limit check skipped — Redis unavailable", exc_info=True)


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ── Streaming generator ───────────────────────────────────────────────────────

async def _stream_kg_chat(
    message: str,
    team_id: str,
    session_id: str,
    user_sid: str,
) -> AsyncIterator[str]:
    """Drive KGChatOrchestrator and emit SSE events."""
    yield _sse("start", {"session_id": session_id})

    # Persist user message
    await db_add_chat_message(session_id=session_id, role="user", content=message)

    # Load prior messages for context
    prior_messages = await db_get_chat_messages(session_id)
    # Convert to OpenAI format, excluding the message we just saved
    history: list[dict[str, Any]] = []
    for m in prior_messages[:-1]:  # exclude the just-persisted user message
        entry: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            entry["tool_call_id"] = m["tool_call_id"]
        history.append(entry)

    batcher = TextDeltaBatcher()
    accumulated_text = ""
    assistant_entity_highlights: list[str] = []

    try:
        orchestrator = KGChatOrchestrator()
        async for event in orchestrator.run(
            message=message,
            team_id=team_id,
            message_history=history,
        ):
            if isinstance(event, KGTextDelta):
                accumulated_text += event.token
                batched = batcher.add(event.token)
                if batched is not None:
                    yield _sse("text_delta", {"token": batched})

            elif isinstance(event, KGToolCallStart):
                remaining = batcher.flush()
                if remaining:
                    yield _sse("text_delta", {"token": remaining})
                try:
                    args = json.loads(event.arguments_json) if event.arguments_json else {}
                except Exception:
                    args = {}
                yield _sse("tool_call_start", {
                    "call_id": event.call_id,
                    "tool_name": event.name,
                    "args": args,
                    "status": "executing",
                })

            elif isinstance(event, KGToolResult):
                preview = (
                    event.content[:400] + "..."
                    if len(event.content) > 400
                    else event.content
                )
                yield _sse("tool_result", {
                    "call_id": event.call_id,
                    "tool_name": event.name,
                    "preview": preview,
                })

            elif isinstance(event, KGHighlight):
                assistant_entity_highlights.extend(event.entity_ids)
                yield _sse("kg_highlight", {"entity_ids": event.entity_ids})

            elif isinstance(event, KGPath):
                yield _sse("kg_path", {
                    "paths": event.paths,
                    "source_id": event.source_id,
                    "target_id": event.target_id,
                })

            elif isinstance(event, KGFinalResult):
                remaining = batcher.flush()
                if remaining:
                    yield _sse("text_delta", {"token": remaining})

                # Persist assistant message
                unique_highlights = list(dict.fromkeys(assistant_entity_highlights))
                await db_add_chat_message(
                    session_id=session_id,
                    role="assistant",
                    content=event.text,
                    entity_highlights=unique_highlights if unique_highlights else None,
                )

                yield _sse("done", {
                    "session_id": session_id,
                    "entity_highlights": unique_highlights,
                })

    except Exception as exc:
        remaining = batcher.flush()
        if remaining:
            yield _sse("text_delta", {"token": remaining})
        logger.exception("KG chat stream error for session %s", session_id)
        yield _sse("error", {"message": str(exc)})
        yield _sse("done", {"session_id": session_id, "error": True})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("")
async def chat_endpoint(
    body: ChatRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """SSE streaming KG chat endpoint.

    Creates a new session if `session_id` is not provided.
    Rate limited to 30 messages/min per user.
    """
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    sid = user["sub"]
    await _check_rate_limit(sid)

    team_id = await _resolve_team(user, body.team_id)

    # Resolve or create session
    session_id: str
    if body.session_id:
        session = await db_get_chat_session(body.session_id, team_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        session_id = body.session_id
        # Enforce per-session message limit (counts user + assistant messages)
        existing = await db_get_chat_messages(session_id)
        if len(existing) >= _SESSION_MAX_MESSAGES:
            raise HTTPException(
                status_code=429,
                detail=f"Session message limit reached ({_SESSION_MAX_MESSAGES}). Start a new session to continue.",
                headers={"Retry-After": "0"},
            )
    else:
        session = await db_create_chat_session(team_id=team_id, user_sid=sid)
        session_id = session["id"]

    return StreamingResponse(
        _stream_kg_chat(
            message=body.message.strip(),
            team_id=team_id,
            session_id=session_id,
            user_sid=sid,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def list_sessions(
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List the current user's chat sessions for a team."""
    sid = user["sub"]
    resolved_team_id = await _resolve_team(user, team_id)
    return await db_list_chat_sessions(team_id=resolved_team_id, user_sid=sid)


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return all messages for a chat session."""
    resolved_team_id = await _resolve_team(user, team_id)
    session = await db_get_chat_session(session_id, resolved_team_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return await db_get_chat_messages(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    team_id: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a chat session and all its messages."""
    resolved_team_id = await _resolve_team(user, team_id)
    deleted = await db_delete_chat_session(session_id, resolved_team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"status": "deleted", "session_id": session_id}

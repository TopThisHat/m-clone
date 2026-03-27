import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.clarification import clarification_store
from app.agent.streaming import stream_research
from app.auth import get_current_user, get_optional_user
from app.config import settings
from app.db import db_is_super_admin, db_is_team_member, db_list_user_teams
from app.dependencies import get_agent_deps
from app.models.job import AsyncResearchRequest, JobStatus
from app.models.request import ResearchRequest
from app.routers.documents import get_document_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["research"])


class ClarifyRequest(BaseModel):
    answer: str


@router.post("/research/clarify/{clarification_id}")
async def clarify_endpoint(clarification_id: str, body: ClarifyRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    """Resolve a pending clarification Future (works for both agent-level and tool-level paths)."""
    if not body.answer or not body.answer.strip():
        raise HTTPException(status_code=422, detail="answer must not be empty")
    found = clarification_store.set_answer(clarification_id, body.answer.strip())
    if not found:
        raise HTTPException(
            status_code=404,
            detail="Clarification not found — may have expired or already been answered",
        )
    return {"status": "answered", "clarification_id": clarification_id}


@router.get("/config/models")
def available_models() -> list[dict[str, str]]:
    """Return the list of available AI models."""
    models = [
        {"id": "openai:gpt-4o", "label": "GPT-4o", "description": "Flagship"},
        {"id": "openai:gpt-4o-mini", "label": "GPT-4o Mini", "description": "Fast & efficient"},
    ]
    if settings.anthropic_api_key:
        models.append({
            "id": "anthropic:claude-sonnet-4-6",
            "label": "Claude Sonnet",
            "description": "Anthropic",
        })
    return models


@router.post("/research")
async def research_endpoint(body: ResearchRequest, request: Request, user: dict[str, Any] | None = Depends(get_optional_user)) -> StreamingResponse:
    """Stream a research session as Server-Sent Events."""
    doc_session = await get_document_text(body.doc_session_key)

    # Retrieve prior memory context
    memory_ctx = ""
    try:
        from app.agent.memory import retrieve_memories
        memory_ctx = await retrieve_memories(body.query)
    except Exception:
        logger.warning("Failed to retrieve memories for research query", exc_info=True)

    # Resolve team context from authenticated user
    team_ids: list[str] = []
    include_master = False
    if user:
        sid = user["sub"]
        include_master = await db_is_super_admin(sid)
        if body.team_id and await db_is_team_member(body.team_id, sid):
            team_ids = [body.team_id]
        else:
            teams = await db_list_user_teams(sid)
            team_ids = [str(t["id"]) for t in teams]

    deps = get_agent_deps(
        doc_context=doc_session.text,
        doc_texts=doc_session.texts,
        uploaded_filenames=doc_session.filenames,
        uploaded_doc_metadata=doc_session.metadata,
        memory_context=memory_ctx,
        depth=body.depth,
        user_rules=body.rules,
        team_ids=team_ids,
        include_master=include_master,
    )

    return StreamingResponse(
        stream_research(
            query=body.query,
            deps=deps,
            message_history=body.message_history,
            model=body.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _run_async_job(
    job_id: str,
    query: str,
    webhook_url: str,
    doc_session_key: str | None,
    team_ids: list[str] | None = None,
    include_master: bool = False,
) -> None:
    """Background task: run research and POST results to webhook."""
    from app.db import db_update_job

    try:
        await db_update_job(job_id, {"status": "running"})
    except Exception:
        logger.warning("Failed to update job %s status to 'running'", job_id, exc_info=True)

    try:
        doc_session = await get_document_text(doc_session_key)
        memory_ctx = ""
        try:
            from app.agent.memory import retrieve_memories
            memory_ctx = await retrieve_memories(query)
        except Exception:
            logger.warning("Failed to retrieve memories for async job %s", job_id, exc_info=True)

        deps = get_agent_deps(
            doc_context=doc_session.text,
            doc_texts=doc_session.texts,
            uploaded_filenames=doc_session.filenames,
            uploaded_doc_metadata=doc_session.metadata,
            memory_context=memory_ctx,
            team_ids=team_ids or [],
            include_master=include_master,
        )

        # Collect all SSE output into a string
        markdown_parts: list[str] = []
        usage_data: dict = {}
        async for chunk in stream_research(query=query, deps=deps):
            # Extract final_report markdown from SSE stream
            if chunk.startswith("event: final_report"):
                try:
                    import json
                    data_line = [line for line in chunk.split("\n") if line.startswith("data: ")]
                    if data_line:
                        payload = json.loads(data_line[0][6:])
                        markdown_parts.append(payload.get("markdown", ""))
                        usage_data = payload.get("usage", {})
                except Exception:
                    logger.warning("Failed to parse final_report SSE chunk for job %s", job_id, exc_info=True)

        final_markdown = "\n".join(markdown_parts)

        # POST to webhook
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                webhook_url,
                json={
                    "job_id": job_id,
                    "markdown": final_markdown,
                    "usage": usage_data,
                },
            )

        try:
            await db_update_job(job_id, {
                "status": "done",
                "result_markdown": final_markdown,
                "completed_at": datetime.now(timezone.utc),
            })
        except Exception:
            logger.warning("Failed to update job %s status to 'done'", job_id, exc_info=True)

    except Exception as exc:
        try:
            await db_update_job(job_id, {
                "status": "failed",
                "error": str(exc),
                "completed_at": datetime.now(timezone.utc),
            })
        except Exception:
            logger.warning("Failed to update job %s status to 'failed'", job_id, exc_info=True)


@router.post("/research/async", status_code=202)
async def async_research_endpoint(body: AsyncResearchRequest, background_tasks: BackgroundTasks, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    """Submit a research job asynchronously. Results POSTed to webhook_url when done."""
    from app.db import DatabaseNotConfigured, db_create_job

    job_id = str(uuid.uuid4())
    try:
        await db_create_job(job_id, body.query, body.webhook_url, owner_sid=user["sub"])
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="Async jobs require a database connection. Please configure DATABASE_URL.")

    # Resolve team context before spawning background task (no request context there)
    team_ids: list[str] = []
    include_master = False
    sid = user["sub"]
    include_master = await db_is_super_admin(sid)
    if body.team_id and await db_is_team_member(body.team_id, sid):
        team_ids = [body.team_id]
    else:
        teams = await db_list_user_teams(sid)
        team_ids = [str(t["id"]) for t in teams]

    background_tasks.add_task(
        _run_async_job,
        job_id,
        body.query,
        body.webhook_url,
        body.doc_session_key,
        team_ids,
        include_master,
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/research/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str, user: dict[str, Any] = Depends(get_current_user)) -> JobStatus:
    """Get status of an async research job."""
    from app.db import DatabaseNotConfigured, db_get_job

    try:
        job = await db_get_job(job_id)
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("owner_sid") and job["owner_sid"] != user["sub"]:
        raise HTTPException(status_code=403, detail="Access denied")

    return JobStatus(
        job_id=str(job["id"]),
        status=job["status"],
        created_at=job["created_at"],
        result_markdown=job.get("result_markdown", ""),
        error=job.get("error"),
    )

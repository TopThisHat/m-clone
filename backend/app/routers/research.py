import asyncio
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.clarification import clarification_store
from app.agent.streaming import stream_research
from app.auth import get_optional_user
from app.config import settings
from app.dependencies import get_agent_deps
from app.models.job import AsyncResearchRequest, JobStatus
from app.models.request import ResearchRequest
from app.routers.documents import get_pdf_text

router = APIRouter(prefix="/api", tags=["research"])


class ClarifyRequest(BaseModel):
    answer: str


@router.post("/research/clarify/{clarification_id}")
async def clarify_endpoint(clarification_id: str, body: ClarifyRequest):
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
def available_models():
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
async def research_endpoint(body: ResearchRequest, request: Request):
    """Stream a research session as Server-Sent Events."""
    pdf_text, filenames = await get_pdf_text(body.pdf_session_key)

    # Retrieve prior memory context
    memory_ctx = ""
    try:
        from app.agent.memory import retrieve_memories
        memory_ctx = await retrieve_memories(body.query)
    except Exception:
        pass

    deps = get_agent_deps(
        pdf_context=pdf_text,
        uploaded_filenames=filenames,
        memory_context=memory_ctx,
        depth=body.depth,
        user_rules=body.rules,
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


async def _run_async_job(job_id: str, query: str, webhook_url: str, pdf_session_key: str | None):
    """Background task: run research and POST results to webhook."""
    from app.db import db_update_job, DatabaseNotConfigured

    try:
        await db_update_job(job_id, {"status": "running"})
    except Exception:
        pass

    try:
        pdf_text, filenames = await get_pdf_text(pdf_session_key)
        memory_ctx = ""
        try:
            from app.agent.memory import retrieve_memories
            memory_ctx = await retrieve_memories(query)
        except Exception:
            pass

        deps = get_agent_deps(
            pdf_context=pdf_text,
            uploaded_filenames=filenames,
            memory_context=memory_ctx,
        )

        # Collect all SSE output into a string
        markdown_parts: list[str] = []
        usage_data: dict = {}
        async for chunk in stream_research(query=query, deps=deps):
            # Extract final_report markdown from SSE stream
            if chunk.startswith("event: final_report"):
                try:
                    import json
                    data_line = [l for l in chunk.split("\n") if l.startswith("data: ")]
                    if data_line:
                        payload = json.loads(data_line[0][6:])
                        markdown_parts.append(payload.get("markdown", ""))
                        usage_data = payload.get("usage", {})
                except Exception:
                    pass

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
            pass

    except Exception as exc:
        try:
            await db_update_job(job_id, {
                "status": "failed",
                "error": str(exc),
                "completed_at": datetime.now(timezone.utc),
            })
        except Exception:
            pass


@router.post("/research/async", status_code=202)
async def async_research_endpoint(body: AsyncResearchRequest, background_tasks: BackgroundTasks):
    """Submit a research job asynchronously. Results POSTed to webhook_url when done."""
    from app.db import db_create_job, DatabaseNotConfigured

    job_id = str(uuid.uuid4())
    try:
        await db_create_job(job_id, body.query, body.webhook_url)
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="Async jobs require a database connection. Please configure DATABASE_URL.")

    background_tasks.add_task(
        _run_async_job,
        job_id,
        body.query,
        body.webhook_url,
        body.pdf_session_key,
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/research/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of an async research job."""
    from app.db import db_get_job, DatabaseNotConfigured

    try:
        job = await db_get_job(job_id)
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatus(
        job_id=str(job["id"]),
        status=job["status"],
        created_at=job["created_at"],
        result_markdown=job.get("result_markdown", ""),
        error=job.get("error"),
    )

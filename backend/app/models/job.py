from __future__ import annotations

from pydantic import BaseModel


class AsyncResearchRequest(BaseModel):
    query: str
    webhook_url: str
    pdf_session_key: str | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | done | failed
    created_at: str
    result_markdown: str = ""
    error: str | None = None

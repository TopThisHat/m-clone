from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, model_validator

logger = logging.getLogger(__name__)


class AsyncResearchRequest(BaseModel):
    query: str
    webhook_url: str
    doc_session_key: str | None = None
    team_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_pdf_session_key(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        old = data.pop("pdf_session_key", None)
        if old is not None:
            logger.warning("pdf_session_key is deprecated, use doc_session_key")
            if data.get("doc_session_key") is None:
                data["doc_session_key"] = old
        return data


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | done | failed
    created_at: str
    result_markdown: str = ""
    error: str | None = None

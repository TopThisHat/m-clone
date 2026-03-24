import logging
from typing import Any

from pydantic import BaseModel, model_validator

logger = logging.getLogger(__name__)


class ResearchRequest(BaseModel):
    query: str
    doc_session_key: str | None = None
    message_history: list[Any] | None = None
    depth: str = "balanced"   # "fast" | "balanced" | "deep"
    model: str | None = None
    rules: list[str] = []
    team_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_pdf_session_key(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        old = data.pop("pdf_session_key", None)
        if old is not None:
            logger.warning("pdf_session_key is deprecated, use doc_session_key")
            # doc_session_key wins when both are provided
            if data.get("doc_session_key") is None:
                data["doc_session_key"] = old
        return data

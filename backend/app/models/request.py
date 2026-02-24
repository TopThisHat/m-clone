from typing import Any

from pydantic import BaseModel


class ResearchRequest(BaseModel):
    query: str
    pdf_session_key: str | None = None
    message_history: list[Any] | None = None
    depth: str = "balanced"   # "fast" | "balanced" | "deep"
    model: str | None = None

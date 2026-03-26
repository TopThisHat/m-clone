from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str
    query: str
    report_markdown: str = ""
    message_history: list[Any] = []
    trace_steps: list[Any] = []
    owner_sid: str | None = None
    visibility: str = "private"
    doc_session_key: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = None
    report_markdown: str | None = None
    message_history: list[Any] | None = None
    trace_steps: list[Any] | None = None
    is_public: bool | None = None
    usage_tokens: int | None = None
    visibility: str | None = None
    doc_session_key: str | None = None


class SessionSummary(BaseModel):
    id: str
    title: str
    query: str
    created_at: str
    updated_at: str
    is_public: bool = False
    usage_tokens: int = 0
    owner_sid: str | None = None
    visibility: str = "private"


class SessionFull(SessionSummary):
    report_markdown: str
    message_history: list[Any]
    trace_steps: list[Any]
    doc_session_key: str | None = None

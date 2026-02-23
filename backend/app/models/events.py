from enum import Enum

from pydantic import BaseModel


class TraceStepType(str, Enum):
    START = "start"
    TOOL_CALL_START = "tool_call_start"
    TOOL_EXECUTING = "tool_executing"
    TOOL_RESULT = "tool_result"
    TEXT_DELTA = "text_delta"
    REASONING_START = "reasoning_start"
    FINAL_REPORT = "final_report"
    DONE = "done"
    ERROR = "error"


class SSEEvent(BaseModel):
    event_type: TraceStepType
    data: dict

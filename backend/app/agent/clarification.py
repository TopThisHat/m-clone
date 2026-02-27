from __future__ import annotations
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.dependencies import AgentDeps

logger = logging.getLogger(__name__)
# No TTL — clarifications wait indefinitely until answered or stream closes.


@dataclass
class PendingClarification:
    future: asyncio.Future[str]
    question: str
    context: str | None
    options: list[str]

    def cancel(self, reason: str = "disconnected") -> None:
        if not self.future.done():
            self.future.set_result(f"__CANCELLED__:{reason}")


class ClarificationStore:
    """Process-level singleton. Safe because asyncio is single-threaded."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingClarification] = {}

    def register(
        self,
        clarification_id: str,
        question: str,
        context: str | None = None,
        options: list[str] | None = None,
    ) -> asyncio.Future[str]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        pending = PendingClarification(
            future=future,
            question=question,
            context=context,
            options=options or [],
        )
        self._pending[clarification_id] = pending
        return future

    def set_answer(self, clarification_id: str, answer: str) -> bool:
        pending = self._pending.pop(clarification_id, None)
        if pending is None:
            return False
        if not pending.future.done():
            pending.future.set_result(answer)
        return True

    def get_pending(self, clarification_id: str) -> PendingClarification | None:
        return self._pending.get(clarification_id)

    def cancel_session(
        self, clarification_ids: list[str], reason: str = "disconnected"
    ) -> None:
        """Cancel all pending clarifications for a session (called when stream closes)."""
        for cid in clarification_ids:
            pending = self._pending.pop(cid, None)
            if pending:
                logger.info("Cancelling clarification %s: %s", cid, reason)
                pending.cancel(reason)


clarification_store = ClarificationStore()


async def clarify_within_tool(
    deps: "AgentDeps",
    question: str,
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """
    Call this from inside any tool to pause and ask the user a question.

    The streaming layer polls deps.tool_sse_queue and will emit the
    clarification_needed SSE within ~100ms. The tool then blocks indefinitely
    until the user responds via POST /api/research/clarify/{id}.
    If the SSE stream closes before the user answers, the stream_research
    finally block calls clarification_store.cancel_session() and this
    await will resolve with a cancellation message so the tool can exit cleanly.

    Returns the user's answer string, or a fallback if the stream was closed.
    """
    clarification_id = str(uuid.uuid4())
    future = clarification_store.register(clarification_id, question, context, options)
    deps.active_clarification_ids.append(clarification_id)

    # Build the SSE string and put it in the outbox for the streaming layer to emit
    sse_payload = {
        "clarification_id": clarification_id,
        "question": question,
        "context": context,
        "options": options or [],
    }
    sse_string = f"event: clarification_needed\ndata: {json.dumps(sse_payload)}\n\n"
    await deps.tool_sse_queue.put(sse_string)

    # Wait indefinitely — no timeout
    answer = await future

    if answer.startswith("__CANCELLED__:"):
        reason = answer.split(":", 1)[1]
        return f"No user answer ({reason}) — proceed with best judgment"

    # Emit clarification_answered so the frontend card turns green immediately
    answered_sse = (
        f"event: clarification_answered\n"
        f"data: {json.dumps({'clarification_id': clarification_id, 'answer': answer})}\n\n"
    )
    await deps.tool_sse_queue.put(answered_sse)

    return answer

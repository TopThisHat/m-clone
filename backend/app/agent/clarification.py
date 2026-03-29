from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass

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

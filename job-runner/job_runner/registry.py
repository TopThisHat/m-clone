from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseWorkflow(ABC):
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job
        self.job_id: str = str(job["id"])
        self.payload: dict = job.get("payload") or {}

    @abstractmethod
    async def run(self) -> None: ...

    @classmethod
    async def on_dead(cls, job: dict[str, Any]) -> None:
        """
        Called when this job has exhausted all retries and moved to dead.
        Override to trigger parent finalization, alerts, cleanup, etc.
        Default: no-op.
        """


class WorkflowRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, type[BaseWorkflow]] = {}

    def register(self, job_type: str):
        def decorator(cls: type[BaseWorkflow]) -> type[BaseWorkflow]:
            self._handlers[job_type] = cls
            logger.debug("Registered workflow handler: %s", job_type)
            return cls
        return decorator

    async def dispatch(self, job: dict[str, Any]) -> None:
        job_type = job["job_type"]
        handler_cls = self._handlers.get(job_type)
        if handler_cls is None:
            raise ValueError(f"No handler registered for job_type={job_type!r}")
        await handler_cls(job).run()

    async def dispatch_on_dead(self, job: dict[str, Any]) -> None:
        """Called after a job transitions to dead. Delegates to the handler's on_dead hook."""
        handler_cls = self._handlers.get(job["job_type"])
        if handler_cls is None:
            return
        try:
            await handler_cls.on_dead(job)
        except Exception as exc:
            logger.error("on_dead hook failed for job %s (%s): %s", job["id"], job["job_type"], exc)


registry = WorkflowRegistry()

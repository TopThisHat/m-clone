"""
ResearchWorkflow — stub for future async research job support.
"""
from __future__ import annotations

import logging

from job_runner.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)


@registry.register("research")
class ResearchWorkflow(BaseWorkflow):
    """
    payload: {"query": str, "webhook_url": str, "session_id": str (optional)}
    """

    async def run(self) -> None:
        logger.info("ResearchWorkflow job=%s: not yet implemented", self.job_id)
        raise NotImplementedError("ResearchWorkflow is a future feature")

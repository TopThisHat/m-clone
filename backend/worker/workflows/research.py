"""
Research workflow stub — placeholder for future research job handling.
"""
from __future__ import annotations

import logging

from worker.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)


@registry.register("research")
class ResearchWorkflow(BaseWorkflow):
    async def run(self) -> None:
        logger.info("ResearchWorkflow: not yet implemented (job_id=%s)", self.job_id)

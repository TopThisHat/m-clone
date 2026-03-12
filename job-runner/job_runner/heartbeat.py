from __future__ import annotations

import asyncio
import logging

from job_runner.queue import update_heartbeat

logger = logging.getLogger(__name__)


class HeartbeatManager:
    def __init__(self, job_id: str, interval: int) -> None:
        self._job_id = job_id
        self._interval = interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await update_heartbeat(self._job_id)
            except Exception as exc:
                logger.warning("Heartbeat failed for job %s: %s", self._job_id, exc)

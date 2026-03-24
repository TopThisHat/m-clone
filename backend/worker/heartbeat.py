from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


_MAX_CONSECUTIVE_FAILURES = 5


class HeartbeatManager:
    def __init__(self, job_id: str, interval: int) -> None:
        self._job_id = job_id
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._consecutive_failures = 0
        self.healthy = True

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
        from app.job_queue import update_heartbeat
        while True:
            await asyncio.sleep(self._interval)
            try:
                await update_heartbeat(self._job_id)
                self._consecutive_failures = 0
            except Exception as exc:
                self._consecutive_failures += 1
                logger.warning(
                    "Heartbeat failed for job %s (%d/%d): %s",
                    self._job_id, self._consecutive_failures,
                    _MAX_CONSECUTIVE_FAILURES, exc,
                )
                if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "Heartbeat for job %s failed %d consecutive times — marking unhealthy",
                        self._job_id, self._consecutive_failures,
                    )
                    self.healthy = False
                    return

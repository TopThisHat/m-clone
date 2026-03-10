"""
Redis Streams wrapper for the entity extraction pipeline.

Messages are published by the API (streaming.py / workflows.py) and consumed
by the background worker (worker/entity_extraction.py).
"""
from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)

STREAM_KEY = "entity_extraction"
GROUP_NAME = "extractor"
_CONSUMER_NAME = f"extractor-{socket.gethostname()}"

_redis = None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    from app.config import settings
    import redis.asyncio as aioredis

    url = settings.redis_url
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    _redis = aioredis.from_url(url, decode_responses=True)
    return _redis


async def publish_for_extraction(session_id: str, report_md: str) -> None:
    """Publish a report to the entity_extraction Redis stream."""
    if not report_md or not report_md.strip():
        return
    try:
        r = await _get_redis()
        await r.xadd(STREAM_KEY, {"session_id": session_id, "report_md": report_md})
        logger.debug("Published extraction task for session_id=%s", session_id)
    except Exception as exc:
        logger.warning("Failed to publish extraction task for session_id=%s: %s", session_id, exc)


async def create_consumer_group() -> None:
    """Create the consumer group if it doesn't already exist."""
    try:
        r = await _get_redis()
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="$", mkstream=True)
        logger.info("Created Redis consumer group '%s' on stream '%s'", GROUP_NAME, STREAM_KEY)
    except Exception as exc:
        # BUSYGROUP means group already exists — that's fine
        if "BUSYGROUP" in str(exc):
            logger.debug("Consumer group '%s' already exists", GROUP_NAME)
        else:
            logger.warning("xgroup_create failed: %s", exc)


async def consume_next() -> tuple[str, dict] | None:
    """
    Block up to 5 seconds waiting for the next undelivered message.
    Returns (msg_id, data_dict) or None if timed out.
    """
    try:
        r = await _get_redis()
        results = await r.xreadgroup(
            GROUP_NAME,
            _CONSUMER_NAME,
            {STREAM_KEY: ">"},
            count=1,
            block=5000,
        )
        if not results:
            return None
        _stream, messages = results[0]
        msg_id, data = messages[0]
        return msg_id, data
    except Exception as exc:
        logger.warning("consume_next error: %s", exc)
        return None


async def ack_message(msg_id: str) -> None:
    """Acknowledge a processed message."""
    try:
        r = await _get_redis()
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except Exception as exc:
        logger.warning("xack failed for msg_id=%s: %s", msg_id, exc)

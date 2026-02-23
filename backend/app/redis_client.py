"""
Async Redis helper with in-memory fallback.
If REDIS_URL is not configured the app continues to work using a plain dict.
"""
from __future__ import annotations

import json
from typing import Any

from app.config import settings

# In-memory fallback store: {key: (text, filename)}
_memory_store: dict[str, tuple[str, str]] = {}

_redis_client: Any = None


async def _get_client():
    global _redis_client
    if not settings.redis_url:
        return None
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            _redis_client = None
    return _redis_client


async def set_pdf(key: str, text: str, filename: str, ttl_hours: int | None = None) -> None:
    """Store extracted PDF text. Falls back to in-memory dict if Redis is unavailable."""
    ttl = (ttl_hours or settings.redis_ttl_hours) * 3600
    client = await _get_client()
    if client is not None:
        try:
            payload = json.dumps({"text": text, "filename": filename})
            await client.setex(f"pdf:{key}", ttl, payload)
            return
        except Exception:
            pass
    # Fallback
    _memory_store[key] = (text, filename)


async def get_pdf(key: str) -> tuple[str, str] | None:
    """Retrieve extracted PDF text and filename. Returns None if not found."""
    client = await _get_client()
    if client is not None:
        try:
            raw = await client.get(f"pdf:{key}")
            if raw:
                data = json.loads(raw)
                return data["text"], data["filename"]
            return None
        except Exception:
            pass
    # Fallback
    return _memory_store.get(key)

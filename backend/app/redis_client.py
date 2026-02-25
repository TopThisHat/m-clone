"""
Async Redis helper with in-memory fallback.

In dev, set REDIS_URL.
In dev/uat/prod, set AWS_ELASTICACHE_SECRET_NAME instead; the secret must be a
JSON object with keys: url (or host+port) and auth_token.
TLS (rediss://) is always used when connecting via a secret.

Token rotation is handled transparently: if a command raises AuthenticationError
the client is torn down, the cached secret is evicted, a fresh one is fetched
from Secrets Manager, and the command is retried once.  All other errors fall
back to the in-memory store so the app keeps running without Redis.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Resolved once at first use; falls back to a sentinel that is never raised
# so the except clauses below are safe even when redis isn't installed.
try:
    from redis.exceptions import AuthenticationError as _RedisAuthError
except ImportError:
    _RedisAuthError = type("_RedisAuthError", (Exception,), {})  # type: ignore[assignment,misc]

# In-memory fallback store: {key: (text, filename)}
_memory_store: dict[str, tuple[str, str]] = {}

_redis_client: Any = None
_client_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def _get_client() -> Any:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    async with _get_lock():
        if _redis_client is not None:
            return _redis_client
        _redis_client = await _create_client()
        return _redis_client


async def _create_client() -> Any:
    """Build and return a new redis.asyncio client, or None if unconfigured."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return None

    if settings.aws_elasticache_secret_name:
        try:
            from app.secrets import build_redis_url, get_redis_secret
            secret = get_redis_secret(settings.aws_elasticache_secret_name, settings.aws_region)
            url, token = build_redis_url(secret)
            kwargs: dict[str, Any] = {
                "decode_responses": True,
                "ssl_cert_reqs": "none",   # ElastiCache uses self-signed certs by default
            }
            if token:
                kwargs["password"] = token
            client = aioredis.from_url(url, **kwargs)
            logger.info("Redis client created via Secrets Manager")
            return client
        except Exception as exc:
            logger.error("Failed to create Redis client from secret: %s", exc)
            return None

    if settings.redis_url:
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            logger.info("Redis client created from REDIS_URL")
            return client
        except Exception as exc:
            logger.error("Failed to create Redis client: %s", exc)
            return None

    return None


async def _reset_client() -> None:
    """
    Tear down the current client and evict the cached secret so the next
    _get_client() call re-fetches credentials and builds a fresh connection.
    Called automatically when a token-rotation auth error is detected.
    """
    global _redis_client
    async with _get_lock():
        old_client, _redis_client = _redis_client, None
        if settings.aws_elasticache_secret_name:
            from app.secrets import invalidate_redis_secret
            invalidate_redis_secret()
    if old_client is not None:
        try:
            await old_client.aclose()
        except Exception:
            pass
    logger.warning("Redis client reset — fresh credentials will be fetched on next request")


async def set_pdf(key: str, text: str, filename: str, ttl_hours: int | None = None) -> None:
    """Store extracted PDF text. Falls back to in-memory dict if Redis is unavailable."""
    ttl = (ttl_hours or settings.redis_ttl_hours) * 3600
    client = await _get_client()
    if client is not None:
        try:
            payload = json.dumps({"text": text, "filename": filename})
            await client.setex(f"pdf:{key}", ttl, payload)
            return
        except _RedisAuthError as exc:
            logger.warning("Redis auth error on set — attempting rotation recovery: %s", exc)
            await _reset_client()
            client = await _get_client()
            if client is not None:
                try:
                    payload = json.dumps({"text": text, "filename": filename})
                    await client.setex(f"pdf:{key}", ttl, payload)
                    return
                except Exception:
                    pass
        except Exception:
            pass
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
        except _RedisAuthError as exc:
            logger.warning("Redis auth error on get — attempting rotation recovery: %s", exc)
            await _reset_client()
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
        except Exception:
            pass
    return _memory_store.get(key)



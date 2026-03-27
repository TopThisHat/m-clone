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
import os
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_EXTENSION_TYPE_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
}


@dataclass
class DocumentSession:
    text: str
    texts: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)


def _infer_type_from_filename(filename: str) -> str:
    _, ext = os.path.splitext(filename.lower())
    return _EXTENSION_TYPE_MAP.get(ext, "unknown")


# Resolved once at first use; falls back to a sentinel that is never raised
# so the except clauses below are safe even when redis isn't installed.
try:
    from redis.exceptions import AuthenticationError as _RedisAuthError
except ImportError:
    _RedisAuthError = type("_RedisAuthError", (Exception,), {})  # type: ignore[assignment,misc]

# In-memory fallback store
_memory_store: dict[str, Any] = {}

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


async def set_documents(
    key: str,
    docs: list[dict],
    ttl_hours: int | None = None,
) -> None:
    """Store a list of document entries under ``doc:<key>``.

    Each entry should contain at minimum ``filename``, ``text``, ``type``, and
    ``char_count``.  Falls back to in-memory dict if Redis is unavailable.
    """
    ttl = (ttl_hours or settings.redis_ttl_hours) * 3600
    client = await _get_client()
    if client is not None:
        try:
            payload = json.dumps(docs)
            await client.setex(f"doc:{key}", ttl, payload)
            return
        except _RedisAuthError as exc:
            logger.warning("Redis auth error on set_documents — attempting rotation recovery: %s", exc)
            await _reset_client()
            client = await _get_client()
            if client is not None:
                try:
                    payload = json.dumps(docs)
                    await client.setex(f"doc:{key}", ttl, payload)
                    return
                except Exception:
                    pass
        except Exception:
            pass
    _memory_store[key] = docs


# Maximum number of WATCH/MULTI/EXEC retries before giving up on an atomic append.
_APPEND_MAX_RETRIES = 5


async def append_document(
    session_key: str,
    filename: str,
    text: str,
    doc_type: str | None = None,
    char_count: int | None = None,
    metadata_fields: dict | None = None,
    ttl_hours: int | None = None,
    session_cap: int | None = None,
) -> tuple[list[dict], bool]:
    """Atomically append a document to an existing session.

    Uses WATCH/MULTI/EXEC optimistic locking so concurrent uploads to the same
    ``session_key`` cannot overwrite each other.  The ``session_cap`` check is
    performed *inside* the atomic block, eliminating the TOCTOU window.

    Args:
        session_key: Redis session identifier.
        filename: Original filename of the uploaded document.
        text: Extracted text content.
        doc_type: Explicit document type; inferred from filename if omitted.
        char_count: Explicit char count; computed from ``text`` if omitted.
        metadata_fields: Extra per-document fields (pages, sheets, rows, …).
        ttl_hours: Override TTL; falls back to ``settings.redis_ttl_hours``.
        session_cap: Maximum total characters allowed in the session.  If the
            appended text would exceed this limit, the text is truncated to fit
            and the returned ``truncated`` flag is ``True``.

    Returns:
        A ``(docs_metadata, truncated)`` tuple where ``docs_metadata`` is the
        full per-document metadata list (text stripped) and ``truncated``
        indicates whether the text was truncated to respect ``session_cap``.

    Raises:
        RuntimeError: If the atomic append fails after ``_APPEND_MAX_RETRIES``
            concurrent-write conflicts (extremely unlikely in practice).
    """
    ttl = (ttl_hours or settings.redis_ttl_hours) * 3600
    resolved_type = doc_type or _infer_type_from_filename(filename)
    resolved_char_count = char_count if char_count is not None else len(text)

    entry: dict[str, Any] = {
        "filename": filename,
        "text": text,
        "type": resolved_type,
        "char_count": resolved_char_count,
    }
    if metadata_fields:
        for k, v in metadata_fields.items():
            if k not in entry:
                entry[k] = v

    docs: list[dict] = []
    truncated = False

    client = await _get_client()
    if client is not None:
        try:
            docs, truncated = await _redis_append(client, session_key, entry, ttl, session_cap)
        except _RedisAuthError as exc:
            logger.warning("Redis auth error on append_document — attempting rotation recovery: %s", exc)
            await _reset_client()
            client = await _get_client()
            if client is not None:
                try:
                    docs, truncated = await _redis_append(client, session_key, entry, ttl, session_cap)
                except Exception:
                    docs, truncated = _memory_append(session_key, entry, session_cap)
            else:
                docs, truncated = _memory_append(session_key, entry, session_cap)
        except Exception:
            docs, truncated = _memory_append(session_key, entry, session_cap)
    else:
        docs, truncated = _memory_append(session_key, entry, session_cap)

    # Return metadata only (strip text)
    return [{k: v for k, v in d.items() if k != "text"} for d in docs], truncated


async def _redis_append(
    client: Any,
    key: str,
    entry: dict,
    ttl: int,
    session_cap: int | None = None,
) -> tuple[list[dict], bool]:
    """Atomically append *entry* to the session list using WATCH/MULTI/EXEC.

    Retries up to ``_APPEND_MAX_RETRIES`` times on concurrent-write conflicts.
    The session cap check runs inside the atomic block so no TOCTOU window
    exists between reading the current total and writing the new document.

    Returns:
        ``(full_docs_list, truncated)`` — the complete list after append and a
        flag indicating whether ``entry["text"]`` was truncated to fit the cap.
    """
    try:
        from redis.exceptions import WatchError
    except ImportError:  # redis not installed — unreachable in practice
        WatchError = type("WatchError", (Exception,), {})  # type: ignore[assignment,misc]

    doc_key = f"doc:{key}"
    pdf_key = f"pdf:{key}"

    for _ in range(_APPEND_MAX_RETRIES):
        async with client.pipeline() as pipe:
            try:
                # WATCH both keys so a concurrent migration also triggers retry.
                await pipe.watch(doc_key, pdf_key)

                # Read phase — pipeline is in immediate-execution mode after WATCH.
                docs: list[dict] = []
                migrated = False

                raw = await pipe.get(doc_key)
                if raw:
                    docs = json.loads(raw)
                else:
                    old_raw = await pipe.get(pdf_key)
                    if old_raw:
                        migrated = True
                        old = json.loads(old_raw)
                        if isinstance(old, dict):
                            docs = [{
                                "filename": old.get("filename", "document.pdf"),
                                "text": old.get("text", ""),
                                "type": _infer_type_from_filename(
                                    old.get("filename", "document.pdf")
                                ),
                                "char_count": len(old.get("text", "")),
                            }]
                        elif isinstance(old, list):
                            docs = old

                # Enforce session cap inside the transaction (eliminates TOCTOU).
                actual_entry = entry
                truncated = False
                if session_cap is not None:
                    current_total = sum(d.get("char_count", 0) for d in docs)
                    entry_chars = entry.get("char_count", len(entry.get("text", "")))
                    if current_total + entry_chars > session_cap:
                        allowed = max(0, session_cap - current_total)
                        actual_entry = {
                            **entry,
                            "text": entry.get("text", "")[:allowed],
                            "char_count": allowed,
                        }
                        truncated = True

                new_docs = [*docs, actual_entry]

                # Write phase — pipeline enters buffered MULTI mode.
                pipe.multi()
                pipe.setex(doc_key, ttl, json.dumps(new_docs))
                if migrated:
                    pipe.delete(pdf_key)
                await pipe.execute()  # raises WatchError if key changed mid-flight

                return new_docs, truncated

            except WatchError:
                continue  # concurrent writer changed the key; retry

    raise RuntimeError(
        f"append_document: failed to write session '{key}' after "
        f"{_APPEND_MAX_RETRIES} concurrent-write retries"
    )


def _memory_append(
    key: str,
    entry: dict,
    session_cap: int | None = None,
) -> tuple[list[dict], bool]:
    """In-memory fallback for append_document, with old-format migration.

    asyncio is single-threaded so there is no race condition in this path.
    The session cap is still enforced here for consistency with the Redis path.
    """
    existing = _memory_store.get(key)
    docs: list[dict] = []

    if existing is not None:
        if isinstance(existing, tuple) and len(existing) == 2:
            old_text, old_fn = existing
            docs = [{
                "filename": old_fn,
                "text": old_text,
                "type": _infer_type_from_filename(old_fn),
                "char_count": len(old_text),
            }]
        elif isinstance(existing, list):
            docs = existing
        elif isinstance(existing, dict):
            docs = [{
                "filename": existing.get("filename", "document.pdf"),
                "text": existing.get("text", ""),
                "type": _infer_type_from_filename(existing.get("filename", "document.pdf")),
                "char_count": len(existing.get("text", "")),
            }]

    actual_entry = entry
    truncated = False
    if session_cap is not None:
        current_total = sum(d.get("char_count", 0) for d in docs)
        entry_chars = entry.get("char_count", len(entry.get("text", "")))
        if current_total + entry_chars > session_cap:
            allowed = max(0, session_cap - current_total)
            actual_entry = {
                **entry,
                "text": entry.get("text", "")[:allowed],
                "char_count": allowed,
            }
            truncated = True

    docs.append(actual_entry)
    _memory_store[key] = docs
    return docs, truncated


async def get_documents(session_key: str) -> DocumentSession | None:
    """Retrieve all documents for a session as a ``DocumentSession``.

    Checks ``doc:`` prefix first, falls back to ``pdf:`` for migration.
    Handles both old dict and old tuple formats in the in-memory store.
    """
    client = await _get_client()
    if client is not None:
        try:
            return await _redis_get_documents(client, session_key)
        except _RedisAuthError as exc:
            logger.warning("Redis auth error on get_documents — attempting rotation recovery: %s", exc)
            await _reset_client()
            client = await _get_client()
            if client is not None:
                try:
                    return await _redis_get_documents(client, session_key)
                except Exception:
                    pass
        except Exception:
            pass

    return _memory_get_documents(session_key)


async def _redis_get_documents(client: Any, key: str) -> DocumentSession | None:
    """Load documents from Redis, trying ``doc:`` then ``pdf:`` prefix."""
    raw = await client.get(f"doc:{key}")
    if raw:
        docs = json.loads(raw)
        return _docs_list_to_session(docs)

    raw = await client.get(f"pdf:{key}")
    if raw:
        old = json.loads(raw)
        if isinstance(old, dict):
            old_text = old.get("text", "")
            return DocumentSession(
                text=old_text,
                texts=[old_text],
                filenames=[old.get("filename", "document.pdf")],
                metadata=[{
                    "filename": old.get("filename", "document.pdf"),
                    "type": _infer_type_from_filename(old.get("filename", "document.pdf")),
                    "char_count": len(old_text),
                }],
            )
        if isinstance(old, list):
            return _docs_list_to_session(old)

    return None


def _memory_get_documents(key: str) -> DocumentSession | None:
    """Build a ``DocumentSession`` from the in-memory fallback store."""
    existing = _memory_store.get(key)
    if existing is None:
        return None

    if isinstance(existing, tuple) and len(existing) == 2:
        text, fn = existing
        return DocumentSession(
            text=text,
            texts=[text],
            filenames=[fn],
            metadata=[{
                "filename": fn,
                "type": _infer_type_from_filename(fn),
                "char_count": len(text),
            }],
        )

    if isinstance(existing, list):
        return _docs_list_to_session(existing)

    if isinstance(existing, dict):
        old_text = existing.get("text", "")
        return DocumentSession(
            text=old_text,
            texts=[old_text],
            filenames=[existing.get("filename", "document.pdf")],
            metadata=[{
                "filename": existing.get("filename", "document.pdf"),
                "type": _infer_type_from_filename(existing.get("filename", "document.pdf")),
                "char_count": len(old_text),
            }],
        )

    return None


def _docs_list_to_session(docs: list[dict]) -> DocumentSession:
    """Convert a list of doc entries into a ``DocumentSession``."""
    texts = [d.get("text", "") for d in docs]
    filenames = [d.get("filename", "") for d in docs]
    metadata = [{k: v for k, v in d.items() if k != "text"} for d in docs]
    return DocumentSession(
        text="\n\n".join(texts),
        texts=texts,
        filenames=filenames,
        metadata=metadata,
    )


# ---- Deprecated wrappers ----


async def set_pdf(key: str, text: str, filename: str, ttl_hours: int | None = None) -> None:
    """Store extracted PDF text. Falls back to in-memory dict if Redis is unavailable.

    .. deprecated:: Use :func:`set_documents` instead.
    """
    logger.warning("set_pdf is deprecated, use set_documents")
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
    """Retrieve extracted PDF text and filename. Returns None if not found.

    .. deprecated:: Use :func:`get_documents` instead.
    """
    logger.warning("get_pdf is deprecated, use get_documents")
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



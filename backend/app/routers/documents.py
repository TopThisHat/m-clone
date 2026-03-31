import datetime
import logging
import math
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import settings
from app.document_intelligence import analyze_schema, query_document
from app.document_parser import (
    SUPPORTED_EXTENSIONS,
    extract_text,
    get_extension,
    get_format_metadata,
    validate_mime,
)
from app.redis_client import (
    DocumentSession,
    append_document,
    get_documents,
    set_documents,
)
from app.streams import publish_for_extraction

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

SESSION_TEXT_CAP = 500_000

# ── Request / Response models ────────────────────────────────────────────────


class DocumentQueryRequest(BaseModel):
    session_key: str
    query: str = Field(max_length=1000)


class DocumentQueryResponse(BaseModel):
    matches: list = []
    query_interpretation: str = ""
    total_matches: int = 0
    error: str | None = None


@router.get("/status")
async def document_status(
    session_key: str = Query(...),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Check whether a document session key still has content in Redis."""
    session = await get_documents(session_key)
    alive = session is not None and bool(session.text)
    return {"alive": alive}


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session_key: str | None = Query(None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Upload a document for use in research sessions."""
    filename = file.filename or ""
    ext = get_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({size_mb:.1f}MB) exceeds the {settings.max_upload_size_mb}MB limit.",
        )

    try:
        validate_mime(contents, filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    # Extract metadata and text in a single try/except — if metadata fails,
    # the same library would fail on text extraction too.
    try:
        format_meta = get_format_metadata(contents, filename, ext)
        text = await extract_text(contents, filename)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to extract text from '{filename}': {exc}",
        ) from exc

    if not text or not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the file. It may be empty or corrupted.",
        )

    doc_type = format_meta.get("type", "unknown")
    truncated = False

    # Build per-document metadata entry (for the response and Redis)
    doc_meta: dict = {
        "filename": filename,
        "type": doc_type,
        "char_count": len(text),
    }
    # Add format-specific fields (pages, sheets, rows)
    for key in ("pages", "sheets", "rows"):
        if key in format_meta:
            doc_meta[key] = format_meta[key]

    # Session handling
    is_append = False
    existing: DocumentSession | None = None
    if session_key:
        existing = await get_documents(session_key)
        if existing and existing.filenames:
            is_append = True

    session_for_bg: DocumentSession

    if is_append:
        # session_total and truncation are computed *inside* append_document's
        # atomic WATCH/MULTI/EXEC block, eliminating the TOCTOU window that
        # existed when we read-then-wrote outside the transaction.
        docs_list, truncated = await append_document(
            session_key,
            filename,
            text,
            doc_type=doc_type,
            char_count=len(text),
            metadata_fields={k: v for k, v in doc_meta.items()
                             if k not in ("filename", "type", "char_count")},
            session_cap=SESSION_TEXT_CAP,
        )
        # Reflect any truncation back into doc_meta for the response
        if truncated:
            doc_meta["char_count"] = next(
                (d["char_count"] for d in docs_list if d.get("filename") == filename),
                doc_meta["char_count"],
            )
        session_total = sum(d.get("char_count", 0) for d in docs_list)

        # Build DocumentSession directly from existing session + new document.
        # Avoids re-reading from Redis in the background task (race condition fix).
        appended_text = text[:doc_meta["char_count"]] if truncated else text
        # existing is guaranteed non-None when is_append is True
        prior_texts = existing.texts if existing and existing.texts else []
        prior_text = existing.text if existing else ""
        session_for_bg = DocumentSession(
            text=(prior_text + "\n\n" + appended_text).strip() if prior_text else appended_text,
            texts=prior_texts + [appended_text],
            filenames=(existing.filenames if existing else []) + [filename],
            metadata=(existing.metadata if existing else []) + [dict(doc_meta)],
        )
    else:
        # New session — generate a fresh key
        session_key = str(uuid.uuid4())
        await set_documents(session_key, [{
            "filename": filename,
            "text": text,
            "type": doc_type,
            "char_count": len(text),
            **{k: v for k, v in doc_meta.items()
               if k not in ("filename", "type", "char_count")},
        }])
        docs_list = [doc_meta]
        session_total = len(text)

        # Build DocumentSession directly — avoids re-reading from Redis in bg task
        session_for_bg = DocumentSession(
            text=text,
            texts=[text],
            filenames=[filename],
            metadata=[dict(doc_meta)],
        )

    # Trigger background schema analysis — pass session directly to avoid
    # re-reading from Redis before the write has propagated (race condition fix)
    async def _bg_analyze_schema(sk: str, session: DocumentSession) -> None:
        try:
            await analyze_schema(sk, session)
        except Exception:
            logger.exception("Background schema analysis failed for session %s", sk)

    background_tasks.add_task(_bg_analyze_schema, session_key, session_for_bg)

    # Build unified response
    response: dict = {
        "session_key": session_key,
        "filename": filename,
        "char_count": doc_meta["char_count"],
        "session_char_count": session_total,
        "type": doc_type,
        "truncated": truncated,
        "documents": docs_list,
    }
    # Add format-specific top-level fields
    for key in ("pages", "sheets", "rows"):
        if key in format_meta:
            response[key] = format_meta[key]

    return response


@router.post("/upload-to-kg")
async def upload_to_kg(
    file: UploadFile = File(...),
    team_id: str | None = Query(None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Upload a document and extract entities/relationships into the knowledge graph.

    Supported formats: PDF, DOCX, Excel (.xlsx/.xls), CSV, TSV, PNG, JPEG, GIF, WebP.
    """
    filename = file.filename or ""
    ext = get_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({size_mb:.1f}MB) exceeds the {settings.max_upload_size_mb}MB limit.",
        )

    try:
        validate_mime(contents, filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    # Extract text from the document
    try:
        extracted_text = await extract_text(contents, filename)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to extract text from '{filename}': {exc}",
        ) from exc

    if not extracted_text or not extracted_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the file. It may be empty or corrupted.",
        )

    # Publish to the entity_extraction stream for KG processing
    session_id = str(uuid.uuid4())
    await publish_for_extraction(
        session_id,
        extracted_text,
        team_id=team_id,
        is_document=True,
    )

    return {
        "session_id": session_id,
        "filename": filename,
        "char_count": len(extracted_text),
        "status": "processing",
        "message": "Document text extracted and queued for KG processing.",
    }


async def get_document_text(session_key: str | None) -> DocumentSession:
    """Retrieve extracted document text by session key."""
    if not session_key:
        return DocumentSession(text="", filenames=[], metadata=[])
    session = await get_documents(session_key)
    if not session:
        return DocumentSession(text="", filenames=[], metadata=[])
    return session


# ── Rate limiting helpers ────────────────────────────────────────────────────

_QUERY_RATE_LIMIT = 10       # requests per window
_QUERY_RATE_WINDOW = 60      # seconds


async def _check_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 if the user has exceeded the query rate limit.

    Uses Redis key ``query_ratelimit:{user_id}:{minute_window}`` with a 60s TTL.
    """
    from app.redis_client import get_redis  # local import to avoid startup cycle

    minute_window = math.floor(datetime.datetime.now(datetime.timezone.utc).timestamp() / _QUERY_RATE_WINDOW)
    rate_key = f"query_ratelimit:{user_id}:{minute_window}"

    try:
        redis = await get_redis()
        count = await redis.incr(rate_key)
        if count == 1:
            # First request in this window — set TTL
            await redis.expire(rate_key, _QUERY_RATE_WINDOW)
        if count > _QUERY_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded: 10 queries per minute.",
                headers={"Retry-After": str(_QUERY_RATE_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis unavailable — allow request through (degrade gracefully)
        logger.warning("_check_rate_limit: Redis error — skipping rate check: %s", exc)


# ── Query endpoint ───────────────────────────────────────────────────────────


@router.post("/query", response_model=DocumentQueryResponse)
async def query_document_endpoint(
    body: DocumentQueryRequest,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict[str, Any] = Depends(get_current_user),
) -> DocumentQueryResponse:
    """Query a document session using natural language.

    Returns extracted matches with source provenance.  Rate-limited to
    10 requests per minute per authenticated user.
    """
    user_id = user["sub"]

    # Rate limiting
    await _check_rate_limit(user_id)

    # Validate session exists
    session = await get_documents(body.session_key)
    if session is None:
        raise HTTPException(status_code=404, detail="Document session not found")

    # Execute query
    result = await query_document(body.session_key, body.query)

    # Apply limit to matches while preserving full total_matches count
    all_matches = result.matches
    limited_matches = all_matches[:limit]

    return DocumentQueryResponse(
        matches=[m.model_dump() for m in limited_matches],
        query_interpretation=result.query_interpretation,
        total_matches=result.total_matches,
        error=result.error,
    )

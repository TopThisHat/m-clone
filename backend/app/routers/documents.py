import datetime
import logging
import math
import uuid
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import settings
from app.document_intelligence import analyze_schema, invalidate_query_cache, query_document
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


# ── Enums ────────────────────────────────────────────────────────────────────


class UploadMode(str, Enum):
    """Controls how an uploaded document is processed.

    - session: store text in Redis for interactive querying (default)
    - kg:      extract entities into the knowledge graph via the worker pipeline
    """
    session = "session"
    kg = "kg"


# ── Request / Response models ────────────────────────────────────────────────


class DocumentQueryRequest(BaseModel):
    session_key: str
    query: str = Field(max_length=1000)


class DocumentQueryResponse(BaseModel):
    matches: list = []
    query_interpretation: str = ""
    total_matches: int = 0
    error: str | None = None


class KGUploadResult(BaseModel):
    session_id: str
    filename: str
    char_count: int
    status: str
    message: str


@router.get("/schema")
async def get_document_schema_endpoint(
    session_key: str = Query(...),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return cached schema analysis for a document session.

    Returns ``{"ready": false}`` while background schema analysis is still
    running, or a full schema object once it completes.  Safe to poll.
    """
    from app.document_intelligence import get_cached_schema, generate_query_suggestions

    schema = await get_cached_schema(session_key)
    if schema is None:
        return {"ready": False}

    session = await get_documents(session_key)
    filename = session.filenames[0] if session and session.filenames else ""

    columns = [
        {
            "name": c.name,
            "inferred_type": c.inferred_type or "text",
            "semantic_type": c.semantic_type.value,
        }
        for s in schema.sheets
        for c in s.columns
    ]

    return {
        "ready": True,
        "document_type": schema.document_type,
        "total_sheets": schema.total_sheets,
        "summary": schema.summary,
        "columns": columns[:30],
        "suggestions": generate_query_suggestions(schema, filename),
    }


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
    mode: UploadMode = Query(UploadMode.session),
    team_id: str | None = Query(None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Upload a document for processing.

    **mode=session** (default): stores extracted text in Redis for interactive
    natural-language querying via POST /api/documents/query.

    **mode=kg**: extracts entities and relationships into the knowledge graph
    via the worker pipeline.  Returns a processing receipt; results arrive
    asynchronously.

    The ``team_id`` parameter is only used in ``mode=kg``.
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

    # ── mode=kg: publish for KG entity extraction and return receipt ──────────
    if mode == UploadMode.kg:
        session_id = str(uuid.uuid4())
        await publish_for_extraction(
            session_id,
            extracted_text,
            team_id=team_id,
            is_document=True,
        )
        return KGUploadResult(
            session_id=session_id,
            filename=filename,
            char_count=len(extracted_text),
            status="processing",
            message="Document text extracted and queued for KG processing.",
        )

    # ── mode=session: store in Redis for interactive querying ─────────────────
    try:
        format_meta = get_format_metadata(contents, filename, ext)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to extract text from '{filename}': {exc}",
        ) from exc

    doc_type = format_meta.get("type", "unknown")
    truncated = False

    doc_meta: dict = {
        "filename": filename,
        "type": doc_type,
        "char_count": len(extracted_text),
    }
    for key in ("pages", "sheets", "rows"):
        if key in format_meta:
            doc_meta[key] = format_meta[key]

    is_append = False
    existing: DocumentSession | None = None
    if session_key:
        existing = await get_documents(session_key)
        if existing and existing.filenames:
            is_append = True

    session_for_bg: DocumentSession

    if is_append:
        # Invalidate cached query results before appending — the dataset is changing
        await invalidate_query_cache(session_key)
        docs_list, truncated = await append_document(
            session_key,
            filename,
            extracted_text,
            doc_type=doc_type,
            char_count=len(extracted_text),
            metadata_fields={k: v for k, v in doc_meta.items()
                             if k not in ("filename", "type", "char_count")},
        )
        session_total = sum(d.get("char_count", 0) for d in docs_list)

        appended_text = extracted_text
        prior_texts = existing.texts if existing and existing.texts else []
        prior_text = existing.text if existing else ""
        session_for_bg = DocumentSession(
            text=(prior_text + "\n\n" + appended_text).strip() if prior_text else appended_text,
            texts=prior_texts + [appended_text],
            filenames=(existing.filenames if existing else []) + [filename],
            metadata=(existing.metadata if existing else []) + [dict(doc_meta)],
        )
    else:
        session_key = str(uuid.uuid4())
        await set_documents(session_key, [{
            "filename": filename,
            "text": extracted_text,
            "type": doc_type,
            "char_count": len(extracted_text),
            **{k: v for k, v in doc_meta.items()
               if k not in ("filename", "type", "char_count")},
        }])
        docs_list = [doc_meta]
        session_total = len(extracted_text)

        session_for_bg = DocumentSession(
            text=extracted_text,
            texts=[extracted_text],
            filenames=[filename],
            metadata=[dict(doc_meta)],
        )

    async def _bg_analyze_schema(sk: str, session: DocumentSession) -> None:
        try:
            await analyze_schema(sk, session)
        except Exception:
            logger.exception("Background schema analysis failed for session %s", sk)

    background_tasks.add_task(_bg_analyze_schema, session_key, session_for_bg)

    response: dict = {
        "session_key": session_key,
        "filename": filename,
        "char_count": doc_meta["char_count"],
        "session_char_count": session_total,
        "type": doc_type,
        "truncated": truncated,
        "documents": docs_list,
    }
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

    **Deprecated** — use ``POST /api/documents/upload?mode=kg`` instead.
    This endpoint is kept for backward compatibility and delegates to the
    unified upload handler.

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

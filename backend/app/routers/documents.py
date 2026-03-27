import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth import get_current_user
from app.config import settings
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

SESSION_TEXT_CAP = 500_000


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
    if session_key:
        existing = await get_documents(session_key)
        if existing and existing.filenames:
            is_append = True

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

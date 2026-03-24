import io
import uuid

import pdfplumber
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.auth import get_current_user
from app.config import settings
from app.document_parser import SUPPORTED_EXTENSIONS, get_extension, extract_text
from app.redis_client import get_pdf, set_pdf
from app.streams import publish_for_extraction

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Upload a PDF document for use in research sessions."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_pdf_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({size_mb:.1f}MB) exceeds the {settings.max_pdf_size_mb}MB limit.",
        )

    extracted_pages: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and text.strip():
                    extracted_pages.append(f"[Page {i + 1}]\n{text.strip()}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}") from exc

    if not extracted_pages:
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the PDF. It may be image-only or corrupted.",
        )

    full_text = "\n\n".join(extracted_pages)
    session_key = str(uuid.uuid4())
    await set_pdf(session_key, full_text, file.filename)

    return {
        "session_key": session_key,
        "filename": file.filename,
        "pages": len(extracted_pages),
        "char_count": len(full_text),
    }


@router.post("/upload-to-kg")
async def upload_to_kg(
    file: UploadFile = File(...),
    team_id: str | None = Query(None),
    user=Depends(get_current_user),
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
    max_mb = getattr(settings, "max_pdf_size_mb", 25)
    if size_mb > max_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({size_mb:.1f}MB) exceeds the {max_mb}MB limit.",
        )

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


async def get_pdf_text(session_key: str | None) -> tuple[str, list[str]]:
    """Retrieve extracted PDF text and filename by session key."""
    if not session_key:
        return "", []
    entry = await get_pdf(session_key)
    if not entry:
        return "", []
    text, filename = entry
    return text, [filename]

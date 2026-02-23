import io
import uuid

import pdfplumber
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.redis_client import get_pdf, set_pdf

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
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


async def get_pdf_text(session_key: str | None) -> tuple[str, list[str]]:
    """Retrieve extracted PDF text and filename by session key."""
    if not session_key:
        return "", []
    entry = await get_pdf(session_key)
    if not entry:
        return "", []
    text, filename = entry
    return text, [filename]

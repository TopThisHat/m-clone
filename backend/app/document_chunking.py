"""Document chunking utilities for page-aware text splitting.

Provides helpers to detect and split text by page markers ([Page N]) and
Excel sheet headers (## Sheet:), used upstream by the chunking pipeline.
"""
from __future__ import annotations

import os
import re
from typing import TypedDict

from chonkie import RecursiveChunker, TableChunker

_PAGE_MARKER_RE = re.compile(r"^\[Page\s+(\d+)\]", re.MULTILINE)
_SHEET_HEADER_RE = re.compile(r"^##\s+Sheet:\s*(.+)", re.MULTILINE)

_EXTENSION_TYPE_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
}


class ChunkDict(TypedDict):
    filename: str
    page: int | str
    chunk_index: int
    text: str


def has_page_markers(text: str) -> bool:
    """Return True if *text* contains at least one ``[Page N]`` marker."""
    return bool(_PAGE_MARKER_RE.search(text))


def split_by_pages(text: str) -> list[tuple[int, str]]:
    """Split *text* on ``[Page N]`` markers.

    Returns a list of ``(page_number, page_text)`` tuples.  Any text
    preceding the first marker is assigned to page 0.
    """
    matches = list(_PAGE_MARKER_RE.finditer(text))
    if not matches:
        return [(1, text)]

    pages: list[tuple[int, str]] = []

    # Text before the first marker → page 0
    leading = text[: matches[0].start()].strip()
    if leading:
        pages.append((0, leading))

    for i, m in enumerate(matches):
        page_num = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        page_text = text[start:end].strip()
        if page_text:
            pages.append((page_num, page_text))

    return pages


def split_excel_sheets(text: str) -> list[tuple[str, str]]:
    """Split *text* on ``## Sheet: <name>`` headers.

    Returns a list of ``(sheet_name, sheet_text)`` tuples.  Any text
    before the first header is returned with sheet name ``"_preamble"``.
    """
    matches = list(_SHEET_HEADER_RE.finditer(text))
    if not matches:
        return [("Sheet1", text)]

    sheets: list[tuple[str, str]] = []

    # Text before the first header
    leading = text[: matches[0].start()].strip()
    if leading:
        sheets.append(("_preamble", leading))

    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sheets.append((name, body))

    return sheets


def _infer_doc_type(filename: str) -> str:
    """Infer document type from filename extension."""
    _, ext = os.path.splitext(filename.lower())
    return _EXTENSION_TYPE_MAP.get(ext, "unknown")


def _chunk_text(text: str, chunker: RecursiveChunker | TableChunker) -> list[str]:
    """Run a chunker and return the text of each chunk."""
    chunks = chunker.chunk(text)
    return [c.text for c in chunks]


def chunk_file(
    text: str,
    filename: str,
    doc_type: str | None = None,
) -> list[ChunkDict]:
    """Chunk a single file's text based on its document type.

    Routing:
    - PDF: split by page markers, then RecursiveChunker per page.
    - CSV/TSV: TableChunker(tokenizer='row', chunk_size=8) on full text.
    - XLSX: split by sheet headers, then TableChunker per sheet.
    - Others: RecursiveChunker on full text.

    Returns a list of dicts with keys: filename, page, chunk_index, text.
    """
    resolved_type = doc_type or _infer_doc_type(filename)
    result: list[ChunkDict] = []

    if resolved_type == "pdf":
        rc = RecursiveChunker(tokenizer="character", chunk_size=512)
        pages = split_by_pages(text) if has_page_markers(text) else [(1, text)]
        for page_num, page_text in pages:
            chunks = _chunk_text(page_text, rc)
            for idx, chunk_text in enumerate(chunks):
                result.append({
                    "filename": filename,
                    "page": page_num,
                    "chunk_index": idx,
                    "text": chunk_text,
                })

    elif resolved_type == "csv":
        tc = TableChunker(tokenizer="row", chunk_size=8)
        chunks = _chunk_text(text, tc)
        for idx, chunk_text in enumerate(chunks):
            result.append({
                "filename": filename,
                "page": 1,
                "chunk_index": idx,
                "text": chunk_text,
            })

    elif resolved_type == "xlsx":
        tc = TableChunker(tokenizer="row", chunk_size=8)
        sheets = split_excel_sheets(text)
        for sheet_name, sheet_text in sheets:
            chunks = _chunk_text(sheet_text, tc)
            for idx, chunk_text in enumerate(chunks):
                result.append({
                    "filename": filename,
                    "page": sheet_name,
                    "chunk_index": idx,
                    "text": chunk_text,
                })

    else:
        rc = RecursiveChunker(tokenizer="character", chunk_size=512)
        chunks = _chunk_text(text, rc)
        for idx, chunk_text in enumerate(chunks):
            result.append({
                "filename": filename,
                "page": 1,
                "chunk_index": idx,
                "text": chunk_text,
            })

    return result


def chunk_session(
    doc_texts: list[str],
    metadata: list[dict],
) -> list[ChunkDict]:
    """Chunk all files in a session.

    Iterates each file's text via :func:`chunk_file`, using ``doc_type``
    from the corresponding metadata entry.

    Args:
        doc_texts: Per-file extracted text (parallel to *metadata*).
        metadata: Per-file metadata dicts; ``type`` key used for routing,
            ``filename`` for labelling.

    Returns:
        Flat list of chunk dicts across all files.
    """
    all_chunks: list[ChunkDict] = []
    for text, meta in zip(doc_texts, metadata):
        filename = meta.get("filename", "unknown")
        doc_type = meta.get("type")
        all_chunks.extend(chunk_file(text, filename, doc_type))
    return all_chunks


def batch_page_texts(
    pages: list[tuple[int, str]],
    target_chars: int = 10_000,
) -> list[str]:
    """Group page texts into batches of approximately *target_chars* characters.

    Used to prepare page-level text for KG extraction LLM calls that have
    a practical input-size sweet spot.

    Args:
        pages: List of ``(page_number, page_text)`` tuples (from :func:`split_by_pages`).
        target_chars: Target batch size in characters.

    Returns:
        List of concatenated text strings, each roughly *target_chars* long.
    """
    batches: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for _page_num, page_text in pages:
        page_len = len(page_text)
        if current_parts and current_len + page_len > target_chars:
            batches.append("\n\n".join(current_parts))
            current_parts = []
            current_len = 0
        current_parts.append(page_text)
        current_len += page_len

    if current_parts:
        batches.append("\n\n".join(current_parts))

    return batches

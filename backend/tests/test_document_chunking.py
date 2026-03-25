"""Tests for document_chunking module."""
from __future__ import annotations

from app.document_chunking import (
    batch_page_texts,
    chunk_file,
    chunk_session,
    has_page_markers,
    split_by_pages,
    split_excel_sheets,
)


# ---------------------------------------------------------------------------
# split_by_pages
# ---------------------------------------------------------------------------


def test_split_by_pages_basic():
    text = "[Page 1]\nHello world.\n[Page 2]\nGoodbye."
    pages = split_by_pages(text)
    assert len(pages) == 2
    assert pages[0] == (1, "Hello world.")
    assert pages[1] == (2, "Goodbye.")


def test_split_by_pages_intra_page_newlines():
    """Newlines within a page should NOT cause a split."""
    text = "[Page 1]\nLine one.\nLine two.\nLine three.\n[Page 2]\nPage two."
    pages = split_by_pages(text)
    assert len(pages) == 2
    assert "Line one.\nLine two.\nLine three." == pages[0][1]


def test_split_by_pages_no_markers():
    text = "Just some plain text."
    pages = split_by_pages(text)
    assert pages == [(1, "Just some plain text.")]


def test_split_by_pages_leading_text():
    text = "Preamble stuff.\n[Page 1]\nActual page."
    pages = split_by_pages(text)
    assert pages[0] == (0, "Preamble stuff.")
    assert pages[1] == (1, "Actual page.")


# ---------------------------------------------------------------------------
# chunk_file — PDF path
# ---------------------------------------------------------------------------


def test_chunk_file_pdf_with_pages():
    text = "[Page 1]\nShort page one.\n[Page 2]\nShort page two."
    chunks = chunk_file(text, "report.pdf", "pdf")
    assert all(c["filename"] == "report.pdf" for c in chunks)
    pages = {c["page"] for c in chunks}
    assert 1 in pages
    assert 2 in pages


def test_chunk_file_pdf_large_page_splits():
    """A page exceeding chunk_size should be split into multiple chunks."""
    big_text = "[Page 1]\n" + ("A" * 2500) + " " + ("B" * 2500)
    chunks = chunk_file(big_text, "big.pdf", "pdf")
    assert len(chunks) >= 2
    assert all(c["page"] == 1 for c in chunks)


# ---------------------------------------------------------------------------
# chunk_file — CSV path
# ---------------------------------------------------------------------------


def test_chunk_file_csv_preserves_structure():
    rows = ["Name,Age"] + [f"Person{i},{20+i}" for i in range(20)]
    text = "\n".join(rows)
    chunks = chunk_file(text, "data.csv", "csv")
    assert len(chunks) >= 1
    assert all(c["filename"] == "data.csv" for c in chunks)
    assert all(c["page"] == 1 for c in chunks)


# ---------------------------------------------------------------------------
# chunk_file — Excel (xlsx) path
# ---------------------------------------------------------------------------


def test_chunk_file_xlsx_multi_sheet():
    sales_rows = "\n".join([f"| Item{i} | {i*10} |" for i in range(1, 6)])
    costs_rows = "\n".join([f"| Cost{i} | {i*5} |" for i in range(1, 6)])
    text = (
        f"## Sheet: Sales\n| Name | Value |\n| --- | --- |\n{sales_rows}\n"
        f"## Sheet: Costs\n| Name | Amount |\n| --- | --- |\n{costs_rows}"
    )
    chunks = chunk_file(text, "book.xlsx", "xlsx")
    sheet_names = {c["page"] for c in chunks}
    assert "Sales" in sheet_names
    assert "Costs" in sheet_names


# ---------------------------------------------------------------------------
# chunk_file — DOCX / other path
# ---------------------------------------------------------------------------


def test_chunk_file_docx_uses_recursive():
    text = "This is a simple document with some content."
    chunks = chunk_file(text, "notes.docx", "docx")
    assert len(chunks) >= 1
    assert chunks[0]["page"] == 1
    assert chunks[0]["filename"] == "notes.docx"


# ---------------------------------------------------------------------------
# chunk_session — multi-file
# ---------------------------------------------------------------------------


def test_chunk_session_multi_file():
    doc_texts = [
        "[Page 1]\nPDF content here.",
        "Name,Value\nAlice,100\nBob,200",
    ]
    metadata = [
        {"filename": "report.pdf", "type": "pdf", "char_count": 25},
        {"filename": "data.csv", "type": "csv", "char_count": 30},
    ]
    chunks = chunk_session(doc_texts, metadata)
    filenames = {c["filename"] for c in chunks}
    assert "report.pdf" in filenames
    assert "data.csv" in filenames
    # No cross-file contamination
    pdf_chunks = [c for c in chunks if c["filename"] == "report.pdf"]
    csv_chunks = [c for c in chunks if c["filename"] == "data.csv"]
    for c in pdf_chunks:
        assert "Alice" not in c["text"]
    for c in csv_chunks:
        assert "PDF content" not in c["text"]


# ---------------------------------------------------------------------------
# batch_page_texts
# ---------------------------------------------------------------------------


def test_batch_page_texts_basic():
    # 30 pages of ~400 chars each → should create ~2-3 batches at target 10000
    pages = [(i, f"Page {i} content. " * 25) for i in range(1, 31)]
    batches = batch_page_texts(pages, target_chars=10_000)
    assert len(batches) >= 2
    # All page content should be present
    combined = "\n\n".join(batches)
    for i in range(1, 31):
        assert f"Page {i} content." in combined


def test_batch_page_texts_single_large_page():
    """A single page exceeding target_chars should still appear as one batch."""
    pages = [(1, "X" * 15_000)]
    batches = batch_page_texts(pages, target_chars=10_000)
    assert len(batches) == 1
    assert len(batches[0]) == 15_000


def test_batch_page_texts_empty():
    batches = batch_page_texts([])
    assert batches == []


def test_batch_page_texts_small_pages():
    """Many tiny pages should be grouped into one batch."""
    pages = [(i, "tiny") for i in range(1, 6)]
    batches = batch_page_texts(pages, target_chars=10_000)
    assert len(batches) == 1


# ---------------------------------------------------------------------------
# No cross-page BM25 contamination
# ---------------------------------------------------------------------------


def test_no_cross_page_contamination():
    """Chunks from different pages should not contain each other's text."""
    text = "[Page 1]\nAlpha bravo charlie.\n[Page 2]\nDelta echo foxtrot."
    chunks = chunk_file(text, "test.pdf", "pdf")
    page1_chunks = [c for c in chunks if c["page"] == 1]
    page2_chunks = [c for c in chunks if c["page"] == 2]
    for c in page1_chunks:
        assert "Delta" not in c["text"]
        assert "foxtrot" not in c["text"]
    for c in page2_chunks:
        assert "Alpha" not in c["text"]
        assert "charlie" not in c["text"]

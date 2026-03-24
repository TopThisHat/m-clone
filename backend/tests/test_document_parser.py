"""Tests for document_parser module — metadata, timeout, and type safety."""
from __future__ import annotations

import csv
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document_parser import extract_image, extract_text, get_format_metadata


# ---------------------------------------------------------------------------
# get_format_metadata — PDF
# ---------------------------------------------------------------------------


def test_pdf_metadata_returns_page_count():
    mock_pages = [MagicMock(), MagicMock(), MagicMock()]
    mock_pdf = MagicMock()
    mock_pdf.pages = mock_pages
    mock_pdf.close = MagicMock()

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = get_format_metadata(b"fake-pdf", "doc.pdf", ".pdf")

    assert result == {"type": "pdf", "pages": 3}


def test_pdf_metadata_closes_on_success():
    mock_pdf = MagicMock()
    mock_pdf.pages = [MagicMock()]
    mock_pdf.close = MagicMock()

    with patch("pdfplumber.open", return_value=mock_pdf):
        get_format_metadata(b"fake-pdf", "doc.pdf", ".pdf")

    mock_pdf.close.assert_called_once()


def test_pdf_metadata_closes_on_error():
    mock_pdf = MagicMock()
    mock_pdf.pages = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    type(mock_pdf).pages = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    mock_pdf.close = MagicMock()

    with patch("pdfplumber.open", return_value=mock_pdf):
        with pytest.raises(RuntimeError):
            get_format_metadata(b"fake-pdf", "doc.pdf", ".pdf")

    mock_pdf.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_format_metadata — Excel
# ---------------------------------------------------------------------------


def test_excel_metadata_returns_sheet_count():
    mock_wb = MagicMock()
    mock_wb.sheetnames = ["Sheet1", "Sheet2"]
    mock_wb.close = MagicMock()

    with patch("openpyxl.load_workbook", return_value=mock_wb):
        result = get_format_metadata(b"fake-xlsx", "data.xlsx", ".xlsx")

    assert result == {"type": "xlsx", "sheets": 2}


def test_excel_metadata_closes_workbook():
    mock_wb = MagicMock()
    mock_wb.sheetnames = ["Sheet1"]
    mock_wb.close = MagicMock()

    with patch("openpyxl.load_workbook", return_value=mock_wb):
        get_format_metadata(b"fake-xlsx", "data.xlsx", ".xlsx")

    mock_wb.close.assert_called_once()


def test_excel_metadata_closes_on_error():
    mock_wb = MagicMock()
    type(mock_wb).sheetnames = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    mock_wb.close = MagicMock()

    with patch("openpyxl.load_workbook", return_value=mock_wb):
        with pytest.raises(RuntimeError):
            get_format_metadata(b"fake-xlsx", "data.xlsx", ".xlsx")

    mock_wb.close.assert_called_once()


def test_xls_extension_uses_xlsx_type():
    mock_wb = MagicMock()
    mock_wb.sheetnames = ["A"]
    mock_wb.close = MagicMock()

    with patch("openpyxl.load_workbook", return_value=mock_wb):
        result = get_format_metadata(b"fake-xls", "old.xls", ".xls")

    assert result["type"] == "xlsx"


# ---------------------------------------------------------------------------
# get_format_metadata — CSV (real bytes, no mocking)
# ---------------------------------------------------------------------------


def _make_csv_bytes(*rows: list[str], delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def test_csv_metadata_counts_non_empty_rows():
    data = _make_csv_bytes(
        ["name", "age"],
        ["Alice", "30"],
        ["", ""],       # blank row — should be excluded
        ["Bob", "25"],
    )
    result = get_format_metadata(data, "people.csv", ".csv")
    assert result == {"type": "csv", "rows": 3}


def test_csv_metadata_all_blank_rows():
    data = _make_csv_bytes(["", ""], ["", ""])
    result = get_format_metadata(data, "empty.csv", ".csv")
    assert result == {"type": "csv", "rows": 0}


def test_tsv_metadata():
    data = _make_csv_bytes(["a", "b"], ["c", "d"], delimiter="\t")
    result = get_format_metadata(data, "data.tsv", ".tsv")
    assert result == {"type": "csv", "rows": 2}


# ---------------------------------------------------------------------------
# get_format_metadata — DOCX / image / unknown
# ---------------------------------------------------------------------------


def test_docx_metadata():
    result = get_format_metadata(b"fake", "doc.docx", ".docx")
    assert result == {"type": "docx"}


def test_image_metadata_png():
    result = get_format_metadata(b"fake", "photo.png", ".png")
    assert result == {"type": "image"}


def test_image_metadata_jpeg():
    result = get_format_metadata(b"fake", "photo.jpeg", ".jpeg")
    assert result == {"type": "image"}


def test_unknown_extension():
    result = get_format_metadata(b"fake", "file.xyz", ".xyz")
    assert result == {"type": "unknown"}


# ---------------------------------------------------------------------------
# extract_image — timeout=60
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_image_passes_timeout():
    mock_choice = MagicMock()
    mock_choice.message.content = "extracted text"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]

    mock_create = AsyncMock(return_value=mock_resp)
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create

    with patch("app.openai_factory.get_openai_client", return_value=mock_client):
        result = await extract_image(b"fake-image", "img.png", "image/png")

    assert result == "extracted text"
    _, kwargs = mock_create.call_args
    assert kwargs["timeout"] == 60


# ---------------------------------------------------------------------------
# extract_text — return type is str
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_text_returns_str():
    with patch("app.document_parser.extract_pdf", return_value="hello pdf"):
        result = await extract_text(b"fake-pdf", "doc.pdf")

    assert isinstance(result, str)
    assert result == "hello pdf"

"""Tests for validate_mime() in document_parser and the upload endpoint 415 gate."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.document_parser import validate_mime


# ---------------------------------------------------------------------------
# Helpers — minimal valid magic-byte prefixes
# ---------------------------------------------------------------------------

_PDF = b"%PDF-1.4 fake content"
_ZIP = b"PK\x03\x04fake zip content"  # DOCX / XLSX
_PNG = b"\x89PNG\r\n\x1a\nfake png"
_JPEG = b"\xff\xd8\xff\xe0fake jpeg"
_GIF87 = b"GIF87afake gif"
_GIF89 = b"GIF89afake gif"
# WebP: bytes 0-3 = RIFF, bytes 8-11 = WEBP
_WEBP = b"RIFFxxxxWEBPfake webp"


# ---------------------------------------------------------------------------
# Valid signatures — validate_mime should return None (no exception)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contents, filename",
    [
        (_PDF, "report.pdf"),
        (_ZIP, "document.docx"),
        (_ZIP, "spreadsheet.xlsx"),
        (_PNG, "photo.png"),
        (_JPEG, "photo.jpg"),
        (_JPEG, "photo.jpeg"),
        (_GIF87, "anim87.gif"),
        (_GIF89, "anim89.gif"),
        (_WEBP, "image.webp"),
    ],
)
def test_valid_magic_bytes_pass(contents: bytes, filename: str) -> None:
    """Files whose magic bytes match their extension must pass silently."""
    validate_mime(contents, filename)  # should not raise


# ---------------------------------------------------------------------------
# CSV / TSV — no magic bytes, always skip validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contents, filename",
    [
        (b"name,age\nAlice,30", "data.csv"),
        (b"name\tage\nBob\t25", "data.tsv"),
        # Even junk bytes are accepted for CSV/TSV
        (b"\x00\x01\x02", "junk.csv"),
    ],
)
def test_csv_tsv_skips_validation(contents: bytes, filename: str) -> None:
    """CSV and TSV files have no magic bytes and must always pass."""
    validate_mime(contents, filename)


# ---------------------------------------------------------------------------
# .xls — OLE Compound Document format, excluded from MIME validation
# ---------------------------------------------------------------------------

# Real OLE magic bytes (\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1) differ from ZIP.
# openpyxl only handles ZIP-based XLSX, so .xls is skipped (like CSV/TSV).
_OLE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 8


def test_xls_ole_magic_skips_validation() -> None:
    """.xls with real OLE magic bytes must pass without a 415 error."""
    validate_mime(_OLE, "legacy.xls")


def test_xls_zip_magic_also_skips_validation() -> None:
    """.xls with ZIP magic bytes also passes — validation is skipped entirely."""
    validate_mime(_ZIP, "legacy.xls")


# ---------------------------------------------------------------------------
# Unknown / unlisted extensions — silently skipped
# ---------------------------------------------------------------------------


def test_unknown_extension_skips_validation() -> None:
    """Files with unknown extensions are not validated."""
    validate_mime(b"\x00\x01\x02\x03garbage", "file.xyz")


# ---------------------------------------------------------------------------
# Mismatched signatures — must raise ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contents, filename, bad_ext",
    [
        # PDF header in a file claiming to be PNG
        (_PDF, "sneaky.png", ".png"),
        # PNG header in a file claiming to be PDF
        (_PNG, "sneaky.pdf", ".pdf"),
        # JPEG header in a file claiming to be WebP
        (_JPEG, "sneaky.webp", ".webp"),
        # ZIP header in a file claiming to be PNG
        (_ZIP, "sneaky.png", ".png"),
        # Random bytes in a PDF
        (b"random bytes here", "corrupt.pdf", ".pdf"),
        # Random bytes in a JPEG
        (b"\x00\x00\x00\x00", "corrupt.jpg", ".jpg"),
        # GIF87 in a WEBP file
        (_GIF87, "sneaky.webp", ".webp"),
        # WebP RIFF but missing WEBP marker at offset 8
        (b"RIFFxxxxJPEGfake", "bad.webp", ".webp"),
    ],
)
def test_mismatched_magic_raises_value_error(
    contents: bytes, filename: str, bad_ext: str
) -> None:
    """Files whose magic bytes don't match their declared extension must raise."""
    with pytest.raises(ValueError, match=filename):
        validate_mime(contents, filename)


# ---------------------------------------------------------------------------
# Edge cases — short / empty files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contents, filename",
    [
        (b"", "empty.pdf"),
        (b"%", "truncated.pdf"),    # only 1 of 4 required PDF bytes
        (b"\xff\xd8", "short.jpg"),  # only 2 of 3 required JPEG bytes
    ],
)
def test_short_file_raises_value_error(contents: bytes, filename: str) -> None:
    """Files too short to contain a valid signature must raise ValueError."""
    with pytest.raises(ValueError):
        validate_mime(contents, filename)


# ---------------------------------------------------------------------------
# GIF — both GIF87a and GIF89a are accepted
# ---------------------------------------------------------------------------


def test_gif87a_accepted() -> None:
    validate_mime(_GIF87, "old.gif")


def test_gif89a_accepted() -> None:
    validate_mime(_GIF89, "new.gif")


def test_gif_wrong_variant_rejected() -> None:
    """GIF90a is not a real format — must be rejected."""
    with pytest.raises(ValueError):
        validate_mime(b"GIF90afake", "fake.gif")


# ---------------------------------------------------------------------------
# Upload endpoint — 415 Unsupported Media Type on MIME mismatch
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    from fastapi import FastAPI
    from app.auth import get_current_user
    from app.routers.documents import router

    _app = FastAPI()
    _app.include_router(router)
    _app.dependency_overrides[get_current_user] = lambda: {
        "sid": "test-user",
        "display_name": "Tester",
        "email": "t@t.com",
    }
    return _app


@pytest.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_upload_returns_415_on_mime_mismatch(client) -> None:
    """Uploading a JPEG masquerading as a PDF must return 415."""
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("report.pdf", _JPEG, "application/octet-stream")},
    )
    assert resp.status_code == 415
    assert "magic bytes" in resp.json()["detail"].lower() or "report.pdf" in resp.json()["detail"]


@pytest.mark.asyncio
@patch("app.routers.documents.set_documents", new_callable=AsyncMock)
@patch(
    "app.routers.documents.extract_text",
    new_callable=AsyncMock,
    return_value="extracted text",
)
@patch(
    "app.routers.documents.get_format_metadata",
    return_value={"type": "pdf", "pages": 1},
)
async def test_upload_accepts_valid_pdf(mock_meta, mock_extract, mock_set, client) -> None:
    """Uploading a real PDF (correct magic bytes) must return 200."""
    resp = await client.post(
        "/api/documents/upload",
        files={"file": ("report.pdf", _PDF, "application/octet-stream")},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_accepts_csv_without_magic_bytes(client) -> None:
    """CSV files bypass MIME validation and must not return 415."""
    with (
        patch("app.routers.documents.set_documents", new_callable=AsyncMock),
        patch(
            "app.routers.documents.extract_text",
            new_callable=AsyncMock,
            return_value="col1,col2\nval1,val2",
        ),
        patch(
            "app.routers.documents.get_format_metadata",
            return_value={"type": "csv", "rows": 1},
        ),
    ):
        resp = await client.post(
            "/api/documents/upload",
            files={"file": ("data.csv", b"col1,col2\nval1,val2", "text/csv")},
        )
    assert resp.status_code == 200

"""Tests for the multi-document Redis storage layer.

All tests run WITHOUT a Redis server by patching ``_get_client`` to return
``None``, which forces every function through the ``_memory_store`` fallback.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.redis_client import (
    DocumentSession,
    _infer_type_from_filename,
    _memory_store,
    append_document,
    get_documents,
    set_documents,
)


@pytest.fixture(autouse=True)
def _clear_memory_store():
    """Ensure a clean in-memory store for every test."""
    _memory_store.clear()
    yield
    _memory_store.clear()


_no_redis = patch("app.redis_client._get_client", new_callable=AsyncMock, return_value=None)


# ------------------------------------------------------------------
# 1. DocumentSession dataclass
# ------------------------------------------------------------------

class TestDocumentSession:
    def test_defaults(self):
        session = DocumentSession(text="hello")
        assert session.text == "hello"
        assert session.filenames == []
        assert session.metadata == []

    def test_with_values(self):
        session = DocumentSession(
            text="body",
            filenames=["a.pdf"],
            metadata=[{"filename": "a.pdf", "type": "pdf"}],
        )
        assert session.filenames == ["a.pdf"]
        assert session.metadata[0]["type"] == "pdf"


# ------------------------------------------------------------------
# 2. _infer_type_from_filename
# ------------------------------------------------------------------

class TestInferType:
    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("report.pdf", "pdf"),
            ("doc.docx", "docx"),
            ("sheet.xlsx", "xlsx"),
            ("sheet.xls", "xlsx"),
            ("data.csv", "csv"),
            ("data.tsv", "csv"),
            ("photo.png", "image"),
            ("photo.jpg", "image"),
            ("photo.jpeg", "image"),
            ("photo.gif", "image"),
            ("photo.webp", "image"),
            ("README.txt", "unknown"),
            ("NOEXT", "unknown"),
            ("Report.PDF", "pdf"),  # case-insensitive
        ],
    )
    def test_extensions(self, filename: str, expected: str):
        assert _infer_type_from_filename(filename) == expected


# ------------------------------------------------------------------
# 3. set_documents + get_documents round-trip
# ------------------------------------------------------------------

class TestSetGetDocuments:
    @_no_redis
    def test_round_trip(self, _mock):
        docs = [
            {
                "filename": "a.pdf",
                "text": "hello",
                "type": "pdf",
                "char_count": 5,
            },
            {
                "filename": "b.csv",
                "text": "world",
                "type": "csv",
                "char_count": 5,
            },
        ]
        asyncio.get_event_loop().run_until_complete(set_documents("k1", docs))
        session = asyncio.get_event_loop().run_until_complete(get_documents("k1"))

        assert session is not None
        assert session.text == "hello\n\nworld"
        assert session.filenames == ["a.pdf", "b.csv"]
        assert len(session.metadata) == 2
        assert session.metadata[0]["char_count"] == 5


# ------------------------------------------------------------------
# 4. append_document to existing session
# ------------------------------------------------------------------

class TestAppendDocument:
    @_no_redis
    def test_append_to_existing(self, _mock):
        loop = asyncio.get_event_loop()
        initial = [
            {"filename": "a.pdf", "text": "first", "type": "pdf", "char_count": 5},
        ]
        loop.run_until_complete(set_documents("k2", initial))

        result = loop.run_until_complete(
            append_document("k2", "b.docx", "second", char_count=6)
        )

        # Result should contain metadata for both docs, no text
        assert len(result) == 2
        assert all("text" not in entry for entry in result)
        assert result[1]["filename"] == "b.docx"
        assert result[1]["type"] == "docx"
        assert result[1]["char_count"] == 6

    @_no_redis
    def test_append_to_old_tuple_format(self, _mock):
        """Migrate from old (text, filename) tuple in _memory_store."""
        _memory_store["k3"] = ("old text", "old.pdf")

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            append_document("k3", "new.csv", "new text")
        )

        assert len(result) == 2
        assert result[0]["filename"] == "old.pdf"
        assert result[0]["type"] == "pdf"
        assert result[0]["char_count"] == 8  # len("old text")
        assert result[1]["filename"] == "new.csv"

    @_no_redis
    def test_append_return_no_text(self, _mock):
        """Returned metadata entries must not include 'text'."""
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            append_document("fresh", "a.pdf", "content here")
        )
        assert len(result) == 1
        assert "text" not in result[0]
        assert result[0]["filename"] == "a.pdf"

    @_no_redis
    def test_append_char_count_auto(self, _mock):
        """char_count defaults to len(text) when not explicitly provided."""
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            append_document("cc", "x.pdf", "abcde")
        )
        assert result[0]["char_count"] == 5

    @_no_redis
    def test_append_with_metadata_fields(self, _mock):
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            append_document(
                "mf", "sheet.xlsx", "data",
                metadata_fields={"sheets": 3, "rows": 100},
            )
        )
        assert result[0]["sheets"] == 3
        assert result[0]["rows"] == 100


# ------------------------------------------------------------------
# 5. get_documents with old-format data
# ------------------------------------------------------------------

class TestGetDocumentsOldFormat:
    @_no_redis
    def test_old_tuple_in_memory(self, _mock):
        _memory_store["old1"] = ("pdf text", "report.pdf")
        session = asyncio.get_event_loop().run_until_complete(get_documents("old1"))

        assert session is not None
        assert session.text == "pdf text"
        assert session.filenames == ["report.pdf"]
        assert session.metadata[0]["type"] == "pdf"
        assert session.metadata[0]["char_count"] == 8

    @_no_redis
    def test_old_dict_in_memory(self, _mock):
        _memory_store["old2"] = {"text": "hi", "filename": "f.docx"}
        session = asyncio.get_event_loop().run_until_complete(get_documents("old2"))

        assert session is not None
        assert session.text == "hi"
        assert session.filenames == ["f.docx"]

    @_no_redis
    def test_missing_key(self, _mock):
        result = asyncio.get_event_loop().run_until_complete(get_documents("nope"))
        assert result is None


# ------------------------------------------------------------------
# 6. char_count stored correctly per entry
# ------------------------------------------------------------------

class TestCharCount:
    @_no_redis
    def test_char_count_stored(self, _mock):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            set_documents("cc1", [
                {"filename": "a.pdf", "text": "abc", "type": "pdf", "char_count": 3},
                {"filename": "b.csv", "text": "abcdef", "type": "csv", "char_count": 6},
            ])
        )
        session = loop.run_until_complete(get_documents("cc1"))
        assert session is not None
        assert session.metadata[0]["char_count"] == 3
        assert session.metadata[1]["char_count"] == 6

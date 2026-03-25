"""Tests for data model changes: DocumentSession.texts and AgentDeps.doc_texts."""
from __future__ import annotations

from unittest.mock import MagicMock

from app.dependencies import AgentDeps, get_agent_deps
from app.redis_client import DocumentSession, _docs_list_to_session, _memory_get_documents, _memory_store


# ---------------------------------------------------------------------------
# DocumentSession.texts — via _docs_list_to_session
# ---------------------------------------------------------------------------


def test_docs_list_to_session_multi_file():
    docs = [
        {"filename": "a.pdf", "text": "hello", "type": "pdf", "char_count": 5},
        {"filename": "b.docx", "text": "world", "type": "docx", "char_count": 5},
    ]
    session = _docs_list_to_session(docs)
    assert session.texts == ["hello", "world"]
    assert session.text == "hello\n\nworld"
    assert session.filenames == ["a.pdf", "b.docx"]
    assert len(session.metadata) == 2
    assert all("text" not in m for m in session.metadata)


def test_docs_list_to_session_single_file():
    docs = [{"filename": "report.pdf", "text": "content", "type": "pdf", "char_count": 7}]
    session = _docs_list_to_session(docs)
    assert session.texts == ["content"]
    assert session.text == "content"


def test_docs_list_to_session_empty_text():
    docs = [{"filename": "empty.pdf", "text": "", "type": "pdf", "char_count": 0}]
    session = _docs_list_to_session(docs)
    assert session.texts == [""]


# ---------------------------------------------------------------------------
# DocumentSession.texts — legacy formats via _memory_get_documents
# ---------------------------------------------------------------------------


def test_memory_get_documents_tuple_format():
    """Old (text, filename) tuple format should populate texts as single-element list."""
    _memory_store["test_tuple"] = ("some text", "file.pdf")
    session = _memory_get_documents("test_tuple")
    assert session is not None
    assert session.texts == ["some text"]
    assert session.text == "some text"
    assert session.filenames == ["file.pdf"]
    del _memory_store["test_tuple"]


def test_memory_get_documents_dict_format():
    """Old dict format should populate texts as single-element list."""
    _memory_store["test_dict"] = {"text": "dict text", "filename": "old.pdf"}
    session = _memory_get_documents("test_dict")
    assert session is not None
    assert session.texts == ["dict text"]
    assert session.text == "dict text"
    del _memory_store["test_dict"]


def test_memory_get_documents_list_format():
    """New list format should populate texts via _docs_list_to_session."""
    _memory_store["test_list"] = [
        {"filename": "a.pdf", "text": "aaa", "type": "pdf", "char_count": 3},
        {"filename": "b.csv", "text": "bbb", "type": "csv", "char_count": 3},
    ]
    session = _memory_get_documents("test_list")
    assert session is not None
    assert session.texts == ["aaa", "bbb"]
    del _memory_store["test_list"]


def test_memory_get_documents_missing_key():
    session = _memory_get_documents("nonexistent_key_12345")
    assert session is None


# ---------------------------------------------------------------------------
# AgentDeps.doc_texts — field and factory
# ---------------------------------------------------------------------------


def test_agent_deps_has_doc_texts():
    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        doc_texts=["text1", "text2"],
    )
    assert deps.doc_texts == ["text1", "text2"]


def test_agent_deps_doc_texts_defaults_empty():
    deps = AgentDeps(tavily_api_key="k", wiki=MagicMock())
    assert deps.doc_texts == []


def test_get_agent_deps_passes_doc_texts():
    texts = ["file1 content", "file2 content"]
    deps = get_agent_deps(doc_texts=texts)
    assert deps.doc_texts == texts


def test_get_agent_deps_doc_texts_defaults_empty():
    deps = get_agent_deps()
    assert deps.doc_texts == []

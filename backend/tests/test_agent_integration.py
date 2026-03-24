"""Tests for agent integration changes (Task 5).

Covers:
- AgentDeps.doc_context rename (from pdf_context)
- AgentDeps.uploaded_doc_metadata field
- get_agent_deps() factory with new params
- search_uploaded_documents uses doc_context
- _build_system_content injects document metadata
- SYSTEM_PROMPT references multi-format documents
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.dependencies import AgentDeps, get_agent_deps


# ---------------------------------------------------------------------------
# 5.1 — AgentDeps field rename and new field
# ---------------------------------------------------------------------------


def test_agent_deps_has_doc_context():
    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        doc_context="hello",
    )
    assert deps.doc_context == "hello"


def test_agent_deps_no_pdf_context_attr():
    deps = AgentDeps(tavily_api_key="k", wiki=MagicMock())
    assert not hasattr(deps, "pdf_context") or "pdf_context" not in AgentDeps.__dataclass_fields__


def test_agent_deps_has_uploaded_doc_metadata():
    meta = [{"filename": "a.pdf", "type": "pdf", "char_count": 100, "pages": 3}]
    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        uploaded_doc_metadata=meta,
    )
    assert deps.uploaded_doc_metadata == meta


def test_agent_deps_uploaded_doc_metadata_defaults_empty():
    deps = AgentDeps(tavily_api_key="k", wiki=MagicMock())
    assert deps.uploaded_doc_metadata == []


# ---------------------------------------------------------------------------
# 5.1 — get_agent_deps factory
# ---------------------------------------------------------------------------


def test_get_agent_deps_doc_context():
    deps = get_agent_deps(doc_context="document text")
    assert deps.doc_context == "document text"


def test_get_agent_deps_pdf_context_compat():
    """Backward-compat: pdf_context kwarg still works."""
    deps = get_agent_deps(pdf_context="legacy text")
    assert deps.doc_context == "legacy text"


def test_get_agent_deps_doc_context_wins_over_pdf_context():
    deps = get_agent_deps(doc_context="new", pdf_context="old")
    assert deps.doc_context == "new"


def test_get_agent_deps_uploaded_doc_metadata():
    meta = [{"filename": "x.xlsx", "type": "xlsx", "char_count": 500, "sheets": 2}]
    deps = get_agent_deps(uploaded_doc_metadata=meta)
    assert deps.uploaded_doc_metadata == meta


def test_get_agent_deps_uploaded_doc_metadata_defaults():
    deps = get_agent_deps()
    assert deps.uploaded_doc_metadata == []


# ---------------------------------------------------------------------------
# 5.2 — search_uploaded_documents uses doc_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_uploaded_documents_uses_doc_context():
    from app.agent.tools import search_uploaded_documents

    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        doc_context="The quick brown fox jumped over the lazy dog",
        uploaded_filenames=["test.docx"],
    )
    result = await search_uploaded_documents(deps=deps, query="fox")
    assert "fox" in result.lower() or "test.docx" in result


@pytest.mark.asyncio
async def test_search_uploaded_documents_no_context():
    from app.agent.tools import search_uploaded_documents

    deps = AgentDeps(tavily_api_key="k", wiki=MagicMock(), doc_context="")
    result = await search_uploaded_documents(deps=deps, query="anything")
    assert "No documents" in result


# ---------------------------------------------------------------------------
# 5.2 — Tool description is multi-format
# ---------------------------------------------------------------------------


def test_tool_description_multi_format():
    from app.agent.tools import TOOL_REGISTRY

    tool = TOOL_REGISTRY["search_uploaded_documents"]
    desc = tool.schema["function"]["description"]
    assert "PDF" in desc
    assert "DOCX" in desc or "Excel" in desc or "CSV" in desc


# ---------------------------------------------------------------------------
# 5.3 — _build_system_content injects document metadata
# ---------------------------------------------------------------------------


def test_build_system_content_no_metadata():
    from app.agent.agent import _build_system_content

    deps = AgentDeps(tavily_api_key="k", wiki=MagicMock())
    content = _build_system_content(deps)
    assert "Uploaded Documents" not in content


def test_build_system_content_with_metadata():
    from app.agent.agent import _build_system_content

    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        uploaded_doc_metadata=[
            {"filename": "report.pdf", "type": "pdf", "char_count": 12000, "pages": 5},
            {"filename": "data.xlsx", "type": "xlsx", "char_count": 3000, "sheets": 3},
        ],
    )
    content = _build_system_content(deps)
    assert "Uploaded Documents" in content
    assert "report.pdf" in content
    assert "pdf" in content
    assert "5 pages" in content
    assert "data.xlsx" in content
    assert "3 sheets" in content


def test_build_system_content_metadata_with_rows():
    from app.agent.agent import _build_system_content

    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        uploaded_doc_metadata=[
            {"filename": "input.csv", "type": "csv", "char_count": 800, "rows": 42},
        ],
    )
    content = _build_system_content(deps)
    assert "42 rows" in content


def test_build_system_content_metadata_minimal():
    """Metadata with only required fields (no pages/sheets/rows)."""
    from app.agent.agent import _build_system_content

    deps = AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        uploaded_doc_metadata=[
            {"filename": "photo.png", "type": "image", "char_count": 200},
        ],
    )
    content = _build_system_content(deps)
    assert "photo.png" in content
    assert "image" in content


# ---------------------------------------------------------------------------
# 5.3 — SYSTEM_PROMPT references multi-format in tool list
# ---------------------------------------------------------------------------


def test_system_prompt_multi_format_tool_ref():
    from app.agent.agent import SYSTEM_PROMPT

    assert "documents" in SYSTEM_PROMPT.lower()
    # The tool reference should no longer say "PDFs" exclusively
    assert "PDF, DOCX" in SYSTEM_PROMPT or "documents the client" in SYSTEM_PROMPT

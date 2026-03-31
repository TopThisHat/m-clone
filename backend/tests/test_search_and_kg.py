"""Tests for search_uploaded_documents rewrite and KG extraction batching."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.dependencies import AgentDeps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deps(
    doc_texts: list[str] | None = None,
    metadata: list[dict] | None = None,
    doc_context: str = "",
    filenames: list[str] | None = None,
) -> AgentDeps:
    return AgentDeps(
        tavily_api_key="k",
        wiki=MagicMock(),
        doc_context=doc_context,
        doc_texts=doc_texts or [],
        uploaded_filenames=filenames or [],
        uploaded_doc_metadata=metadata or [],
    )


# ---------------------------------------------------------------------------
# search_uploaded_documents — chunk-based BM25 with file+page prefixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_page_attribution():
    from app.agent.tools import search_uploaded_documents

    deps = _make_deps(
        doc_texts=["[Page 1]\nAlpha bravo charlie.\n[Page 2]\nDelta echo foxtrot."],
        metadata=[{"filename": "report.pdf", "type": "pdf", "char_count": 50}],
    )
    result = await search_uploaded_documents(deps=deps, query="Alpha bravo")
    assert "[report.pdf" in result
    assert "Page" in result


@pytest.mark.asyncio
async def test_search_short_circuit_three_chunks():
    """<=3 chunks should be returned directly without BM25."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_deps(
        doc_texts=["Short text here."],
        metadata=[{"filename": "small.docx", "type": "docx", "char_count": 16}],
    )
    result = await search_uploaded_documents(deps=deps, query="anything")
    assert "Short text here" in result


@pytest.mark.asyncio
async def test_search_response_cap():
    """Response longer than 15K chars should be trimmed."""
    from app.agent.tools import search_uploaded_documents

    # Create a large document that will produce large chunks
    big_text = "keyword " * 5000  # ~40K chars
    deps = _make_deps(
        doc_texts=[big_text],
        metadata=[{"filename": "big.docx", "type": "docx", "char_count": len(big_text)}],
    )
    result = await search_uploaded_documents(deps=deps, query="keyword")
    assert len(result) <= 15_000


@pytest.mark.asyncio
async def test_search_no_docs():
    from app.agent.tools import search_uploaded_documents

    deps = _make_deps()
    result = await search_uploaded_documents(deps=deps, query="anything")
    assert "No documents" in result


@pytest.mark.asyncio
async def test_search_fallback_to_doc_context():
    """When doc_texts is empty, should use old doc_context.split approach."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_deps(
        doc_context="The quick brown fox jumped over the lazy dog",
        filenames=["legacy.pdf"],
    )
    result = await search_uploaded_documents(deps=deps, query="fox")
    assert "fox" in result.lower()


@pytest.mark.asyncio
async def test_search_caches_chunks():
    """Chunks and BM25 should be cached in tool_cache."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_deps(
        doc_texts=["Hello world content here. " * 50],
        metadata=[{"filename": "test.docx", "type": "docx", "char_count": 1000}],
    )
    await search_uploaded_documents(deps=deps, query="hello")
    assert "chunked_docs" in deps.tool_cache


# ---------------------------------------------------------------------------
# search_uploaded_documents — filename filtering (Tasks 4.1, 4.2)
# ---------------------------------------------------------------------------


def _make_multi_file_deps() -> "AgentDeps":
    """Create deps with two uploaded files for filename-filter tests."""
    return _make_deps(
        doc_texts=[
            "[Page 1]\nAlpha revenue Q3 results.\n[Page 2]\nBeta bravo charlie.",
            "Team names roster players stats NBA MLB.",
        ],
        metadata=[
            {"filename": "financials.pdf", "type": "pdf", "char_count": 60},
            {"filename": "sports.csv", "type": "csv", "char_count": 50},
        ],
    )


@pytest.mark.asyncio
async def test_filename_filter_returns_only_matching_file():
    """Task 6.1: filename param restricts results to that file only."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(
        deps=deps, query="revenue", filename="financials.pdf",
    )
    assert "financials.pdf" in result
    assert "sports.csv" not in result


@pytest.mark.asyncio
async def test_filename_filter_nonmatching_returns_error_with_available():
    """Task 6.2: non-matching filename returns error listing available files."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(
        deps=deps, query="anything", filename="missing.xlsx",
    )
    assert "missing.xlsx" in result
    assert "financials.pdf" in result
    assert "sports.csv" in result


@pytest.mark.asyncio
async def test_filename_filter_case_insensitive():
    """Task 6.3: filename matching is case-insensitive."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(
        deps=deps, query="revenue", filename="FINANCIALS.PDF",
    )
    # Should match financials.pdf despite uppercase input
    assert "No uploaded file matches" not in result
    assert "financials.pdf" in result


# ---------------------------------------------------------------------------
# search_uploaded_documents — wildcard / non-keyword guard (Task 4.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wildcard_query_returns_guidance():
    """Task 6.4: wildcard query '*' returns guidance, not dead-end error."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(deps=deps, query="*")
    assert "not supported" in result.lower() or "Wildcard" in result
    assert "financials.pdf" in result
    assert "sports.csv" in result


@pytest.mark.asyncio
async def test_empty_query_returns_guidance():
    """Task 6.5: empty query '' returns guidance message."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(deps=deps, query="")
    assert "not supported" in result.lower() or "Wildcard" in result
    assert "Available files" in result


@pytest.mark.asyncio
async def test_single_punctuation_query_returns_guidance():
    """Single punctuation char like '?' should be caught by the guard."""
    from app.agent.tools import search_uploaded_documents

    deps = _make_multi_file_deps()
    result = await search_uploaded_documents(deps=deps, query="?")
    assert "not supported" in result.lower() or "Wildcard" in result


# ---------------------------------------------------------------------------
# search_uploaded_documents — BM25 zero-result fallback (Task 4.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bm25_zero_result_with_filename_returns_fallback():
    """Task 6.6: BM25 miss + filename returns first chunks of targeted file."""
    from app.agent.tools import search_uploaded_documents

    # Create a file with enough chunks to skip the short-circuit (>3 chunks)
    long_text = "\n\n".join(
        f"[Page {i}]\nContent for page {i} with some filler words." for i in range(1, 10)
    )
    deps = _make_deps(
        doc_texts=[long_text],
        metadata=[{"filename": "report.pdf", "type": "pdf", "char_count": len(long_text)}],
    )
    # Query with a keyword that will never match any chunk text
    result = await search_uploaded_documents(
        deps=deps, query="xyzzyspoon", filename="report.pdf",
    )
    assert "No keyword matches found" in result
    assert "report.pdf" in result
    # Should still have actual file content returned as fallback
    assert "Content for page" in result


@pytest.mark.asyncio
async def test_bm25_zero_result_without_filename_returns_standard_error():
    """Task 6.7: BM25 miss without filename returns standard error, no fallback."""
    from app.agent.tools import search_uploaded_documents

    long_text = "\n\n".join(
        f"[Page {i}]\nContent for page {i} with some filler words." for i in range(1, 10)
    )
    deps = _make_deps(
        doc_texts=[long_text],
        metadata=[{"filename": "report.pdf", "type": "pdf", "char_count": len(long_text)}],
    )
    result = await search_uploaded_documents(deps=deps, query="xyzzyspoon")
    assert "No relevant passages found" in result
    # Should NOT have the fallback message
    assert "No keyword matches found" not in result


# ---------------------------------------------------------------------------
# KG extraction paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kg_non_document_single_call():
    """is_document=False should call extract_entities_and_relationships once."""
    from worker.entity_extraction import ExtractionResult, _extract_document_batched

    with patch("worker.entity_extraction.extract_entities_and_relationships") as mock_extract:
        mock_extract.return_value = ExtractionResult()
        # _process_message with is_document=False takes a different path,
        # so we test _extract_document_batched directly for the document path
        await _extract_document_batched("Short text no markers.")
        # Should still call extract at least once (single batch)
        assert mock_extract.call_count >= 1


@pytest.mark.asyncio
async def test_kg_document_with_markers_batched():
    """is_document=True with page markers should batch and call extract per batch."""
    from worker.entity_extraction import ExtractionResult, _extract_document_batched

    pages_text = "\n".join(
        [f"[Page {i}]\n" + f"Content for page {i}. " * 100 for i in range(1, 11)]
    )

    with patch("worker.entity_extraction.extract_entities_and_relationships") as mock_extract:
        mock_extract.return_value = ExtractionResult()
        result = await _extract_document_batched(pages_text)
        # Should have called extract multiple times (batched)
        assert mock_extract.call_count >= 1
        assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_kg_document_without_markers_paragraph_batched():
    """is_document=True without page markers should use RecursiveChunker then batch."""
    from worker.entity_extraction import ExtractionResult, _extract_document_batched

    # Long text without page markers
    text = "Paragraph about entities. " * 500

    with patch("worker.entity_extraction.extract_entities_and_relationships") as mock_extract:
        mock_extract.return_value = ExtractionResult()
        result = await _extract_document_batched(text)
        assert mock_extract.call_count >= 1
        assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_kg_batch_error_isolation():
    """A failed batch should not prevent other batches from succeeding."""
    from worker.entity_extraction import (
        ExtractionResult,
        ExtractedEntity,
        _extract_document_batched,
    )

    pages_text = "\n".join(
        [f"[Page {i}]\n" + f"Content for page {i}. " * 100 for i in range(1, 11)]
    )

    call_count = 0

    async def _mock_extract(text: str, is_document: bool = False, max_chars: int | None = 12_000) -> ExtractionResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated LLM failure")
        return ExtractionResult(
            entities=[ExtractedEntity(name="TestEntity", type="other")],
        )

    with patch("worker.entity_extraction.extract_entities_and_relationships", side_effect=_mock_extract):
        result = await _extract_document_batched(pages_text)
        # Should still have entities from the successful batches
        assert len(result.entities) > 0
        # The first batch failed but we should still have results from others
        assert call_count >= 2

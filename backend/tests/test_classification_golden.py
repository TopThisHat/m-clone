"""Golden dataset for heuristic classification accuracy.

Contains 55+ labeled test cases that validate the deterministic heuristic
classifier without requiring any LLM calls.  Each entry specifies:

    (query, has_documents, doc_metadata, expected_mode, description)

When ``expected_mode`` is None the heuristic is expected to return None,
meaning the query is ambiguous and should fall through to the LLM classifier.

Coverage targets:
  - 12 FORMAT_ONLY patterns
  - 12 QUICK_ANSWER patterns
  - 11 DATA_PROCESSING patterns (with various doc metadata)
  - 10 ambiguous patterns that should return None
  - 10+ edge cases (empty, very long, mixed signals, case variations)

Run: cd backend && uv run python -m pytest tests/test_classification_golden.py -v
"""
from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio

from app.agent.classifier import _heuristic_classify
from app.agent.runner_config import ExecutionMode


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Reusable doc metadata fixtures
# ---------------------------------------------------------------------------

_CSV_META: list[dict[str, Any]] = [
    {"filename": "data.csv", "rows": 100, "columns": ["name", "company"]},
]

_MULTI_CSV_META: list[dict[str, Any]] = [
    {"filename": "contacts.csv", "rows": 50},
    {"filename": "companies.xlsx", "rows": 200},
]

_PDF_META: list[dict[str, Any]] = [
    {"filename": "report.pdf", "pages": 15, "char_count": 25000},
]

_LARGE_CSV_META: list[dict[str, Any]] = [
    {"filename": "huge.csv", "rows": 5000, "columns": ["name", "email", "phone"]},
]


# ---------------------------------------------------------------------------
# Golden dataset — 55 labeled test cases
# ---------------------------------------------------------------------------

GOLDEN_DATASET: list[tuple[str, bool, list[dict[str, Any]] | None, str | None, str]] = [
    # ===================================================================
    # FORMAT_ONLY patterns (12 cases)
    # ===================================================================
    (
        "Reformat this as a table",
        False, None,
        "format_only",
        "basic reformat request",
    ),
    (
        "Summarize the above in 3 bullet points",
        False, None,
        "format_only",
        "summarize existing content",
    ),
    (
        "Convert to markdown",
        False, None,
        "format_only",
        "format conversion",
    ),
    (
        "Reorganize these notes by topic",
        False, None,
        "format_only",
        "reorganize existing text",
    ),
    (
        "Translate this to Spanish",
        False, None,
        "format_only",
        "translation request",
    ),
    (
        "Please rephrase this paragraph more formally",
        False, None,
        "format_only",
        "rephrase request",
    ),
    (
        "Rewrite this email in a professional tone",
        False, None,
        "format_only",
        "rewrite request",
    ),
    (
        "Summarize this for my boss",
        False, None,
        "format_only",
        "summarize for audience",
    ),
    (
        "Put this as bullet points please",
        False, None,
        "format_only",
        "bullet points via 'as bullet points'",
    ),
    (
        "REFORMAT THIS AS A NUMBERED LIST",
        False, None,
        "format_only",
        "uppercase format request (case insensitive)",
    ),
    (
        "as a table with proper headers",
        False, None,
        "format_only",
        "partial sentence format request",
    ),
    (
        "Can you reorganize the above section?",
        False, None,
        "format_only",
        "reorganize question form",
    ),

    # ===================================================================
    # QUICK_ANSWER patterns (12 cases)
    # ===================================================================
    (
        "What is Apple's P/E ratio?",
        False, None,
        "quick_answer",
        "single financial metric",
    ),
    (
        "Who is the CEO of Tesla?",
        False, None,
        "quick_answer",
        "single person lookup",
    ),
    (
        "When did Amazon go public?",
        False, None,
        "quick_answer",
        "single date fact",
    ),
    (
        "How much revenue did Google make last quarter?",
        False, None,
        "quick_answer",
        "single revenue figure",
    ),
    (
        "What's the market cap of Microsoft?",
        False, None,
        "quick_answer",
        "contraction form question",
    ),
    (
        "What is the current price of NVDA?",
        False, None,
        "quick_answer",
        "stock price question",
    ),
    (
        "Who is the founder of Stripe?",
        False, None,
        "quick_answer",
        "founder question",
    ),
    (
        "What is GDP?",
        False, None,
        "quick_answer",
        "definition question",
    ),
    (
        "What is Nvidia's ticker symbol?",
        False, None,
        "quick_answer",
        "simple factoid",
    ),
    (
        "Who is Tim Cook?",
        False, None,
        "quick_answer",
        "who is person question",
    ),
    (
        "How much is Bitcoin worth?",
        False, None,
        "quick_answer",
        "price question",
    ),
    (
        "When did the iPhone launch?",
        False, None,
        "quick_answer",
        "date question about product",
    ),

    # ===================================================================
    # DATA_PROCESSING patterns (11 cases — require docs + tabular data)
    # ===================================================================
    (
        "Look up all the names in this file",
        True, _CSV_META,
        "data_processing",
        "CSV lookup with 'look up'",
    ),
    (
        "Process each row and enrich with company info",
        True, _CSV_META,
        "data_processing",
        "process + enrich on CSV",
    ),
    (
        "Extract all entities from the spreadsheet",
        True, _CSV_META,
        "data_processing",
        "extract on CSV",
    ),
    (
        "Batch look up these companies",
        True, _CSV_META,
        "data_processing",
        "batch keyword on CSV",
    ),
    (
        "Cross-reference the names with our database",
        True, _CSV_META,
        "data_processing",
        "cross-reference on CSV",
    ),
    (
        "Check which companies are publicly traded",
        True, _CSV_META,
        "data_processing",
        "check which on CSV",
    ),
    (
        "For each row find the CEO",
        True, _CSV_META,
        "data_processing",
        "for each row on CSV",
    ),
    (
        "Parse the data and enrich with market data",
        True, _CSV_META,
        "data_processing",
        "parse + enrich on CSV",
    ),
    (
        "Look up every row in our CRM",
        True, _MULTI_CSV_META,
        "data_processing",
        "every row with multiple CSVs",
    ),
    (
        "Process all names in the uploaded file",
        True, _LARGE_CSV_META,
        "data_processing",
        "process on large CSV (5000 rows)",
    ),
    (
        "Enrich the contacts spreadsheet with GWM IDs",
        True, _CSV_META,
        "data_processing",
        "enrich keyword on CSV",
    ),

    # ===================================================================
    # Ambiguous patterns — should return None (fall through to LLM) (10 cases)
    # ===================================================================
    (
        "Tell me about recent market trends for tech companies",
        False, None,
        None,
        "broad research topic — no heuristic match",
    ),
    (
        "Analyze the competitive landscape of cloud computing",
        False, None,
        None,
        "multi-faceted analysis — no heuristic match",
    ),
    (
        "Compare Uber and Lyft's business models in detail",
        False, None,
        None,
        "deep comparison — no heuristic match",
    ),
    (
        "What are the key risks facing the semiconductor industry?",
        False, None,
        None,
        "long question — exceeds QUICK_ANSWER token limit",
    ),
    (
        "Research the top SaaS companies and their pricing strategies",
        False, None,
        None,
        "research keyword but too complex for heuristic",
    ),
    (
        "Analyze Tesla's competitive position in the EV market and compare with BYD",
        False, None,
        None,
        "complex analysis — no heuristic match",
    ),
    (
        "Create a comprehensive report on the state of AI in healthcare",
        False, None,
        None,
        "report creation — no heuristic match",
    ),
    (
        "Evaluate the merits of investing in emerging markets vs developed markets",
        False, None,
        None,
        "evaluation — no heuristic match",
    ),
    (
        "Help me understand the recent regulatory changes in fintech",
        False, None,
        None,
        "help me understand — no heuristic match",
    ),
    (
        "What are the implications of the Fed's rate decision on REITs?",
        False, None,
        None,
        "long question with financial jargon — exceeds token limit",
    ),

    # ===================================================================
    # Edge cases (10 cases)
    # ===================================================================
    (
        "",
        False, None,
        None,
        "empty string — should return None",
    ),
    (
        "   ",
        False, None,
        None,
        "whitespace only — should return None",
    ),
    (
        "\n\t\r",
        False, None,
        None,
        "whitespace chars only — should return None",
    ),
    (
        "Look up all names in the document",
        False, None,
        None,
        "data action verb WITHOUT documents — should NOT match DATA_PROCESSING",
    ),
    (
        "Look up all names in the file",
        True, _PDF_META,
        None,
        "data action verb with PDF (no rows) — should NOT match DATA_PROCESSING",
    ),
    (
        "What is Apple's stock price then compare it with MSFT and analyze the trend",
        False, None,
        None,
        "starts like QUICK_ANSWER but has sequential indicators",
    ),
    (
        " ".join(["elaborate"] * 30),
        False, None,
        None,
        "very long single-word repetition — no heuristic match",
    ),
    (
        "WHAT IS THE GDP OF THE UNITED STATES?",
        False, None,
        "quick_answer",
        "uppercase QUICK_ANSWER — case insensitive matching",
    ),
    (
        "reformat",
        False, None,
        "format_only",
        "single keyword — minimal FORMAT_ONLY match",
    ),
    (
        "Summarize the above and then research new competitors in the market",
        False, None,
        "format_only",
        "starts with format pattern — heuristic matches first even with research intent",
    ),
]


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,has_docs,metadata,expected,desc",
    GOLDEN_DATASET,
    ids=[t[4] for t in GOLDEN_DATASET],
)
def test_heuristic_classification(
    query: str,
    has_docs: bool,
    metadata: list[dict[str, Any]] | None,
    expected: str | None,
    desc: str,
) -> None:
    """Validate heuristic classification against the golden dataset.

    Each test case specifies an expected mode string (or None for ambiguous).
    The heuristic classifier must either match the expected mode or return
    None when the query is ambiguous.
    """
    result = _heuristic_classify(query, has_docs, metadata)

    if expected is None:
        assert result is None, (
            f"Should fall through to LLM: {desc!r} — "
            f"got {result.mode.value if result else 'None'}"
        )
    else:
        assert result is not None, (
            f"Should match heuristic: {desc!r} — got None"
        )
        assert result.mode.value == expected, (
            f"Wrong mode for: {desc!r} — "
            f"expected {expected!r}, got {result.mode.value!r}"
        )
        assert result.source == "heuristic"
        assert 0.0 < result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Aggregate accuracy metric
# ---------------------------------------------------------------------------


class TestGoldenDatasetCoverage:
    """Meta-tests to ensure the golden dataset has adequate coverage."""

    def test_minimum_50_cases(self):
        """The golden dataset must contain at least 50 test cases."""
        assert len(GOLDEN_DATASET) >= 50, (
            f"Golden dataset has only {len(GOLDEN_DATASET)} cases; need >= 50"
        )

    def test_minimum_10_format_only(self):
        count = sum(1 for _, _, _, mode, _ in GOLDEN_DATASET if mode == "format_only")
        assert count >= 10, f"Only {count} FORMAT_ONLY cases; need >= 10"

    def test_minimum_10_quick_answer(self):
        count = sum(1 for _, _, _, mode, _ in GOLDEN_DATASET if mode == "quick_answer")
        assert count >= 10, f"Only {count} QUICK_ANSWER cases; need >= 10"

    def test_minimum_10_data_processing(self):
        count = sum(1 for _, _, _, mode, _ in GOLDEN_DATASET if mode == "data_processing")
        assert count >= 10, f"Only {count} DATA_PROCESSING cases; need >= 10"

    def test_minimum_10_ambiguous(self):
        count = sum(1 for _, _, _, mode, _ in GOLDEN_DATASET if mode is None)
        assert count >= 10, f"Only {count} ambiguous (None) cases; need >= 10"

    def test_minimum_10_edge_cases(self):
        """Edge cases include empty strings, whitespace, case variations,
        very long queries, and mixed signals."""
        # Count cases from the edge-case section (last 10 in the dataset)
        edge_descs = {desc for _, _, _, _, desc in GOLDEN_DATASET if "edge" in desc.lower()
                      or "empty" in desc.lower()
                      or "whitespace" in desc.lower()
                      or "uppercase" in desc.lower()
                      or "case" in desc.lower()
                      or "long" in desc.lower()
                      or "minimal" in desc.lower()
                      or "WITHOUT documents" in desc
                      or "no rows" in desc
                      or "sequential" in desc
                      or "starts with" in desc}
        assert len(edge_descs) >= 10, (
            f"Only {len(edge_descs)} edge cases; need >= 10"
        )

    def test_data_processing_cases_have_documents(self):
        """All DATA_PROCESSING cases must have has_documents=True."""
        for query, has_docs, metadata, mode, desc in GOLDEN_DATASET:
            if mode == "data_processing":
                assert has_docs is True, (
                    f"DATA_PROCESSING case missing has_documents=True: {desc!r}"
                )
                assert metadata is not None, (
                    f"DATA_PROCESSING case missing metadata: {desc!r}"
                )

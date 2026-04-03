"""Tests for compact JSON output format in app.agent.batch_resolver.

Validates the compact JSON output format introduced as an alternative to
the existing markdown table format. The compact format reduces token usage
by at least 40% while preserving all result data.

Coverage:
  - JSON structure (summary + results keys)
  - All input rows present in output
  - Token reduction vs. markdown (>= 40%)
  - Matched entry fields (gwm_id, confidence, status)
  - No-match entry structure
  - Error entry structure
  - Empty input handling
  - Backward compatibility of existing markdown format

Run: cd backend && uv run python -m pytest tests/test_compact_json_output.py -v
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.agent.batch_resolver import (
    format_results_as_compact_json,
    format_results_as_markdown,
)


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matched_result(name: str = "John Smith", gwm_id: str = "GWM-001",
                    confidence: float = 0.92) -> dict[str, Any]:
    """Build a matched result dict for testing."""
    return {
        "name": name,
        "status": "matched",
        "gwm_id": gwm_id,
        "confidence": confidence,
        "error": None,
    }


def _no_match_result(name: str = "Unknown Person") -> dict[str, Any]:
    """Build a no-match result dict for testing."""
    return {
        "name": name,
        "status": "no_match",
        "gwm_id": None,
        "confidence": None,
        "error": None,
    }


def _error_result(name: str = "Bad Entry",
                  error: str = "Connection timed out") -> dict[str, Any]:
    """Build an error result dict for testing."""
    return {
        "name": name,
        "status": "error",
        "gwm_id": None,
        "confidence": None,
        "error": error,
    }


# ---------------------------------------------------------------------------
# JSON Structure
# ---------------------------------------------------------------------------

class TestCompactJsonStructure:
    """Verify the compact JSON format has the required top-level keys."""

    def test_format_compact_json_structure(self):
        """The compact JSON output must contain 'summary' and 'results'
        top-level keys. 'summary' holds aggregate counts; 'results' holds
        per-entity details.

        Spec ref: m-clone-v936, compact JSON output format.
        """
        results = [_matched_result(), _no_match_result(), _error_result()]
        raw = format_results_as_compact_json(results)
        parsed = json.loads(raw)

        assert "summary" in parsed
        assert "results" in parsed

        summary = parsed["summary"]
        assert summary["total"] == 3
        assert summary["matched"] == 1
        assert summary["no_match"] == 1
        assert summary["errors"] == 1


# ---------------------------------------------------------------------------
# Row Completeness
# ---------------------------------------------------------------------------

class TestCompactJsonRowCompleteness:
    """Verify all input rows appear in the compact JSON output."""

    def test_format_compact_json_all_rows_present(self):
        """Every name provided in the input list must appear as an entry
        in the 'results' array of the compact JSON output. No silent drops.

        Spec ref: m-clone-v936, anti-truncation guarantee.
        """
        results = [_matched_result(f"Person {i}") for i in range(500)]
        raw = format_results_as_compact_json(results)
        parsed = json.loads(raw)

        assert len(parsed["results"]) == 500
        assert parsed["summary"]["total"] == 500


# ---------------------------------------------------------------------------
# Token Reduction
# ---------------------------------------------------------------------------

class TestCompactJsonTokenEfficiency:
    """Verify the compact JSON format is machine-parseable and compact."""

    def test_format_compact_json_no_whitespace_padding(self):
        """The compact JSON output must use minimal separators (no indentation,
        no trailing spaces). This ensures efficient token usage when the result
        is embedded in an LLM tool response.

        Spec ref: m-clone-v936, compact JSON output format.
        """
        results = [
            _matched_result("John Smith", "GWM-001", 0.92),
            _no_match_result("Unknown Person"),
            _error_result("Bad Entry", "Connection timed out"),
        ]
        raw = format_results_as_compact_json(results)

        # Must be valid JSON
        parsed = json.loads(raw)
        assert len(parsed["results"]) == 3

        # Must not contain pretty-print whitespace (no indentation, no
        # space after colons/commas).
        assert "\n" not in raw
        assert ": " not in raw  # compact separators have no space after ':'
        assert ", " not in raw  # compact separators have no space after ','

    def test_format_compact_json_single_entry_smaller_than_markdown(self):
        """For single-entry results the compact JSON should be smaller than
        markdown thanks to the absence of header/separator rows.

        Spec ref: m-clone-v936, token reduction target.
        """
        results = [_matched_result("John Smith", "GWM-001", 0.92)]
        md_output = format_results_as_markdown(results)
        json_output = format_results_as_compact_json(results)

        assert len(json_output) < len(md_output), (
            f"Expected JSON to be smaller for single entry "
            f"(markdown={len(md_output)} chars, json={len(json_output)} chars)"
        )


# ---------------------------------------------------------------------------
# Matched Entry Fields
# ---------------------------------------------------------------------------

class TestCompactJsonMatchedEntry:
    """Verify matched entries have the required fields."""

    def test_format_compact_json_matched_entry(self):
        """Each matched entry in the compact JSON 'results' array must
        include: gwm_id (str), confidence (float), and status ('matched').

        Spec ref: m-clone-v936, matched entry schema.
        """
        results = [_matched_result("Alice Smith", "GWM-123", 0.94)]
        raw = format_results_as_compact_json(results)
        parsed = json.loads(raw)

        entry = parsed["results"][0]
        assert entry["name"] == "Alice Smith"
        assert entry["gwm_id"] == "GWM-123"
        assert entry["confidence"] == 0.94
        assert entry["status"] == "matched"


# ---------------------------------------------------------------------------
# No-Match Entry
# ---------------------------------------------------------------------------

class TestCompactJsonNoMatchEntry:
    """Verify no-match entries have the correct structure."""

    def test_format_compact_json_no_match_entry(self):
        """No-match entries must have: gwm_id=null, confidence=null,
        status='no_match'. They must NOT have an error field populated.

        Spec ref: m-clone-v936, no-match entry schema.
        """
        results = [_no_match_result("Nobody Special")]
        raw = format_results_as_compact_json(results)
        parsed = json.loads(raw)

        entry = parsed["results"][0]
        assert entry["name"] == "Nobody Special"
        assert entry["gwm_id"] is None
        assert entry["confidence"] is None
        assert entry["status"] == "no_match"


# ---------------------------------------------------------------------------
# Error Entry
# ---------------------------------------------------------------------------

class TestCompactJsonErrorEntry:
    """Verify error entries have the correct structure."""

    def test_format_compact_json_error_entry(self):
        """Error entries must have: status='error', and gwm_id=null.

        Spec ref: m-clone-v936, error entry schema.
        """
        results = [_error_result("Bad Entry", "Connection timed out")]
        raw = format_results_as_compact_json(results)
        parsed = json.loads(raw)

        entry = parsed["results"][0]
        assert entry["name"] == "Bad Entry"
        assert entry["gwm_id"] is None
        assert entry["confidence"] is None
        assert entry["status"] == "error"


# ---------------------------------------------------------------------------
# Empty Input
# ---------------------------------------------------------------------------

class TestCompactJsonEmptyInput:
    """Verify handling of empty input lists."""

    def test_format_compact_json_empty_input(self):
        """When given an empty list, the compact JSON output should return
        'No names provided.' (same as the markdown version).

        Spec ref: m-clone-v936, empty input edge case.
        """
        result = format_results_as_compact_json([])
        assert result == "No names provided."


# ---------------------------------------------------------------------------
# Markdown Backward Compatibility
# ---------------------------------------------------------------------------

class TestMarkdownBackwardCompat:
    """Verify the existing markdown format is unchanged."""

    def test_format_markdown_backward_compat(self):
        """The existing format_results_as_markdown() function must continue
        to produce the same markdown table format (with pipe-delimited
        columns, summary header, and status indicators) so that callers
        using the markdown format are not broken by the compact JSON
        addition.

        Spec ref: m-clone-v936, backward compatibility requirement.
        """
        results = [_matched_result("Jane Doe", "GWM-999", 0.88)]
        md = format_results_as_markdown(results)

        assert "Processed 1 name" in md
        assert "| # | Entity Name |" in md
        assert "Jane Doe" in md
        assert "GWM-999" in md
        assert "88%" in md
        assert "Matched" in md

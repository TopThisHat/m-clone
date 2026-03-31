"""Unit tests for app.agent.batch_resolver.

Pure unit tests -- no database, no network, no external services.
All async DB calls, LLM calls, and resolve_client calls are mocked.

Coverage:
  - batch_resolve_clients()        (issue m-clone-gloe)
  - format_results_as_markdown()   (issue m-clone-gloe)
  - _split_into_chunks()           (issue m-clone-ziyw)
  - extract_person_names()         (issue m-clone-ziyw)
  - _extract_names_from_chunk()    (issue m-clone-ziyw)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.client_lookup import (
    AdjudicationMethod,
    LookupResult,
    SearchSummary,
)


# ---------------------------------------------------------------------------
# Override the autouse _ensure_schema fixture from conftest.py so that
# these pure-unit tests never attempt to connect to PostgreSQL.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_summary(fuzzy: int = 1, hpq: int = 0) -> SearchSummary:
    return SearchSummary(fuzzy_client_hits=fuzzy, hpq_client_hits=hpq)


def _make_lookup_result(
    match_found: bool = True,
    gwm_id: str | None = "GWM-001",
    matched_name: str | None = "John Smith",
    confidence: float = 0.92,
    source: str = "fuzzy_client",
) -> LookupResult:
    """Build a LookupResult with sensible defaults for testing."""
    return LookupResult(
        match_found=match_found,
        gwm_id=gwm_id if match_found else None,
        matched_name=matched_name if match_found else None,
        source=source if match_found else None,
        confidence=confidence,
        adjudication=AdjudicationMethod.LLM,
        search_summary=_make_search_summary(),
    )


def _make_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response with the given content."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


# ===========================================================================
# batch_resolve_clients tests (issue m-clone-gloe)
# ===========================================================================


class TestBatchResolveClientsEmpty:
    """Empty input returns empty list."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_list(self):
        from app.agent.batch_resolver import batch_resolve_clients

        result = await batch_resolve_clients([])
        assert result == []


class TestBatchResolveClientsSingleName:
    """Single name resolution works."""

    @pytest.mark.asyncio
    async def test_single_name_matched(self):
        from app.agent.batch_resolver import batch_resolve_clients

        mock_result = _make_lookup_result(match_found=True, gwm_id="GWM-100")

        with patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_rc:
            mock_rc.return_value = mock_result
            results = await batch_resolve_clients([{"name": "John Smith"}])

        assert len(results) == 1
        assert results[0]["status"] == "matched"
        assert results[0]["gwm_id"] == "GWM-100"
        mock_rc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_single_name_no_match(self):
        from app.agent.batch_resolver import batch_resolve_clients

        mock_result = _make_lookup_result(match_found=False, confidence=0.0)

        with patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_rc:
            mock_rc.return_value = mock_result
            results = await batch_resolve_clients([{"name": "Unknown Person"}])

        assert len(results) == 1
        assert results[0]["status"] == "no_match"
        assert results[0]["gwm_id"] is None


class TestBatchResolveClientsConcurrency:
    """Multiple names resolve concurrently; semaphore is respected."""

    @pytest.mark.asyncio
    async def test_multiple_names_resolve_concurrently(self):
        from app.agent.batch_resolver import batch_resolve_clients

        names = [{"name": f"Person {i}"} for i in range(5)]

        async def _mock_resolve(name: str, company: str | None = None) -> LookupResult:
            return _make_lookup_result(
                match_found=True, gwm_id=f"GWM-{name.split()[-1]}", matched_name=name,
            )

        with patch("app.agent.batch_resolver.resolve_client", side_effect=_mock_resolve):
            results = await batch_resolve_clients(names)

        assert len(results) == 5
        assert all(r["status"] == "matched" for r in results)

    @pytest.mark.asyncio
    async def test_concurrency_semaphore_respected(self):
        """At most 10 concurrent resolve_client calls at any moment."""
        from app.agent.batch_resolver import batch_resolve_clients

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            # Yield control so other tasks can enter concurrently.
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return _make_lookup_result(match_found=True, matched_name=name)

        names = [{"name": f"Person {i}"} for i in range(25)]

        with patch("app.agent.batch_resolver.resolve_client", side_effect=_mock_resolve):
            results = await batch_resolve_clients(names)

        assert len(results) == 25
        assert max_concurrent <= 10, f"Expected at most 10 concurrent calls, got {max_concurrent}"


class TestBatchResolveClientsErrorIsolation:
    """Individual resolve_client exceptions don't stop the batch."""

    @pytest.mark.asyncio
    async def test_single_failure_does_not_stop_batch(self):
        from app.agent.batch_resolver import batch_resolve_clients

        call_count = 0

        async def _mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal call_count
            call_count += 1
            if "Fail" in name:
                raise RuntimeError("Simulated lookup failure")
            return _make_lookup_result(match_found=True, matched_name=name)

        names = [
            {"name": "Alice Good"},
            {"name": "Fail Person"},
            {"name": "Bob Good"},
        ]

        with patch("app.agent.batch_resolver.resolve_client", side_effect=_mock_resolve):
            results = await batch_resolve_clients(names)

        assert len(results) == 3
        statuses = {r["name"]: r["status"] for r in results}
        assert statuses["Alice Good"] == "matched"
        assert statuses["Fail Person"] == "error"
        assert statuses["Bob Good"] == "matched"
        assert any("Simulated lookup failure" in (r.get("error") or "") for r in results)

    @pytest.mark.asyncio
    async def test_multiple_failures_captured(self):
        from app.agent.batch_resolver import batch_resolve_clients

        async def _mock_resolve(name: str, company: str | None = None) -> LookupResult:
            raise ValueError(f"Error for {name}")

        names = [{"name": "Person A"}, {"name": "Person B"}, {"name": "Person C"}]

        with patch("app.agent.batch_resolver.resolve_client", side_effect=_mock_resolve):
            results = await batch_resolve_clients(names)

        assert len(results) == 3
        assert all(r["status"] == "error" for r in results)
        assert all(r["error"] is not None for r in results)


class TestBatchResolveClientsDeduplication:
    """Names are deduplicated case-insensitively; first-seen original preserved."""

    @pytest.mark.asyncio
    async def test_case_insensitive_dedup_single_call(self):
        from app.agent.batch_resolver import batch_resolve_clients

        with patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_rc:
            mock_rc.return_value = _make_lookup_result(match_found=True)
            results = await batch_resolve_clients([
                {"name": "John Smith"},
                {"name": "john smith"},
                {"name": "JOHN SMITH"},
            ])

        # Should only call resolve_client once for the deduplicated name.
        assert mock_rc.await_count == 1
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_dedup_preserves_first_seen_original_name(self):
        from app.agent.batch_resolver import batch_resolve_clients

        with patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_rc:
            mock_rc.return_value = _make_lookup_result(match_found=True)
            results = await batch_resolve_clients([
                {"name": "John Smith"},
                {"name": "john smith"},
            ])

        # The result should use the first-seen original name form.
        assert results[0]["name"] == "John Smith"


class TestBatchResolveClientsCompanyPassthrough:
    """Company field is passed through to resolve_client."""

    @pytest.mark.asyncio
    async def test_company_passed_to_resolve_client(self):
        from app.agent.batch_resolver import batch_resolve_clients

        with patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_rc:
            mock_rc.return_value = _make_lookup_result(match_found=True)
            await batch_resolve_clients([
                {"name": "Jane Doe", "company": "Acme Corp"},
            ])

        # Verify company was passed through.
        mock_rc.assert_awaited_once()
        _, kwargs = mock_rc.call_args
        assert kwargs.get("company") == "Acme Corp" or mock_rc.call_args[1].get("company") == "Acme Corp"


# ===========================================================================
# format_results_as_markdown tests (issue m-clone-gloe)
# ===========================================================================


class TestFormatResultsEmpty:
    """Empty results produce a plain-text message."""

    def test_empty_results_returns_no_names(self):
        from app.agent.batch_resolver import format_results_as_markdown

        assert format_results_as_markdown([]) == "No names provided."


class TestFormatResultsSingleMatch:
    """Single matched result produces correct markdown table."""

    def test_single_matched_result(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "John Smith",
            "status": "matched",
            "gwm_id": "GWM-001",
            "confidence": 0.92,
            "error": None,
        }]
        md = format_results_as_markdown(results)

        assert "Processed 1 name:" in md
        assert "1 matched" in md
        assert "0 no match" in md
        assert "John Smith" in md
        assert "GWM-001" in md
        assert "92%" in md
        assert "Matched" in md
        # Table structure
        assert "| # |" in md
        assert "|---|" in md


class TestFormatResultsMixed:
    """Mixed results (matched + no_match + error) all appear correctly."""

    def _build_mixed_results(self) -> list[dict]:
        return [
            {
                "name": "Alice Good",
                "status": "matched",
                "gwm_id": "GWM-100",
                "confidence": 0.85,
                "error": None,
            },
            {
                "name": "Bob Unknown",
                "status": "no_match",
                "gwm_id": None,
                "confidence": None,
                "error": None,
            },
            {
                "name": "Charlie Bad",
                "status": "error",
                "gwm_id": None,
                "confidence": None,
                "error": "Connection timed out",
            },
        ]

    def test_all_rows_present(self):
        from app.agent.batch_resolver import format_results_as_markdown

        md = format_results_as_markdown(self._build_mixed_results())

        assert "Alice Good" in md
        assert "Bob Unknown" in md
        assert "Charlie Bad" in md

    def test_summary_counts_correct(self):
        from app.agent.batch_resolver import format_results_as_markdown

        md = format_results_as_markdown(self._build_mixed_results())

        assert "Processed 3 names:" in md
        assert "1 matched" in md
        assert "1 no match" in md
        assert "1 error" in md

    def test_confidence_formatted_as_percentage(self):
        from app.agent.batch_resolver import format_results_as_markdown

        md = format_results_as_markdown(self._build_mixed_results())

        assert "85%" in md

    def test_no_match_rows_show_dash(self):
        from app.agent.batch_resolver import format_results_as_markdown

        md = format_results_as_markdown(self._build_mixed_results())
        lines = md.split("\n")
        bob_row = next(line for line in lines if "Bob Unknown" in line)
        # no_match rows use "—" for ID and confidence
        assert bob_row.count("—") >= 2

    def test_error_rows_show_error_description(self):
        from app.agent.batch_resolver import format_results_as_markdown

        md = format_results_as_markdown(self._build_mixed_results())
        lines = md.split("\n")
        charlie_row = next(line for line in lines if "Charlie Bad" in line)
        assert "Connection timed out" in charlie_row


class TestFormatResultsErrorTruncation:
    """Error descriptions longer than 80 chars are truncated."""

    def test_error_truncated_at_80_chars(self):
        from app.agent.batch_resolver import format_results_as_markdown

        long_error = "A" * 200
        results = [{
            "name": "Fail Person",
            "status": "error",
            "gwm_id": None,
            "confidence": None,
            "error": long_error,
        }]
        md = format_results_as_markdown(results)

        lines = md.split("\n")
        fail_row = next(line for line in lines if "Fail Person" in line)
        # The full 200-char error should NOT appear; it should be truncated.
        assert long_error not in fail_row
        assert "..." in fail_row


class TestFormatResultsPipeEscaping:
    """Pipe characters in names are escaped so they don't break markdown tables."""

    def test_pipe_in_name_escaped(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "Smith | Jones",
            "status": "matched",
            "gwm_id": "GWM-099",
            "confidence": 0.88,
            "error": None,
        }]
        md = format_results_as_markdown(results)

        # The pipe in the name should be escaped.
        assert "Smith \\| Jones" in md


# ===========================================================================
# _split_into_chunks tests (issue m-clone-ziyw)
# ===========================================================================


class TestSplitIntoChunks:
    """Tests for _split_into_chunks() in app.agent.batch_resolver."""

    def setup_method(self):
        from app.agent.batch_resolver import _split_into_chunks
        self.split = _split_into_chunks

    def test_short_text_returns_single_chunk(self):
        text = "Hello world"
        chunks = self.split(text, chunk_size=100, overlap=20)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_into_multiple_chunks(self):
        # 100 words of ~6 chars each = ~600 chars
        text = " ".join(["alpha"] * 100)
        chunks = self.split(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1

    def test_chunks_have_overlap(self):
        """Adjacent chunks share content near the boundary."""
        text = " ".join(f"word{i}" for i in range(50))
        chunks = self.split(text, chunk_size=60, overlap=20)
        assert len(chunks) >= 2
        # Because of overlap, the end of chunk[0] and start of chunk[1] should share text.
        chunk0_words = set(chunks[0].split())
        chunk1_words = set(chunks[1].split())
        overlap_words = chunk0_words & chunk1_words
        assert len(overlap_words) > 0, "Expected overlap between adjacent chunks"

    def test_split_at_whitespace_boundary(self):
        """The first chunk should end at a whitespace boundary, not mid-word."""
        # Use words of varying lengths so the split point falls mid-word if
        # the implementation is naive.
        text = "abcdefghij klmnopqrst uvwxyzabcd efghijklmn"
        # chunk_size=25 puts the raw cut inside "uvwxyzabcd"; the algorithm
        # should walk back to the space after "klmnopqrst".
        chunks = self.split(text, chunk_size=25, overlap=5)
        assert len(chunks) >= 2
        # The first chunk must end at a space boundary, so it should equal
        # "abcdefghij klmnopqrst" (the last whitespace before position 25).
        first_end = chunks[0].rstrip()
        assert first_end.endswith("klmnopqrst"), (
            f"Expected first chunk to end at word boundary, got: {chunks[0]!r}"
        )

    def test_empty_text_returns_single_chunk(self):
        """Empty text returns a list with the empty string (before the filter)."""
        chunks = self.split("", chunk_size=100, overlap=10)
        # The implementation filters out whitespace-only chunks.
        # An empty string is the input itself which passes len(text) <= chunk_size.
        assert len(chunks) == 1
        assert chunks[0] == ""

    def test_text_exactly_chunk_size(self):
        """Text with length == chunk_size returns a single chunk."""
        text = "a" * 100
        chunks = self.split(text, chunk_size=100, overlap=20)
        assert len(chunks) == 1
        assert chunks[0] == text


# ===========================================================================
# extract_person_names tests (issue m-clone-ziyw)
# ===========================================================================


class TestExtractPersonNamesEmpty:
    """Empty/whitespace text returns empty list."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty(self):
        from app.agent.batch_resolver import extract_person_names

        names, count = await extract_person_names("")
        assert names == []
        assert count == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty(self):
        from app.agent.batch_resolver import extract_person_names

        names, count = await extract_person_names("   \n\t  ")
        assert names == []
        assert count == 0

    @pytest.mark.asyncio
    async def test_none_returns_empty(self):
        from app.agent.batch_resolver import extract_person_names

        names, count = await extract_person_names(None)
        assert names == []
        assert count == 0


class TestExtractPersonNamesSingleChunk:
    """Single chunk extraction with mocked LLM call."""

    @pytest.mark.asyncio
    async def test_single_chunk_returns_names(self):
        from app.agent.batch_resolver import extract_person_names

        response = _make_openai_response(json.dumps({"names": ["John Smith", "Jane Doe"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names, count = await extract_person_names("John Smith met Jane Doe for lunch.")

        assert "John Smith" in names
        assert "Jane Doe" in names
        assert count == 2


class TestExtractPersonNamesMultiChunkDedup:
    """Multi-chunk extraction with deduplication across chunks."""

    @pytest.mark.asyncio
    async def test_exact_duplicates_deduplicated(self):
        from app.agent.batch_resolver import extract_person_names

        response1 = _make_openai_response(json.dumps({"names": ["Robert Kraft"]}))
        response2 = _make_openai_response(json.dumps({"names": ["Robert Kraft"]}))

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[response1, response2])

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            with patch(
                "app.agent.batch_resolver._split_into_chunks",
                return_value=["chunk one text", "chunk two text"],
            ):
                names, count = await extract_person_names("Some text about Robert Kraft.")

        # "Robert Kraft" appears in both chunks but should be deduplicated.
        assert names.count("Robert Kraft") == 1
        # Total raw count should reflect both mentions.
        assert count == 2

    @pytest.mark.asyncio
    async def test_case_insensitive_dedup(self):
        from app.agent.batch_resolver import extract_person_names

        response1 = _make_openai_response(json.dumps({"names": ["Robert Kraft"]}))
        response2 = _make_openai_response(json.dumps({"names": ["robert kraft"]}))

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[response1, response2])

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            with patch(
                "app.agent.batch_resolver._split_into_chunks",
                return_value=["chunk one text", "chunk two text"],
            ):
                names, count = await extract_person_names("Some text about Robert Kraft.")

        # Case-insensitive dedup: only first-seen form preserved.
        assert len([n for n in names if n.lower() == "robert kraft"]) == 1
        assert count == 2

    @pytest.mark.asyncio
    async def test_name_variations_preserved(self):
        """'Robert Kraft' and 'Bob Kraft' are different surface forms and both kept."""
        from app.agent.batch_resolver import extract_person_names

        response1 = _make_openai_response(json.dumps({"names": ["Robert Kraft"]}))
        response2 = _make_openai_response(json.dumps({"names": ["Bob Kraft"]}))

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[response1, response2])

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            with patch(
                "app.agent.batch_resolver._split_into_chunks",
                return_value=["chunk one text", "chunk two text"],
            ):
                names, count = await extract_person_names("Some text about people.")

        assert "Robert Kraft" in names
        assert "Bob Kraft" in names
        assert count == 2


class TestExtractPersonNamesLLMError:
    """LLM timeout/error returns empty list for that chunk, others continue."""

    @pytest.mark.asyncio
    async def test_timeout_chunk_returns_empty_others_continue(self):
        from app.agent.batch_resolver import extract_person_names

        call_count = 0
        good_response = _make_openai_response(json.dumps({"names": ["Alice Jones"]}))

        async def _mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return good_response

        mock_client = MagicMock()
        mock_client.chat.completions.create = _mock_create

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            with patch(
                "app.agent.batch_resolver._split_into_chunks",
                return_value=["chunk one text", "chunk two text"],
            ):
                names, count = await extract_person_names("Some document text here.")

        # The second chunk should still produce results even though the first timed out.
        assert "Alice Jones" in names
        assert count == 1


class TestExtractPersonNamesResponseFormats:
    """Handles both JSON object and bare JSON array responses."""

    @pytest.mark.asyncio
    async def test_handles_json_object_response(self):
        from app.agent.batch_resolver import extract_person_names

        response = _make_openai_response(json.dumps({"names": ["John Smith"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names, count = await extract_person_names("John Smith is an owner.")

        assert "John Smith" in names
        assert count == 1

    @pytest.mark.asyncio
    async def test_handles_bare_array_response(self):
        from app.agent.batch_resolver import extract_person_names

        response = _make_openai_response(json.dumps(["Jane Doe", "Bob Smith"]))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names, count = await extract_person_names("Jane Doe and Bob Smith.")

        assert "Jane Doe" in names
        assert "Bob Smith" in names
        assert count == 2


# ===========================================================================
# _extract_names_from_chunk tests (issue m-clone-ziyw)
# ===========================================================================


class TestExtractNamesFromChunkSuccess:
    """Successful extraction returns names."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps({"names": ["Alice", "Bob"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Alice met Bob at the park.")

        assert names == ["Alice", "Bob"]


class TestExtractNamesFromChunkTimeout:
    """Timeout returns empty list."""

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Some text here.")

        assert names == []


class TestExtractNamesFromChunkAPIError:
    """API error returns empty list."""

    @pytest.mark.asyncio
    async def test_api_error_returns_empty(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API connection refused")
        )

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Some text here.")

        assert names == []


class TestExtractNamesFromChunkInvalidJSON:
    """Invalid JSON returns empty list."""

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response("not valid json at all {{{}}")
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Some text here.")

        assert names == []


class TestExtractNamesFromChunkMarkdownFence:
    """Markdown fence stripping works."""

    @pytest.mark.asyncio
    async def test_markdown_fence_stripped(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        fenced = '```json\n{"names": ["Alice Smith"]}\n```'
        response = _make_openai_response(fenced)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Alice Smith is a person.")

        assert names == ["Alice Smith"]

    @pytest.mark.asyncio
    async def test_markdown_fence_without_json_label(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        fenced = '```\n{"names": ["Bob Jones"]}\n```'
        response = _make_openai_response(fenced)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Bob Jones is a person.")

        assert names == ["Bob Jones"]


class TestExtractNamesFromChunkResponseFormats:
    """Handles both {"names": [...]} and bare array response formats."""

    @pytest.mark.asyncio
    async def test_dict_with_names_key(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps({"names": ["Person A"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Person A text.")

        assert names == ["Person A"]

    @pytest.mark.asyncio
    async def test_bare_array(self):
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps(["Person X", "Person Y"]))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Person X and Person Y.")

        assert names == ["Person X", "Person Y"]

    @pytest.mark.asyncio
    async def test_dict_with_non_standard_key(self):
        """A dict with a non-'names' key that has an array value should still work."""
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps({"people": ["Person Z"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Person Z text.")

        assert names == ["Person Z"]

    @pytest.mark.asyncio
    async def test_unexpected_type_returns_empty(self):
        """A JSON response that is neither a list nor a dict returns empty."""
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps("just a string"))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Some text.")

        assert names == []

    @pytest.mark.asyncio
    async def test_whitespace_only_names_filtered(self):
        """Names that are only whitespace are filtered out."""
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps({"names": ["Alice", "  ", "", "Bob"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Alice and Bob.")

        assert names == ["Alice", "Bob"]

    @pytest.mark.asyncio
    async def test_non_string_entries_filtered(self):
        """Non-string entries in the names array are filtered out."""
        from app.agent.batch_resolver import _extract_names_from_chunk

        response = _make_openai_response(json.dumps({"names": ["Alice", 42, None, "Bob"]}))
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("app.agent.batch_resolver.get_openai_client", return_value=mock_client):
            names = await _extract_names_from_chunk("Alice and Bob.")

        assert names == ["Alice", "Bob"]

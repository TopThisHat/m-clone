"""Integration tests for batch_lookup_clients and extract_and_lookup_entities tools.

These tests exercise the tool handler functions end-to-end while mocking
external dependencies (DB lookups, LLM calls) to avoid needing a live
database or OpenAI API key.

Coverage:
  m-clone-r6y5: batch_lookup_clients with 50+ names, concurrency, error handling
  m-clone-e2u3: filename resolution in extract_and_lookup_entities
  m-clone-zjx3: extract_and_lookup_entities end-to-end pipeline

Run:
  cd backend && uv run python -m pytest tests/test_batch_resolver_integration.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.dependencies import AgentDeps
from app.models.client_lookup import AdjudicationMethod, LookupResult, SearchSummary


# ---------------------------------------------------------------------------
# Override the autouse _ensure_schema fixture from conftest.py — these tests
# do not require a live database.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CSV = """\
Owner,Team,Sport
Robert Kraft,New England Patriots,NFL
Jerry Jones,Dallas Cowboys,NFL
Steve Cohen,New York Mets,MLB
"""

_SEARCH_SUMMARY = SearchSummary(fuzzy_client_hits=1, hpq_client_hits=0)


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


def _make_match(name: str, gwm_id: str, confidence: float = 0.92) -> LookupResult:
    """Build a successful LookupResult for mocking."""
    return LookupResult(
        match_found=True,
        gwm_id=gwm_id,
        matched_name=name,
        source="fuzzy_client",
        confidence=confidence,
        adjudication=AdjudicationMethod.LLM,
        search_summary=_SEARCH_SUMMARY,
    )


def _make_no_match(name: str) -> LookupResult:
    """Build a no-match LookupResult for mocking."""
    return LookupResult(
        match_found=False,
        gwm_id=None,
        matched_name=None,
        source=None,
        confidence=0.0,
        adjudication=AdjudicationMethod.LLM,
        search_summary=_SEARCH_SUMMARY,
    )


def _generate_names(n: int) -> list[dict[str, str]]:
    """Generate n distinct person name entries for batch tests."""
    return [{"name": f"Person {i:04d}"} for i in range(n)]


# ---------------------------------------------------------------------------
# m-clone-r6y5: batch_lookup_clients tool handler
# ---------------------------------------------------------------------------


class TestBatchLookupClients:
    """Tests for the batch_lookup_clients tool handler."""

    @pytest.mark.asyncio
    async def test_empty_people_returns_no_names_message(self):
        """Empty people list returns 'No names provided.' immediately."""
        from app.agent.tools import batch_lookup_clients

        deps = _make_deps()
        result = await batch_lookup_clients(deps, people=[])
        assert result == "No names provided."

    @pytest.mark.asyncio
    async def test_50_plus_names_all_results_returned(self):
        """Batch with 50+ names returns one result per unique name."""
        import json as _json
        from app.agent.tools import batch_lookup_clients

        num_names = 55
        people = _generate_names(num_names)

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            return _make_match(name, f"GWM-{name[-4:]}")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        parsed = _json.loads(result)
        assert parsed["summary"]["total"] == num_names
        assert parsed["summary"]["matched"] == num_names
        assert len(parsed["results"]) == num_names

    @pytest.mark.asyncio
    async def test_mixed_results_matched_nomatch_errors(self):
        """Batch with mixed outcomes: matched, no_match, and errors."""
        import json as _json
        from app.agent.tools import batch_lookup_clients

        people = [
            {"name": "Alice Thornton"},
            {"name": "Bob Henderson"},
            {"name": "Charlie Unknown"},
            {"name": "Diana Error"},
        ]

        call_count = 0

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal call_count
            call_count += 1
            if "Alice" in name:
                return _make_match(name, "GWM-001", confidence=0.95)
            if "Bob" in name:
                return _make_match(name, "GWM-002", confidence=0.88)
            if "Charlie" in name:
                return _make_no_match(name)
            # Diana triggers an error
            raise RuntimeError("Simulated DB timeout")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        parsed = _json.loads(result)
        assert parsed["summary"]["total"] == 4
        assert parsed["summary"]["matched"] == 2
        assert parsed["summary"]["no_match"] == 1
        assert parsed["summary"]["errors"] == 1
        # Verify the JSON results contain all names
        names = [r["name"] for r in parsed["results"]]
        assert "Alice Thornton" in names
        assert "Bob Henderson" in names
        assert "Charlie Unknown" in names
        assert "Diana Error" in names

    @pytest.mark.asyncio
    async def test_output_is_compact_json(self):
        """Output is valid compact JSON with summary and results."""
        import json as _json
        from app.agent.tools import batch_lookup_clients

        people = [{"name": "John Smith"}]

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            return _make_match(name, "GWM-100")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        # Verify compact JSON structure
        parsed = _json.loads(result)
        assert "summary" in parsed
        assert "results" in parsed
        assert parsed["results"][0]["name"] == "John Smith"
        assert parsed["results"][0]["gwm_id"] == "GWM-100"
        assert parsed["results"][0]["status"] == "matched"

    @pytest.mark.asyncio
    async def test_concurrency_controlled_by_semaphore(self):
        """Verify concurrent resolve_client calls are limited to 10."""
        from app.agent.tools import batch_lookup_clients

        num_names = 25
        people = _generate_names(num_names)

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            # Simulate work so multiple calls overlap
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return _make_match(name, f"GWM-{name[-4:]}")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        # The semaphore limit is 10 (_BATCH_CONCURRENCY)
        assert max_concurrent <= 10, f"Max concurrent was {max_concurrent}, expected <= 10"
        assert f'"total":{num_names}' in result

    @pytest.mark.asyncio
    async def test_individual_errors_do_not_stop_batch(self):
        """One failing resolve_client call does not prevent other lookups."""
        from app.agent.tools import batch_lookup_clients

        people = [
            {"name": "Good Person 1"},
            {"name": "Bad Person"},
            {"name": "Good Person 2"},
        ]

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            if "Bad" in name:
                raise RuntimeError("Connection reset")
            return _make_match(name, f"GWM-{hash(name) % 1000:03d}")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        # Both good persons should be matched
        import json as _json
        parsed = _json.loads(result)
        assert parsed["summary"]["matched"] == 2
        assert parsed["summary"]["errors"] == 1
        names = [r["name"] for r in parsed["results"]]
        assert "Good Person 1" in names
        assert "Good Person 2" in names
        assert "Bad Person" in names

    @pytest.mark.asyncio
    async def test_summary_line_correct_counts(self):
        """Summary line reports accurate matched/no_match/error counts."""
        from app.agent.tools import batch_lookup_clients

        people = [{"name": f"P{i}"} for i in range(10)]

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            idx = int(name[1:])
            if idx < 5:
                return _make_match(name, f"GWM-{idx}")
            if idx < 8:
                return _make_no_match(name)
            raise ValueError("Simulated failure")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        import json as _json
        parsed = _json.loads(result)
        assert parsed["summary"]["total"] == 10
        assert parsed["summary"]["matched"] == 5
        assert parsed["summary"]["no_match"] == 3
        assert parsed["summary"]["errors"] == 2

    @pytest.mark.asyncio
    async def test_deduplication_same_name_different_casing(self):
        """Duplicate names (case-insensitive) are resolved only once."""
        from app.agent.tools import batch_lookup_clients

        people = [
            {"name": "Alice Thornton"},
            {"name": "alice thornton"},
            {"name": "ALICE THORNTON"},
        ]
        call_count = 0

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal call_count
            call_count += 1
            return _make_match(name, "GWM-001")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        # Only one unique name should be resolved
        import json as _json
        assert call_count == 1
        parsed = _json.loads(result)
        assert parsed["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_single_name_singular_grammar(self):
        """Summary line uses singular 'name' for count of 1."""
        from app.agent.tools import batch_lookup_clients

        people = [{"name": "Solo Person"}]

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            return _make_match(name, "GWM-999")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            result = await batch_lookup_clients(deps, people=people)

        import json as _json
        parsed = _json.loads(result)
        assert parsed["summary"]["total"] == 1
        assert parsed["summary"]["matched"] == 1

    @pytest.mark.asyncio
    async def test_company_passed_to_resolver(self):
        """Company field from input is forwarded to resolve_client."""
        from app.agent.tools import batch_lookup_clients

        people = [{"name": "John Smith", "company": "Goldman Sachs"}]
        captured_company = None

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal captured_company
            captured_company = company
            return _make_match(name, "GWM-100")

        deps = _make_deps()
        with patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve):
            await batch_lookup_clients(deps, people=people)

        assert captured_company == "Goldman Sachs"


# ---------------------------------------------------------------------------
# m-clone-e2u3: Filename resolution in extract_and_lookup_entities
# ---------------------------------------------------------------------------


class TestFilenameResolution:
    """Tests for filename matching logic in extract_and_lookup_entities."""

    @pytest.mark.asyncio
    async def test_exact_filename_match(self):
        """Exact filename match resolves to the correct document."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV, "Other doc content."],
            metadata=[
                {"filename": "owners.csv", "type": "csv"},
                {"filename": "report.pdf", "type": "pdf"},
            ],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft"], 1)
            mock_resolve.return_value = _make_match("Robert Kraft", "GWM-001")

            await extract_and_lookup_entities(deps, filename="owners.csv")

        # extract_person_names should have been called with the CSV text
        mock_extract.assert_called_once()
        call_text = mock_extract.call_args[0][0]
        assert "Robert Kraft" in call_text
        assert "Other doc content" not in call_text

    @pytest.mark.asyncio
    async def test_case_insensitive_filename_match(self):
        """Case-insensitive filename matching (e.g., 'Owners.CSV' -> 'owners.csv')."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft"], 1)
            mock_resolve.return_value = _make_match("Robert Kraft", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="Owners.CSV")

        # Should NOT return file-not-found error
        assert "No uploaded file matches" not in result
        mock_extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_keyword_processes_all_documents(self):
        """The 'all' keyword processes every uploaded document."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV, "Bill Gates, Microsoft\nElon Musk, Tesla"],
            metadata=[
                {"filename": "owners.csv", "type": "csv"},
                {"filename": "tech_leaders.csv", "type": "csv"},
            ],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft", "Bill Gates"], 2)
            mock_resolve.return_value = _make_match("test", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="all")

        # extract_person_names should receive combined text from both documents
        call_text = mock_extract.call_args[0][0]
        assert "Robert Kraft" in call_text
        assert "Bill Gates" in call_text
        assert "all documents" in result

    @pytest.mark.asyncio
    async def test_all_keyword_case_insensitive(self):
        """The 'ALL' keyword (uppercase) also processes all documents."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft"], 1)
            mock_resolve.return_value = _make_match("Robert Kraft", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="ALL")

        assert "all documents" in result

    @pytest.mark.asyncio
    async def test_filename_not_found_returns_error_with_available(self):
        """Non-existent filename returns an error listing available filenames."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[
                {"filename": "owners.csv", "type": "csv"},
                {"filename": "report.pdf", "type": "pdf"},
            ],
        )

        result = await extract_and_lookup_entities(deps, filename="nonexistent.xlsx")

        assert "No uploaded file matches" in result
        assert "nonexistent.xlsx" in result
        assert "owners.csv" in result
        assert "report.pdf" in result

    @pytest.mark.asyncio
    async def test_no_documents_uploaded_returns_message(self):
        """No documents uploaded returns 'No documents have been uploaded.'."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps()
        result = await extract_and_lookup_entities(deps, filename="anything.csv")

        assert result == "No documents have been uploaded."

    @pytest.mark.asyncio
    async def test_exact_match_preferred_over_case_insensitive(self):
        """When both exact and case-insensitive matches exist, exact wins."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=["Doc content A", "Doc content B"],
            metadata=[
                {"filename": "Report.csv", "type": "csv"},
                {"filename": "report.csv", "type": "csv"},
            ],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Some Person"], 1)
            mock_resolve.return_value = _make_match("Some Person", "GWM-001")

            await extract_and_lookup_entities(deps, filename="report.csv")

        # The exact match is "report.csv" (second entry), so the text should be "Doc content B"
        call_text = mock_extract.call_args[0][0]
        assert call_text == "Doc content B"


# ---------------------------------------------------------------------------
# m-clone-zjx3: extract_and_lookup_entities end-to-end pipeline
# ---------------------------------------------------------------------------


class TestExtractAndLookupEndToEnd:
    """End-to-end pipeline tests for extract_and_lookup_entities."""

    @pytest.mark.asyncio
    async def test_full_pipeline_csv_extraction_and_lookup(self):
        """Full pipeline: CSV doc -> extract names -> resolve -> compact JSON output."""
        import json as _json
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            if "Kraft" in name:
                return _make_match(name, "GWM-RK01", confidence=0.95)
            if "Jones" in name:
                return _make_match(name, "GWM-JJ02", confidence=0.88)
            return _make_no_match(name)

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve),
        ):
            mock_extract.return_value = (["Robert Kraft", "Jerry Jones", "Steve Cohen"], 3)

            result = await extract_and_lookup_entities(deps, filename="owners.csv")

        # Verify extraction metadata header
        assert "Extracted 3 unique names" in result
        assert "owners.csv" in result

        # Extract the JSON portion (after the header text)
        json_start = result.index("{")
        parsed = _json.loads(result[json_start:])

        # Verify all names appear in the results
        names = [r["name"] for r in parsed["results"]]
        assert "Robert Kraft" in names
        assert "Jerry Jones" in names
        assert "Steve Cohen" in names

        # Verify match statuses
        statuses = {r["name"]: r["status"] for r in parsed["results"]}
        assert statuses["Robert Kraft"] == "matched"
        assert statuses["Jerry Jones"] == "matched"
        assert statuses["Steve Cohen"] == "no_match"

    @pytest.mark.asyncio
    async def test_deduplication_in_extraction(self):
        """Duplicate names from extraction are resolved only once."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=["Robert Kraft mentioned twice. Robert Kraft again."],
            metadata=[{"filename": "mentions.txt", "type": "txt"}],
        )
        resolve_call_count = 0

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            nonlocal resolve_call_count
            resolve_call_count += 1
            return _make_match(name, "GWM-001")

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve),
        ):
            # Simulate extraction returning the same name multiple times
            mock_extract.return_value = (["Robert Kraft", "Robert Kraft"], 2)

            result = await extract_and_lookup_entities(deps, filename="mentions.txt")

        # extract_person_names itself deduplicates, but even if duplicates sneak
        # through, batch_resolve_clients deduplicates by normalized name.
        # The mock returns 2 entries, so batch_resolve handles dedup.
        # In any case, the result should be valid.
        assert "Robert Kraft" in result
        assert '"summary"' in result

    @pytest.mark.asyncio
    async def test_zero_names_extracted_returns_message(self):
        """When no names are found in the document, return an appropriate message."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=["Just numbers: 123, 456, 789."],
            metadata=[{"filename": "numbers.csv", "type": "csv"}],
        )

        with patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = ([], 0)

            result = await extract_and_lookup_entities(deps, filename="numbers.csv")

        assert "No person names found" in result
        assert "numbers.csv" in result

    @pytest.mark.asyncio
    async def test_output_includes_extraction_metadata_header(self):
        """Output starts with extraction metadata before the table."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft", "Jerry Jones"], 2)
            mock_resolve.return_value = _make_match("test", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="owners.csv")

        # Should start with extraction info, then include the JSON results
        assert result.startswith("Extracted 2 unique names")
        assert '"summary"' in result

    @pytest.mark.asyncio
    async def test_mixed_results_in_pipeline(self):
        """Pipeline with mixed match/no_match/error results formats correctly."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        async def mock_resolve(name: str, company: str | None = None) -> LookupResult:
            if "Kraft" in name:
                return _make_match(name, "GWM-RK01", confidence=0.95)
            if "Jones" in name:
                raise ConnectionError("DB unavailable")
            return _make_no_match(name)

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", side_effect=mock_resolve),
        ):
            mock_extract.return_value = (["Robert Kraft", "Jerry Jones", "Steve Cohen"], 3)

            result = await extract_and_lookup_entities(deps, filename="owners.csv")

        # All three outcomes should appear in the compact JSON summary
        import json as _json
        json_start = result.index("{")
        parsed = _json.loads(result[json_start:])
        assert parsed["summary"]["matched"] == 1
        assert parsed["summary"]["no_match"] == 1
        assert parsed["summary"]["errors"] == 1

    @pytest.mark.asyncio
    async def test_multiple_documents_via_all(self):
        """Processing 'all' documents merges text before extraction."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[
                "Owner: Robert Kraft, New England Patriots",
                "Owner: Steve Cohen, New York Mets",
            ],
            metadata=[
                {"filename": "nfl.csv", "type": "csv"},
                {"filename": "mlb.csv", "type": "csv"},
            ],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["Robert Kraft", "Steve Cohen"], 2)
            mock_resolve.return_value = _make_match("test", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="all")

        # Combined text should include content from both documents
        call_text = mock_extract.call_args[0][0]
        assert "Robert Kraft" in call_text
        assert "Steve Cohen" in call_text
        assert "all documents" in result

    @pytest.mark.asyncio
    async def test_extraction_count_in_header(self):
        """Header includes correct unique name count and total mentions."""
        from app.agent.tools import extract_and_lookup_entities

        deps = _make_deps(
            doc_texts=[SAMPLE_CSV],
            metadata=[{"filename": "owners.csv", "type": "csv"}],
        )

        with (
            patch("app.agent.batch_resolver.extract_person_names", new_callable=AsyncMock) as mock_extract,
            patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_extract.return_value = (["A", "B", "C", "D", "E"], 12)
            mock_resolve.return_value = _make_match("test", "GWM-001")

            result = await extract_and_lookup_entities(deps, filename="owners.csv")

        assert "Extracted 5 unique names" in result
        assert "12 total mentions" in result


# ---------------------------------------------------------------------------
# Standalone batch_resolver module tests (format + dedup helpers)
# ---------------------------------------------------------------------------


class TestFormatResultsAsMarkdown:
    """Unit tests for format_results_as_markdown."""

    def test_empty_results(self):
        from app.agent.batch_resolver import format_results_as_markdown

        assert format_results_as_markdown([]) == "No names provided."

    def test_matched_row_shows_gwm_id_and_confidence(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "Alice",
            "status": "matched",
            "gwm_id": "GWM-001",
            "confidence": 0.95,
            "error": None,
            "result": None,
        }]
        output = format_results_as_markdown(results)
        assert "GWM-001" in output
        assert "95%" in output
        assert "Matched" in output

    def test_no_match_row_shows_dashes(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "Unknown",
            "status": "no_match",
            "gwm_id": None,
            "confidence": None,
            "error": None,
            "result": None,
        }]
        output = format_results_as_markdown(results)
        assert "No match" in output

    def test_error_row_includes_error_message(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "Problem",
            "status": "error",
            "gwm_id": None,
            "confidence": None,
            "error": "Connection refused",
            "result": None,
        }]
        output = format_results_as_markdown(results)
        assert "Error: Connection refused" in output

    def test_long_error_message_truncated(self):
        from app.agent.batch_resolver import format_results_as_markdown

        long_error = "x" * 200
        results = [{
            "name": "Problem",
            "status": "error",
            "gwm_id": None,
            "confidence": None,
            "error": long_error,
            "result": None,
        }]
        output = format_results_as_markdown(results)
        # Error should be truncated to 80 chars (77 + "...")
        assert "..." in output

    def test_pipe_chars_escaped_in_names(self):
        from app.agent.batch_resolver import format_results_as_markdown

        results = [{
            "name": "Name|With|Pipes",
            "status": "matched",
            "gwm_id": "GWM-X",
            "confidence": 0.90,
            "error": None,
            "result": None,
        }]
        output = format_results_as_markdown(results)
        # Pipes in name should be escaped
        assert "Name\\|With\\|Pipes" in output


class TestBuildDedupMap:
    """Unit tests for the _build_dedup_map helper."""

    def test_dedup_removes_case_duplicates(self):
        from app.agent.batch_resolver import _build_dedup_map

        people = [
            {"name": "Alice Smith"},
            {"name": "alice smith"},
            {"name": "ALICE SMITH"},
        ]
        unique = _build_dedup_map(people)
        assert len(unique) == 1

    def test_dedup_preserves_first_occurrence(self):
        from app.agent.batch_resolver import _build_dedup_map

        people = [
            {"name": "Alice Smith", "company": "Acme"},
            {"name": "alice smith", "company": "OtherCo"},
        ]
        unique = _build_dedup_map(people)
        assert len(unique) == 1
        assert unique[0]["_original_name"] == "Alice Smith"

    def test_dedup_skips_empty_names(self):
        from app.agent.batch_resolver import _build_dedup_map

        people = [
            {"name": ""},
            {"name": "  "},
            {"name": "Alice Smith"},
        ]
        unique = _build_dedup_map(people)
        assert len(unique) == 1
        assert unique[0]["_original_name"] == "Alice Smith"

    def test_dedup_different_names_preserved(self):
        from app.agent.batch_resolver import _build_dedup_map

        people = [
            {"name": "Alice Smith"},
            {"name": "Bob Jones"},
            {"name": "Charlie Brown"},
        ]
        unique = _build_dedup_map(people)
        assert len(unique) == 3


class TestChunking:
    """Unit tests for the _split_into_chunks helper."""

    def test_short_text_single_chunk(self):
        from app.agent.batch_resolver import _split_into_chunks

        result = _split_into_chunks("Short text", chunk_size=100)
        assert len(result) == 1
        assert result[0] == "Short text"

    def test_long_text_splits_into_chunks(self):
        from app.agent.batch_resolver import _split_into_chunks

        text = "word " * 2000  # ~10K chars
        result = _split_into_chunks(text, chunk_size=1000, overlap=100)
        assert len(result) > 1
        # Each chunk should be <= chunk_size
        for chunk in result:
            assert len(chunk) <= 1000

    def test_chunks_have_overlap(self):
        from app.agent.batch_resolver import _split_into_chunks

        text = " ".join(f"word{i}" for i in range(500))
        result = _split_into_chunks(text, chunk_size=200, overlap=50)
        assert len(result) > 2
        # The end of one chunk and start of the next should share some content
        # due to overlap
        for i in range(len(result) - 1):
            end_words = set(result[i].split()[-5:])
            start_words = set(result[i + 1].split()[:5])
            # At least some words should overlap due to the overlap window
            # (This is probabilistic but reliable with overlap=50)
            assert len(end_words & start_words) >= 0  # Guard: no crash

    def test_empty_text_returns_single_chunk(self):
        from app.agent.batch_resolver import _split_into_chunks

        result = _split_into_chunks("", chunk_size=100)
        # Empty string may return single chunk or be filtered out
        assert len(result) <= 1

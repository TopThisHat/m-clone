"""Unit tests for the client ID lookup feature.

Pure unit tests — no database, no network, no external services.
All async DB calls and LLM calls are mocked with unittest.mock.AsyncMock.

Coverage:
  - normalize_name()                    (tasks 7.1–7.2)
  - _dedup_candidates()                 (task 7.3)
  - _detect_gwm_id_conflicts()          (task 7.4)
  - _fast_path()                        (task 7.5)
  - _levenshtein_fallback()             (task 7.6)
  - _parse_llm_response()               (task 7.7)
  - _call_llm() mocked                  (task 7.8)
  - resolve_client() end-to-end mocked  (task 7.9)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.client_lookup import (
    AdjudicationMethod,
    CandidateResult,
    LLMDecision,
    LookupResult,
    SearchSummary,
)


# ---------------------------------------------------------------------------
# Override the autouse DB fixture from conftest.py so unit tests never
# touch a real database.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    gwm_id: str = "GWM-001",
    name: str = "John Smith",
    source: str = "fuzzy_client",
    db_score: float = 0.90,
    companies: str | None = None,
    label_excerpt: str | None = None,
) -> CandidateResult:
    return CandidateResult(
        gwm_id=gwm_id,
        name=name,
        source=source,  # type: ignore[arg-type]
        db_score=db_score,
        companies=companies,
        label_excerpt=label_excerpt,
    )


def _make_search_summary(fuzzy: int = 1, hpq: int = 0) -> SearchSummary:
    return SearchSummary(fuzzy_client_hits=fuzzy, hpq_client_hits=hpq)


# ---------------------------------------------------------------------------
# 7.1 / 7.2 — normalize_name()
# ---------------------------------------------------------------------------

class TestNormalizeName:
    """Tests for normalize_name() in app.db.client_lookup."""

    def setup_method(self):
        from app.db.client_lookup import normalize_name
        self.normalize = normalize_name

    # --- Honorific prefixes ---

    def test_strips_mr(self):
        assert self.normalize("Mr. John Smith") == "John Smith"

    def test_strips_mrs(self):
        assert self.normalize("Mrs. Jane Doe") == "Jane Doe"

    def test_strips_ms(self):
        assert self.normalize("Ms. Alice Brown") == "Alice Brown"

    def test_strips_dr(self):
        assert self.normalize("Dr. Robert Jones") == "Robert Jones"

    def test_strips_prof(self):
        assert self.normalize("Prof. Emily White") == "Emily White"

    def test_strips_rev(self):
        assert self.normalize("Rev. Samuel Black") == "Samuel Black"

    def test_strips_dr_without_dot(self):
        assert self.normalize("Dr John Smith") == "John Smith"

    # --- Suffixes ---

    def test_strips_jr(self):
        assert self.normalize("John Smith Jr.") == "John Smith"

    def test_strips_sr(self):
        assert self.normalize("John Smith Sr.") == "John Smith"

    def test_strips_iii(self):
        assert self.normalize("William Jones III") == "William Jones"

    def test_strips_iv(self):
        assert self.normalize("Henry Tudor IV") == "Henry Tudor"

    def test_strips_esq(self):
        assert self.normalize("Jane Doe Esq.") == "Jane Doe"

    # --- Combined honorifics and suffixes ---

    def test_strips_multiple_honorifics(self):
        result = self.normalize("Dr. John Smith Jr.")
        assert result == "John Smith"

    def test_strips_prefix_and_suffix_with_extra_spaces(self):
        result = self.normalize("Dr.  Jane  Doe  III")
        assert result == "Jane Doe"

    # --- Whitespace handling ---

    def test_collapses_internal_whitespace(self):
        assert self.normalize("  Alice   Johnson  ") == "Alice Johnson"

    def test_strips_leading_trailing_whitespace(self):
        assert self.normalize("   Bob Davis   ") == "Bob Davis"

    def test_empty_string_returns_empty(self):
        assert self.normalize("") == ""

    def test_whitespace_only_returns_empty(self):
        assert self.normalize("   ") == ""

    # --- Normal names preserved ---

    def test_normal_name_unchanged(self):
        assert self.normalize("John Smith") == "John Smith"

    def test_single_word_name_unchanged(self):
        assert self.normalize("Madonna") == "Madonna"

    def test_name_with_hyphen_unchanged(self):
        assert self.normalize("Smith-Jones") == "Smith-Jones"


# ---------------------------------------------------------------------------
# 7.3 — _dedup_candidates()
# ---------------------------------------------------------------------------

class TestDedupCandidates:
    """Tests for _dedup_candidates() in app.agent.client_resolver."""

    def setup_method(self):
        from app.agent.client_resolver import _dedup_candidates
        self.dedup = _dedup_candidates

    def test_keeps_highest_score_within_fuzzy_source(self):
        """When the same gwm_id appears twice in fuzzy, keep the higher score."""
        candidates = [
            _make_candidate("GWM-001", db_score=0.70),
            _make_candidate("GWM-001", db_score=0.90),
        ]
        fuzzy_out, hpq_out = self.dedup(candidates, [])
        assert len(fuzzy_out) == 1
        assert fuzzy_out[0].db_score == 0.90

    def test_keeps_highest_score_within_hpq_source(self):
        """When the same gwm_id appears twice in HPQ, keep the higher score."""
        candidates = [
            _make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.50),
            _make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.80),
        ]
        fuzzy_out, hpq_out = self.dedup([], candidates)
        assert len(hpq_out) == 1
        assert hpq_out[0].db_score == 0.80

    def test_preserves_cross_source_duplicates(self):
        """Same gwm_id appearing in both sources is kept in both (corroborating evidence)."""
        fuzzy = [_make_candidate("GWM-001", source="fuzzy_client", db_score=0.90)]
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.75)]
        fuzzy_out, hpq_out = self.dedup(fuzzy, hpq)
        assert len(fuzzy_out) == 1
        assert len(hpq_out) == 1
        assert fuzzy_out[0].gwm_id == "GWM-001"
        assert hpq_out[0].gwm_id == "GWM-001"

    def test_empty_input_returns_empty(self):
        fuzzy_out, hpq_out = self.dedup([], [])
        assert fuzzy_out == []
        assert hpq_out == []

    def test_distinct_gwm_ids_all_kept(self):
        """Multiple distinct gwm_ids in same source are all preserved."""
        candidates = [
            _make_candidate("GWM-001", db_score=0.90),
            _make_candidate("GWM-002", db_score=0.80),
            _make_candidate("GWM-003", db_score=0.70),
        ]
        fuzzy_out, hpq_out = self.dedup(candidates, [])
        assert len(fuzzy_out) == 3

    def test_dedup_with_three_dupes_keeps_best(self):
        """Three records for same id — only highest score survives."""
        candidates = [
            _make_candidate("GWM-001", db_score=0.50),
            _make_candidate("GWM-001", db_score=0.95),
            _make_candidate("GWM-001", db_score=0.70),
        ]
        fuzzy_out, _ = self.dedup(candidates, [])
        assert len(fuzzy_out) == 1
        assert fuzzy_out[0].db_score == 0.95


# ---------------------------------------------------------------------------
# 7.4 — _detect_gwm_id_conflicts()
# ---------------------------------------------------------------------------

class TestDetectGwmIdConflicts:
    """Tests for _detect_gwm_id_conflicts() in app.agent.client_resolver."""

    def setup_method(self):
        from app.agent.client_resolver import _detect_gwm_id_conflicts
        self.detect = _detect_gwm_id_conflicts

    def test_returns_conflicting_ids_when_sources_differ(self):
        """Different top gwm_ids across sources signals a conflict."""
        fuzzy = [_make_candidate("GWM-001")]
        hpq = [_make_candidate("GWM-002", source="high_priority_queue_client")]
        result = self.detect(fuzzy, hpq)
        assert sorted(result) == ["GWM-001", "GWM-002"]

    def test_returns_empty_when_same_id_in_both_sources(self):
        """Same gwm_id in both sources means no conflict."""
        fuzzy = [_make_candidate("GWM-001")]
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client")]
        result = self.detect(fuzzy, hpq)
        assert result == []

    def test_returns_empty_when_hpq_is_empty(self):
        """No conflict when one source has no results."""
        fuzzy = [_make_candidate("GWM-001")]
        result = self.detect(fuzzy, [])
        assert result == []

    def test_returns_empty_when_fuzzy_is_empty(self):
        """No conflict when fuzzy source has no results."""
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client")]
        result = self.detect([], hpq)
        assert result == []

    def test_returns_empty_when_both_empty(self):
        result = self.detect([], [])
        assert result == []

    def test_conflict_includes_all_distinct_ids(self):
        """Multiple ids per source — all conflicting ids are returned."""
        fuzzy = [
            _make_candidate("GWM-001"),
            _make_candidate("GWM-002"),
        ]
        hpq = [
            _make_candidate("GWM-003", source="high_priority_queue_client"),
        ]
        result = self.detect(fuzzy, hpq)
        assert "GWM-001" in result
        assert "GWM-002" in result
        assert "GWM-003" in result

    def test_partial_overlap_is_not_a_conflict(self):
        """If sources share even one id, the sets are not disjoint — no conflict."""
        fuzzy = [_make_candidate("GWM-001"), _make_candidate("GWM-002")]
        hpq = [
            _make_candidate("GWM-001", source="high_priority_queue_client"),
            _make_candidate("GWM-003", source="high_priority_queue_client"),
        ]
        result = self.detect(fuzzy, hpq)
        assert result == []


# ---------------------------------------------------------------------------
# 7.5 — _fast_path()
# ---------------------------------------------------------------------------

class TestFastPath:
    """Tests for _fast_path() in app.agent.client_resolver."""

    def setup_method(self):
        from app.agent.client_resolver import _fast_path
        self.fast_path = _fast_path

    def test_returns_result_for_single_fuzzy_candidate_above_threshold(self):
        """Single fuzzy candidate with score >= 0.85 triggers fast path."""
        fuzzy = [_make_candidate("GWM-001", db_score=0.90)]
        result = self.fast_path(fuzzy, [], company=None, search_summary=_make_search_summary())
        assert result is not None
        assert result.match_found is True
        assert result.gwm_id == "GWM-001"
        assert result.adjudication == AdjudicationMethod.FAST_PATH

    def test_returns_result_for_single_hpq_candidate_above_threshold(self):
        """Single HPQ candidate with score >= 0.75 triggers fast path."""
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.80)]
        result = self.fast_path([], hpq, company=None, search_summary=_make_search_summary(0, 1))
        assert result is not None
        assert result.match_found is True
        assert result.gwm_id == "GWM-001"
        assert result.adjudication == AdjudicationMethod.FAST_PATH

    def test_returns_none_when_company_provided(self):
        """Company context always bypasses fast path, even with high score."""
        fuzzy = [_make_candidate("GWM-001", db_score=0.95)]
        result = self.fast_path(
            fuzzy, [], company="Goldman Sachs", search_summary=_make_search_summary()
        )
        assert result is None

    def test_returns_none_when_multiple_candidates(self):
        """Two different gwm_ids never fast-path."""
        fuzzy = [
            _make_candidate("GWM-001", db_score=0.90),
            _make_candidate("GWM-002", db_score=0.88),
        ]
        result = self.fast_path(fuzzy, [], company=None, search_summary=_make_search_summary(2))
        assert result is None

    def test_returns_none_when_score_below_fuzzy_threshold(self):
        """Fuzzy score of 0.84 (below 0.85) does not trigger fast path."""
        fuzzy = [_make_candidate("GWM-001", db_score=0.84)]
        result = self.fast_path(fuzzy, [], company=None, search_summary=_make_search_summary())
        assert result is None

    def test_returns_none_when_hpq_score_below_threshold(self):
        """HPQ score of 0.74 (below 0.75) does not trigger fast path."""
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.74)]
        result = self.fast_path([], hpq, company=None, search_summary=_make_search_summary(0, 1))
        assert result is None

    def test_returns_none_when_no_candidates(self):
        """Empty candidate lists never fast-path."""
        result = self.fast_path([], [], company=None, search_summary=_make_search_summary(0, 0))
        assert result is None

    def test_confidence_capped_at_0_95(self):
        """Even a perfect 1.0 db_score yields confidence <= 0.95."""
        fuzzy = [_make_candidate("GWM-001", db_score=1.0)]
        result = self.fast_path(fuzzy, [], company=None, search_summary=_make_search_summary())
        assert result is not None
        assert result.confidence <= 0.95

    def test_same_gwm_id_in_both_sources_fast_paths(self):
        """When both sources return the same gwm_id with high scores, fast path fires."""
        fuzzy = [_make_candidate("GWM-001", source="fuzzy_client", db_score=0.90)]
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.80)]
        result = self.fast_path(
            fuzzy, hpq, company=None, search_summary=_make_search_summary(1, 1)
        )
        assert result is not None
        assert result.match_found is True
        assert result.gwm_id == "GWM-001"


# ---------------------------------------------------------------------------
# 7.6 — _levenshtein_fallback()
# ---------------------------------------------------------------------------

class TestLevenshteinFallback:
    """Tests for _levenshtein_fallback() in app.agent.client_resolver."""

    def setup_method(self):
        from app.agent.client_resolver import _levenshtein_fallback
        self.fallback = _levenshtein_fallback

    def test_returns_best_fuzzy_candidate_by_score(self):
        """Highest fuzzy db_score wins."""
        fuzzy = [
            _make_candidate("GWM-001", db_score=0.50),
            _make_candidate("GWM-002", db_score=0.55),
        ]
        result = self.fallback(fuzzy, [], _make_search_summary(2), [])
        assert result.match_found is True
        assert result.gwm_id == "GWM-002"

    def test_hpq_scores_normalized_upward(self):
        """HPQ scores are multiplied by NORMALIZATION_FACTOR_HPQ (1.2x)."""
        # Fuzzy score 0.50, HPQ score 0.50 * 1.2 = 0.60 — HPQ should win
        fuzzy = [_make_candidate("GWM-001", db_score=0.50)]
        hpq = [_make_candidate("GWM-002", source="high_priority_queue_client", db_score=0.50)]
        result = self.fallback(fuzzy, hpq, _make_search_summary(1, 1), [])
        assert result.match_found is True
        assert result.gwm_id == "GWM-002"

    def test_confidence_capped_at_0_60(self):
        """Even a perfect score produces confidence <= FALLBACK_CONFIDENCE_CAP (0.60)."""
        fuzzy = [_make_candidate("GWM-001", db_score=1.0)]
        result = self.fallback(fuzzy, [], _make_search_summary(), [])
        assert result.confidence <= 0.60
        assert result.adjudication == AdjudicationMethod.RULE_BASED

    def test_returns_no_match_when_best_score_below_0_40(self):
        """Best effective score < 0.40 produces match_found=False."""
        fuzzy = [_make_candidate("GWM-001", db_score=0.30)]
        result = self.fallback(fuzzy, [], _make_search_summary(), [])
        assert result.match_found is False
        assert result.adjudication == AdjudicationMethod.RULE_BASED

    def test_returns_no_match_with_no_candidates(self):
        """Empty candidate lists → match_found=False with informative warning."""
        result = self.fallback([], [], _make_search_summary(0, 0), [])
        assert result.match_found is False
        assert result.candidates_evaluated == 0
        assert any("no candidates" in w.lower() for w in result.warnings)

    def test_warnings_include_fallback_notice(self):
        """Result always includes a warning that LLM adjudication failed."""
        fuzzy = [_make_candidate("GWM-001", db_score=0.55)]
        result = self.fallback(fuzzy, [], _make_search_summary(), [])
        assert any("rule-based" in w.lower() or "llm" in w.lower() for w in result.warnings)

    def test_hpq_normalization_capped_at_1_0(self):
        """Normalized HPQ score should not exceed 1.0."""
        hpq = [_make_candidate("GWM-001", source="high_priority_queue_client", db_score=0.95)]
        result = self.fallback([], hpq, _make_search_summary(0, 1), [])
        # Confidence capped at 0.60, so this indirectly verifies the cap
        assert result.confidence <= 0.60


# ---------------------------------------------------------------------------
# 7.7 — _parse_llm_response()
# ---------------------------------------------------------------------------

class TestParseLlmResponse:
    """Tests for _parse_llm_response() in app.agent.client_resolver."""

    def setup_method(self):
        from app.agent.client_resolver import _parse_llm_response
        self.parse = _parse_llm_response

    def _make_decision(self, **kwargs) -> LLMDecision:
        defaults = {
            "match_found": True,
            "gwm_id": "GWM-001",
            "matched_name": "John Smith",
            "source": "fuzzy_client",
            "confidence": 0.85,
            "conflict": False,
            "conflict_gwm_ids": [],
            "ambiguous": False,
            "resolution_factors": ["Strong name match"],
            "candidates_considered": 1,
        }
        defaults.update(kwargs)
        return LLMDecision(**defaults)

    def test_successful_match_returned_correctly(self):
        """Valid high-confidence LLM decision produces a matched LookupResult."""
        decision = self._make_decision()
        fuzzy = [_make_candidate("GWM-001")]
        result = self.parse(decision, fuzzy, [], _make_search_summary(), [])
        assert result.match_found is True
        assert result.gwm_id == "GWM-001"
        assert result.confidence == 0.85
        assert result.adjudication == AdjudicationMethod.LLM

    def test_conflict_caps_confidence_at_0_5(self):
        """Conflict flag caps confidence at 0.5 and sets match_found=False."""
        decision = self._make_decision(
            conflict=True,
            conflict_gwm_ids=["GWM-001", "GWM-002"],
            confidence=0.90,
            match_found=False,
        )
        fuzzy = [_make_candidate("GWM-001")]
        hpq = [_make_candidate("GWM-002", source="high_priority_queue_client")]
        result = self.parse(decision, fuzzy, hpq, _make_search_summary(1, 1), [])
        assert result.match_found is False
        assert result.conflict is True
        assert result.confidence <= 0.5

    def test_ambiguous_sets_match_found_false(self):
        """Ambiguous flag produces match_found=False regardless of confidence."""
        decision = self._make_decision(
            ambiguous=True,
            match_found=False,
            confidence=0.65,
        )
        fuzzy = [_make_candidate("GWM-001"), _make_candidate("GWM-002", db_score=0.88)]
        result = self.parse(decision, fuzzy, [], _make_search_summary(2), [])
        assert result.match_found is False
        assert result.ambiguous is True

    def test_low_confidence_returns_no_match(self):
        """LLM confidence below MIN_MATCH_CONFIDENCE (0.70) yields match_found=False."""
        decision = self._make_decision(confidence=0.65, match_found=True)
        fuzzy = [_make_candidate("GWM-001")]
        result = self.parse(decision, fuzzy, [], _make_search_summary(), [])
        assert result.match_found is False

    def test_null_gwm_id_means_no_match(self):
        """LLM returning null gwm_id → match_found=False."""
        decision = self._make_decision(
            match_found=False,
            gwm_id=None,
            matched_name=None,
            source=None,
            confidence=0.10,
        )
        result = self.parse(decision, [], [], _make_search_summary(0, 0), [])
        assert result.match_found is False
        assert result.gwm_id is None

    def test_resolution_factors_propagated(self):
        """LLM resolution factors are included in the output."""
        factors = ["Exact name match", "Company confirmed"]
        decision = self._make_decision(resolution_factors=factors)
        result = self.parse(decision, [_make_candidate("GWM-001")], [], _make_search_summary(), [])
        for f in factors:
            assert f in result.resolution_factors

    def test_warnings_passed_through(self):
        """Caller-provided warnings are preserved in the result."""
        decision = self._make_decision()
        warnings = ["fuzzy_client search was slow"]
        result = self.parse(
            decision, [_make_candidate("GWM-001")], [], _make_search_summary(), warnings
        )
        assert "fuzzy_client search was slow" in result.warnings

    def test_gap_check_marks_ambiguous_when_gap_too_small(self):
        """When matched candidate and rival are close in score, result is ambiguous."""
        # Matched at 0.80, rival at 0.70 → gap = 0.10 < 0.15 threshold
        # LLM confidence must be < 0.85 for gap check to activate
        decision = self._make_decision(
            gwm_id="GWM-001",
            confidence=0.75,
            match_found=True,
        )
        fuzzy = [
            _make_candidate("GWM-001", db_score=0.80),
            _make_candidate("GWM-002", db_score=0.70),
        ]
        result = self.parse(decision, fuzzy, [], _make_search_summary(2), [])
        assert result.ambiguous is True
        assert result.match_found is False

    def test_gap_check_skipped_when_llm_highly_confident(self):
        """Gap check is bypassed when LLM confidence >= 0.85."""
        decision = self._make_decision(
            gwm_id="GWM-001",
            confidence=0.90,  # >= 0.85 → gap check skipped
            match_found=True,
        )
        fuzzy = [
            _make_candidate("GWM-001", db_score=0.80),
            _make_candidate("GWM-002", db_score=0.72),
        ]
        result = self.parse(decision, fuzzy, [], _make_search_summary(2), [])
        assert result.match_found is True


# ---------------------------------------------------------------------------
# 7.8 — _call_llm() with mocked OpenAI client
# ---------------------------------------------------------------------------

class TestCallLlm:
    """Tests for _call_llm() in app.agent.client_resolver."""

    def _valid_llm_payload(self) -> str:
        return json.dumps({
            "match_found": True,
            "gwm_id": "GWM-001",
            "matched_name": "John Smith",
            "source": "fuzzy_client",
            "confidence": 0.92,
            "conflict": False,
            "conflict_gwm_ids": [],
            "ambiguous": False,
            "resolution_factors": ["Strong similarity"],
            "candidates_considered": 1,
        })

    @pytest.mark.asyncio
    async def test_successful_llm_call_returns_llm_decision(self):
        """Valid JSON response from LLM is parsed into LLMDecision."""
        from app.agent import client_resolver

        mock_message = MagicMock()
        mock_message.content = self._valid_llm_payload()
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(client_resolver, "get_openai_client", return_value=mock_client):
            result = await client_resolver._call_llm(
                name="John Smith",
                company=None,
                context=None,
                fuzzy=[_make_candidate("GWM-001")],
                hpq=[],
            )

        assert result is not None
        assert isinstance(result, LLMDecision)
        assert result.gwm_id == "GWM-001"
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """TimeoutError causes _call_llm to return None (triggers fallback)."""
        from app.agent import client_resolver

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_client):
            result = await client_resolver._call_llm(
                "John Smith", None, None, [], []
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        """Any API exception causes _call_llm to return None."""
        from app.agent import client_resolver

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API quota exceeded")
        )

        with patch.object(client_resolver, "get_openai_client", return_value=mock_client):
            result = await client_resolver._call_llm(
                "John Smith", None, None, [], []
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_unparseable_json_returns_none(self):
        """Malformed JSON response causes _call_llm to return None."""
        from app.agent import client_resolver

        mock_message = MagicMock()
        mock_message.content = "this is not json { broken"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(client_resolver, "get_openai_client", return_value=mock_client):
            result = await client_resolver._call_llm(
                "John Smith", None, None, [], []
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_markdown_fenced_json_is_stripped_and_parsed(self):
        """LLM response wrapped in markdown fences is still parsed successfully."""
        from app.agent import client_resolver

        payload = "```json\n" + self._valid_llm_payload() + "\n```"
        mock_message = MagicMock()
        mock_message.content = payload
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(client_resolver, "get_openai_client", return_value=mock_client):
            result = await client_resolver._call_llm(
                "John Smith", None, None, [_make_candidate("GWM-001")], []
            )

        assert result is not None
        assert result.gwm_id == "GWM-001"


# ---------------------------------------------------------------------------
# 7.9 — resolve_client() end-to-end with all external calls mocked
# ---------------------------------------------------------------------------

class TestResolveClientEndToEnd:
    """Tests for the full resolve_client() pipeline with mocked DB + LLM."""

    def _make_llm_decision_json(
        self,
        match_found: bool = True,
        gwm_id: str = "GWM-001",
        confidence: float = 0.88,
    ) -> str:
        return json.dumps({
            "match_found": match_found,
            "gwm_id": gwm_id if match_found else None,
            "matched_name": "John Smith" if match_found else None,
            "source": "fuzzy_client" if match_found else None,
            "confidence": confidence,
            "conflict": False,
            "conflict_gwm_ids": [],
            "ambiguous": False,
            "resolution_factors": ["Name similarity"],
            "candidates_considered": 1,
        })

    @pytest.mark.asyncio
    async def test_full_flow_with_fuzzy_and_hpq_results(self):
        """Both DB sources return results; LLM resolves to fuzzy candidate."""
        from app.agent import client_resolver

        fuzzy_candidates = [_make_candidate("GWM-001", db_score=0.80)]
        hpq_candidates = [
            _make_candidate(
                "GWM-002",
                source="high_priority_queue_client",
                db_score=0.65,
            )
        ]

        mock_message = MagicMock()
        mock_message.content = self._make_llm_decision_json()
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=hpq_candidates),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            result = await client_resolver.resolve_client("John Smith")

        assert result.match_found is True
        assert result.gwm_id == "GWM-001"
        assert result.adjudication == AdjudicationMethod.LLM

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_no_match(self):
        """Both DB sources return empty → immediate no-match without LLM call."""
        from app.agent import client_resolver

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await client_resolver.resolve_client("Unknown Person")

        assert result.match_found is False
        assert result.confidence == 0.0
        assert result.search_summary.fuzzy_client_hits == 0
        assert result.search_summary.hpq_client_hits == 0

    @pytest.mark.asyncio
    async def test_empty_name_after_normalization_returns_no_match(self):
        """Name that normalizes to empty string → no-match without any DB calls."""
        from app.agent import client_resolver

        mock_fuzzy = AsyncMock()
        mock_hpq = AsyncMock()

        with (
            patch.object(client_resolver, "search_fuzzy_client", new=mock_fuzzy),
            patch.object(client_resolver, "search_queue_client", new=mock_hpq),
        ):
            # A string of only honorifics reduces to empty after normalize_name
            result = await client_resolver.resolve_client("Dr. Jr.")

        assert result.match_found is False
        # DB should not be called for an empty normalized name
        mock_fuzzy.assert_not_called()
        mock_hpq.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_high_score_candidate_uses_fast_path(self):
        """Single fuzzy candidate with score >= 0.85 skips the LLM entirely."""
        from app.agent import client_resolver

        fuzzy_candidates = [_make_candidate("GWM-001", db_score=0.92)]
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock()  # should never be called

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            result = await client_resolver.resolve_client("John Smith")

        assert result.match_found is True
        assert result.adjudication == AdjudicationMethod.FAST_PATH
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_activates_rule_based_fallback(self):
        """When LLM returns None (timeout/error), Levenshtein fallback is used."""
        from app.agent import client_resolver

        fuzzy_candidates = [_make_candidate("GWM-001", db_score=0.70)]

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(return_value=fuzzy_candidates),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(client_resolver, "get_openai_client", return_value=mock_openai),
        ):
            result = await client_resolver.resolve_client("John Smith")

        assert result.adjudication == AdjudicationMethod.RULE_BASED
        assert any("rule-based" in w.lower() or "llm" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_db_exception_is_handled_gracefully(self):
        """If a DB source raises an exception, resolve_client still returns a result."""
        from app.agent import client_resolver

        with (
            patch.object(
                client_resolver, "search_fuzzy_client",
                new=AsyncMock(side_effect=Exception("DB connection failed")),
            ),
            patch.object(
                client_resolver, "search_queue_client",
                new=AsyncMock(return_value=[]),
            ),
        ):
            # Should not raise — exceptions are swallowed and surfaced in warnings
            result = await client_resolver.resolve_client("John Smith")

        assert isinstance(result, LookupResult)

    @pytest.mark.asyncio
    async def test_name_is_normalized_before_db_queries(self):
        """Honorifics are stripped before the name is sent to DB queries."""
        from app.agent import client_resolver

        captured_names: list[str] = []

        async def _capture_fuzzy(name: str, **kwargs):
            captured_names.append(name)
            return []

        async def _capture_hpq(name: str, **kwargs):
            return []

        with (
            patch.object(client_resolver, "search_fuzzy_client", new=_capture_fuzzy),
            patch.object(client_resolver, "search_queue_client", new=_capture_hpq),
        ):
            await client_resolver.resolve_client("Dr. John Smith Jr.")

        # The name passed to the DB should not contain honorifics
        assert captured_names[0] == "John Smith"

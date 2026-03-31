"""
Integration test: extraction pipeline with kg_ontology relevance filtering.

Exercises _process_message() end-to-end with mocked LLM + DB to verify:
- Entity type validation (invalid types skipped)
- Predicate normalization (buys->owns, unknown->None)
- Relevance filtering (LOW signal dropped, HIGH kept)
- Filter counter reporting
- Symmetric dedup uses ontology
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

from worker.entity_extraction import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    _process_message,
    _relationship_already_exists,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fake_entity_id() -> str:
    """Return a deterministic-looking UUID string."""
    return str(uuid.uuid4())


def _make_result(
    entities: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
) -> ExtractionResult:
    """Build an ExtractionResult from simplified dicts."""
    ents = [ExtractedEntity(**e) for e in (entities or [])]
    rels = [ExtractedRelationship(**r) for r in (relationships or [])]
    return ExtractionResult(entities=ents, relationships=rels)


@asynccontextmanager
async def _mock_acquire():
    """Yield a mock connection object that supports fetchrow."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)  # default: no existing row
    yield conn


# ── Fixtures ─────────────────────────────────────────────────────────────────

# Entity ID map used across tests — gives stable IDs per entity name
_ENTITY_IDS: dict[str, str] = {}


def _stable_entity_id(
    name: str,
    entity_type: str,
    aliases: list[str],
    team_id: str | None = None,
    disambiguation_context: str = "",
) -> str:
    """Return a stable UUID for each unique entity name."""
    key = name.lower().strip()
    if key not in _ENTITY_IDS:
        _ENTITY_IDS[key] = _fake_entity_id()
    return _ENTITY_IDS[key]


# ── Test: HIGH-signal relationships are stored ───────────────────────────────


class TestHighSignalRelationshipsStored:
    """Scenario 1: 'owns' predicate with confidence 0.90 should be upserted."""

    async def test_owns_high_signal_is_stored(self):
        extraction = _make_result(
            entities=[
                {"name": "John Smith", "type": "person"},
                {"name": "Dallas Cowboys", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "John Smith",
                    "predicate": "owns",
                    "predicate_family": "ownership",
                    "object": "Dallas Cowboys",
                    "confidence": 0.90,
                    "evidence": "Smith completed the purchase.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-rel-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-1", "John Smith owns Dallas Cowboys.")

        assert result["relationships"] >= 1
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["predicate"] == "owns"
        assert call_kwargs.kwargs["predicate_family"] == "ownership"


# ── Test: LOW-signal relationships are filtered ──────────────────────────────


class TestLowSignalRelationshipsFiltered:
    """Scenario 2: 'coaches' predicate (LOW signal) should NOT be upserted."""

    async def test_coaches_low_signal_is_filtered(self):
        extraction = _make_result(
            entities=[
                {"name": "Mike Jones", "type": "person"},
                {"name": "Green Bay Packers", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "Mike Jones",
                    "predicate": "coaches",
                    "predicate_family": "role",
                    "object": "Green Bay Packers",
                    "confidence": 0.99,
                    "evidence": "Jones is head coach.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-2", "Mike Jones coaches the Packers.")

        mock_upsert.assert_not_called()
        assert result["filtered_by_relevance"] == 1


# ── Test: Unknown predicates are filtered ────────────────────────────────────


class TestUnknownPredicatesFiltered:
    """Scenario 3: 'random_unknown_verb' should be filtered by unknown predicate."""

    async def test_unknown_predicate_filtered(self):
        extraction = _make_result(
            entities=[
                {"name": "Alice", "type": "person"},
                {"name": "Bob", "type": "person"},
            ],
            relationships=[
                {
                    "subject": "Alice",
                    "predicate": "random_unknown_verb",
                    "predicate_family": "ownership",
                    "object": "Bob",
                    "confidence": 0.95,
                    "evidence": "Alice random_unknown_verb Bob.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-3", "Alice random_unknown_verb Bob.")

        mock_upsert.assert_not_called()
        assert result["filtered_by_unknown_predicate"] == 1


# ── Test: Invalid entity types are skipped ───────────────────────────────────


class TestInvalidEntityTypesSkipped:
    """Scenario 4: Entities with type 'product' or 'other' should NOT be created."""

    async def test_invalid_entity_type_not_created(self):
        extraction = _make_result(
            entities=[
                {"name": "Widget X", "type": "product"},
                {"name": "Some Thing", "type": "other"},
                {"name": "Valid Person", "type": "person"},
            ],
            relationships=[],
        )

        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                AsyncMock(),
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-4", "Some text.")

        # Only 'Valid Person' (type=person) should have been created
        assert result["entities"] == 1
        # Verify the calls to db_find_or_create_entity — only person type
        assert mock_find_or_create.call_count == 1
        call_args = mock_find_or_create.call_args
        assert call_args.args[1] == "person"  # entity_type positional arg


# ── Test: Valid entity types are created ─────────────────────────────────────


class TestValidEntityTypesCreated:
    """Scenario 5: Entity with type 'person' should be created."""

    async def test_person_entity_created(self):
        extraction = _make_result(
            entities=[
                {"name": "Jane Doe", "type": "person", "aliases": ["J. Doe"]},
            ],
            relationships=[],
        )

        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                AsyncMock(),
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-5", "Jane Doe is notable.")

        assert result["entities"] == 1
        mock_find_or_create.assert_called_once()
        call_args = mock_find_or_create.call_args
        assert call_args.args[0] == "Jane Doe"
        assert call_args.args[1] == "person"


# ── Test: Predicate normalization end-to-end ─────────────────────────────────


class TestPredicateNormalization:
    """Scenario 6: 'buys' and 'purchased' should both normalize to 'owns'."""

    async def test_buys_normalizes_to_owns(self):
        extraction = _make_result(
            entities=[
                {"name": "Buyer A", "type": "person"},
                {"name": "Team A", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "Buyer A",
                    "predicate": "buys",
                    "predicate_family": "ownership",
                    "object": "Team A",
                    "confidence": 0.85,
                    "evidence": "Buyer A buys Team A.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            await _process_message("session-6a", "Buyer A buys Team A.")

        mock_upsert.assert_called_once()
        assert mock_upsert.call_args.kwargs["predicate"] == "owns"

    async def test_purchased_normalizes_to_owns(self):
        extraction = _make_result(
            entities=[
                {"name": "Buyer B", "type": "person"},
                {"name": "Team B", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "Buyer B",
                    "predicate": "purchased",
                    "predicate_family": "ownership",
                    "object": "Team B",
                    "confidence": 0.80,
                    "evidence": "Buyer B purchased Team B.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            await _process_message("session-6b", "Buyer B purchased Team B.")

        mock_upsert.assert_called_once()
        assert mock_upsert.call_args.kwargs["predicate"] == "owns"


# ── Test: Return dict includes correct filter counters ───────────────────────


class TestReturnDictCounters:
    """Scenario 7: Verify return dict has all expected keys with correct values."""

    async def test_return_dict_keys_present(self):
        """A mixed extraction: 1 valid rel, 1 low-signal, 1 unknown predicate."""
        extraction = _make_result(
            entities=[
                {"name": "PersonA", "type": "person"},
                {"name": "TeamA", "type": "sports_team"},
                {"name": "PersonB", "type": "person"},
            ],
            relationships=[
                {
                    "subject": "PersonA",
                    "predicate": "owns",
                    "predicate_family": "ownership",
                    "object": "TeamA",
                    "confidence": 0.90,
                    "evidence": "PersonA owns TeamA.",
                },
                {
                    "subject": "PersonB",
                    "predicate": "coaches",
                    "predicate_family": "role",
                    "object": "TeamA",
                    "confidence": 0.99,
                    "evidence": "PersonB coaches TeamA.",
                },
                {
                    "subject": "PersonA",
                    "predicate": "totally_bogus_predicate",
                    "predicate_family": "ownership",
                    "object": "PersonB",
                    "confidence": 0.95,
                    "evidence": "Some nonsense.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-7", "Mixed extraction text.")

        # All required keys present
        assert "entities" in result
        assert "relationships" in result
        assert "skipped_duplicates" in result
        assert "filtered_by_relevance" in result
        assert "filtered_by_unknown_predicate" in result

        # Counts
        assert result["entities"] == 3  # all valid types
        assert result["relationships"] == 1  # only 'owns' passes
        assert result["filtered_by_relevance"] == 1  # 'coaches' dropped
        assert result["filtered_by_unknown_predicate"] == 1  # bogus predicate
        assert result["skipped_duplicates"] == 0

    async def test_empty_extraction_returns_zeroes(self):
        """When LLM returns nothing, all counters should be zero."""
        extraction = _make_result(entities=[], relationships=[])

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                AsyncMock(),
            ),
            patch(
                "app.db.db_upsert_relationship",
                AsyncMock(),
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-empty", "Nothing here.")

        assert result == {
            "entities": 0,
            "relationships": 0,
            "skipped_duplicates": 0,
            "filtered_by_unknown_predicate": 0,
            "filtered_by_relevance": 0,
            "client_lookups": 0,
        }


# ── Test: Symmetric relationship dedup uses ontology ─────────────────────────


class TestSymmetricRelationshipDedup:
    """Scenario 8: _relationship_already_exists uses per-predicate symmetry."""

    async def test_co_owns_symmetric_checks_both_directions(self):
        """For co_owns (symmetric=True), both directions should be queried."""
        conn = AsyncMock()
        # First query (forward direction) returns None, second (reverse) also None
        conn.fetchrow = AsyncMock(return_value=None)

        subject_id = str(uuid.uuid4())
        object_id = str(uuid.uuid4())

        exists = await _relationship_already_exists(
            conn, subject_id, object_id, "co_owns", "ownership"
        )

        assert exists is False
        # co_owns is symmetric, so fetchrow should be called twice:
        # once for forward, once for reverse
        assert conn.fetchrow.call_count == 2

    async def test_owns_non_symmetric_checks_one_direction(self):
        """For owns (symmetric=False), only the forward direction is queried."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        subject_id = str(uuid.uuid4())
        object_id = str(uuid.uuid4())

        exists = await _relationship_already_exists(
            conn, subject_id, object_id, "owns", "ownership"
        )

        assert exists is False
        # owns is NOT symmetric, so only one fetchrow call
        assert conn.fetchrow.call_count == 1

    async def test_symmetric_found_in_reverse_returns_true(self):
        """If the reverse direction matches for a symmetric predicate, return True."""
        conn = AsyncMock()
        # First query (forward): no match. Second query (reverse): match.
        conn.fetchrow = AsyncMock(
            side_effect=[None, {"id": "existing-row-id"}]
        )

        subject_id = str(uuid.uuid4())
        object_id = str(uuid.uuid4())

        exists = await _relationship_already_exists(
            conn, subject_id, object_id, "co_owns", "ownership"
        )

        assert exists is True
        assert conn.fetchrow.call_count == 2

    async def test_forward_match_returns_true_without_reverse_check(self):
        """If forward direction matches, return True immediately (no reverse query)."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "existing-row-id"})

        subject_id = str(uuid.uuid4())
        object_id = str(uuid.uuid4())

        exists = await _relationship_already_exists(
            conn, subject_id, object_id, "co_owns", "ownership"
        )

        assert exists is True
        # Forward matched, so only 1 call even though co_owns is symmetric
        assert conn.fetchrow.call_count == 1

    async def test_non_ownership_symmetric_predicate(self):
        """co_invested_with (investment family, symmetric) checks both directions."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        subject_id = str(uuid.uuid4())
        object_id = str(uuid.uuid4())

        exists = await _relationship_already_exists(
            conn, subject_id, object_id, "co_invested_with", "investment"
        )

        assert exists is False
        assert conn.fetchrow.call_count == 2  # symmetric: checks both directions


# ── Test: Duplicate relationship is counted as skipped ───────────────────────


class TestDuplicateRelationshipSkipped:
    """When _relationship_already_exists returns True, the rel is skipped."""

    async def test_duplicate_rel_increments_skipped_count(self):
        extraction = _make_result(
            entities=[
                {"name": "Owner X", "type": "person"},
                {"name": "Team X", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "Owner X",
                    "predicate": "owns",
                    "predicate_family": "ownership",
                    "object": "Team X",
                    "confidence": 0.85,
                    "evidence": "Owns it.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        @asynccontextmanager
        async def _acquire_with_existing():
            conn = AsyncMock()
            # Simulate that the relationship already exists (forward match)
            conn.fetchrow = AsyncMock(return_value={"id": "existing-rel"})
            yield conn

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _acquire_with_existing,
            ),
        ):
            result = await _process_message("session-dup", "Owner X owns Team X.")

        mock_upsert.assert_not_called()
        assert result["skipped_duplicates"] == 1
        assert result["relationships"] == 0


# ── Test: Multiple relationship types in one extraction ──────────────────────


class TestMixedRelationships:
    """Multiple relationship types: HIGH kept, MEDIUM kept if above floor, LOW dropped."""

    async def test_mixed_signal_levels(self):
        extraction = _make_result(
            entities=[
                {"name": "CEO Alice", "type": "person"},
                {"name": "Acme Corp", "type": "company"},
                {"name": "Fan Bob", "type": "person"},
                {"name": "LA Lakers", "type": "sports_team"},
            ],
            relationships=[
                # HIGH signal: ceo_of (role family) — should be kept (confidence > 0.55)
                {
                    "subject": "CEO Alice",
                    "predicate": "ceo_of",
                    "predicate_family": "role",
                    "object": "Acme Corp",
                    "confidence": 0.80,
                    "evidence": "Alice is CEO.",
                },
                # MEDIUM signal: fan_of (affinity family) — needs 0.75 confidence
                {
                    "subject": "Fan Bob",
                    "predicate": "fan_of",
                    "predicate_family": "affinity",
                    "object": "LA Lakers",
                    "confidence": 0.80,  # above 0.75 threshold
                    "evidence": "Bob is a big Lakers fan.",
                },
                # LOW signal: attended_event (affinity family) — always dropped
                {
                    "subject": "Fan Bob",
                    "predicate": "attended_event",
                    "predicate_family": "affinity",
                    "object": "LA Lakers",
                    "confidence": 0.99,
                    "evidence": "Bob attended the game.",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-mixed", "Mixed signals text.")

        assert result["relationships"] == 2  # ceo_of + fan_of
        assert result["filtered_by_relevance"] == 1  # attended_event
        assert result["filtered_by_unknown_predicate"] == 0


# ── Test: Below global confidence floor ──────────────────────────────────────


class TestGlobalConfidenceFloor:
    """A relationship below GLOBAL_CONFIDENCE_FLOOR (0.50) is dropped even if HIGH signal."""

    async def test_below_global_floor_filtered(self):
        extraction = _make_result(
            entities=[
                {"name": "Low Conf Person", "type": "person"},
                {"name": "Some Team", "type": "sports_team"},
            ],
            relationships=[
                {
                    "subject": "Low Conf Person",
                    "predicate": "owns",
                    "predicate_family": "ownership",
                    "object": "Some Team",
                    "confidence": 0.30,  # below 0.50 global floor
                    "evidence": "Maybe owns?",
                },
            ],
        )

        mock_upsert = AsyncMock(return_value={"status": "new", "id": "fake-id"})
        mock_find_or_create = AsyncMock(side_effect=_stable_entity_id)

        with (
            patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                return_value=extraction,
            ),
            patch(
                "app.db.db_find_or_create_entity",
                mock_find_or_create,
            ),
            patch(
                "app.db.db_upsert_relationship",
                mock_upsert,
            ),
            patch(
                "app.db._pool._acquire",
                _mock_acquire,
            ),
        ):
            result = await _process_message("session-floor", "Low confidence text.")

        mock_upsert.assert_not_called()
        assert result["filtered_by_relevance"] == 1

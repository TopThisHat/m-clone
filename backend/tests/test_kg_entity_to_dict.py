"""Tests for _kg_entity_to_dict null normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.db.knowledge_graph import _kg_entity_to_dict


class _FakeRecord(dict):
    """Minimal dict subclass that mimics asyncpg.Record for dict() conversion."""


def _make_row(**overrides):
    """Build a fake entity row with sensible defaults."""
    row = _FakeRecord(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="Acme Corp",
        entity_type="company",
        aliases=["Acme", "ACME Inc"],
        metadata={"sector": "tech"},
        team_id=UUID("00000000-0000-0000-0000-000000000099"),
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    row.update(overrides)
    return row


# ── Aliases normalization ────────────────────────────────────────────────────


def test_null_aliases_normalized_to_empty_list():
    row = _make_row(aliases=None)
    result = _kg_entity_to_dict(row)
    assert result["aliases"] == []


def test_valid_aliases_pass_through():
    row = _make_row(aliases=["Foo", "Bar"])
    result = _kg_entity_to_dict(row)
    assert result["aliases"] == ["Foo", "Bar"]


def test_empty_aliases_pass_through():
    row = _make_row(aliases=[])
    result = _kg_entity_to_dict(row)
    assert result["aliases"] == []


# ── Metadata normalization ───────────────────────────────────────────────────


def test_null_metadata_normalized_to_empty_dict():
    row = _make_row(metadata=None)
    result = _kg_entity_to_dict(row)
    assert result["metadata"] == {}


def test_valid_metadata_pass_through():
    row = _make_row(metadata={"key": "value"})
    result = _kg_entity_to_dict(row)
    assert result["metadata"] == {"key": "value"}


def test_empty_metadata_pass_through():
    row = _make_row(metadata={})
    result = _kg_entity_to_dict(row)
    assert result["metadata"] == {}


# ── Both null ────────────────────────────────────────────────────────────────


def test_both_null_aliases_and_metadata():
    row = _make_row(aliases=None, metadata=None)
    result = _kg_entity_to_dict(row)
    assert result["aliases"] == []
    assert result["metadata"] == {}


# ── Existing conversions still work ──────────────────────────────────────────


def test_id_converted_to_string():
    row = _make_row()
    result = _kg_entity_to_dict(row)
    assert result["id"] == "00000000-0000-0000-0000-000000000001"
    assert isinstance(result["id"], str)


def test_team_id_converted_to_string():
    row = _make_row()
    result = _kg_entity_to_dict(row)
    assert result["team_id"] == "00000000-0000-0000-0000-000000000099"


def test_timestamps_converted_to_isoformat():
    row = _make_row()
    result = _kg_entity_to_dict(row)
    assert result["created_at"] == "2025-01-01T00:00:00+00:00"
    assert result["updated_at"] == "2025-06-01T00:00:00+00:00"


def test_row_without_aliases_key_gets_defaults():
    """Rows from partial selects that omit aliases/metadata get safe defaults."""
    row = _FakeRecord(id=UUID("00000000-0000-0000-0000-000000000001"), name="X")
    result = _kg_entity_to_dict(row)
    assert result["aliases"] == []
    assert result["metadata"] == {}

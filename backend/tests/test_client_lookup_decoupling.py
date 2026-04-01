"""Unit tests for m-clone-d0nj: Decouple client lookup from entity extraction.

Verifies:
  - _process_message always extracts entities and stores to KG regardless of
    the enable_client_lookup flag.
  - Client lookup is skipped when enable_client_lookup=False (default).
  - Client lookup runs when enable_client_lookup=True.
  - Existing publish_for_extraction callers are unaffected (flag defaults False).
  - Existing agent tools (batch_lookup_clients) still resolve clients correctly.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.entity_extraction import ExtractionResult, ExtractedEntity, _process_message


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_result(person_names: list[str] | None = None) -> ExtractionResult:
    entities = [ExtractedEntity(name=n, type="person") for n in (person_names or [])]
    return ExtractionResult(entities=entities, relationships=[])


def _db_patcher():
    """Context manager that stubs out all DB and KG dependencies used in _process_message."""
    mock_find = AsyncMock(side_effect=lambda name, *a, **kw: f"eid-{name}")
    mock_upsert = AsyncMock(return_value={"status": "inserted"})

    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _fake_acquire():
        yield mock_conn

    patches = [
        patch("app.db.db_find_or_create_entity", mock_find),
        patch("app.db.db_upsert_relationship", mock_upsert),
        patch("app.db._pool._acquire", _fake_acquire),
        patch("app.kg_ontology.ALLOWED_ENTITY_TYPE_NAMES", {"person", "company", "location"}),
        patch("app.kg_ontology.normalize_predicate", return_value=None),
        patch("app.kg_ontology.should_keep_relationship", return_value=True),
    ]
    return patches, mock_find, mock_upsert


# ── 3.6: Entity extraction always runs ────────────────────────────────────────


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_entity_extraction_always_runs_flag_false(mock_extract):
    """Entity extraction and KG storage run when enable_client_lookup=False."""
    mock_extract.return_value = _make_result(["Alice Smith"])
    pats, mock_find, _ = _db_patcher()
    for p in pats:
        p.start()
    try:
        result = await _process_message(
            "sess-1", "Alice Smith is a client.",
            enable_client_lookup=False,
        )
    finally:
        for p in pats:
            p.stop()

    mock_extract.assert_called_once()
    mock_find.assert_called_once()
    assert result["entities"] == 1
    assert result["client_lookups"] == 0


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_entity_extraction_always_runs_flag_true(mock_extract):
    """Entity extraction and KG storage run even when enable_client_lookup=True."""
    mock_extract.return_value = _make_result(["Bob Jones"])
    pats, mock_find, _ = _db_patcher()
    mock_batch = AsyncMock(return_value=[{"name": "Bob Jones", "status": "matched", "gwm_id": "G1"}])
    for p in pats:
        p.start()
    try:
        with patch("app.agent.batch_resolver.batch_resolve_clients", mock_batch):
            result = await _process_message(
                "sess-2", "Bob Jones is a client.",
                enable_client_lookup=True,
            )
    finally:
        for p in pats:
            p.stop()

    mock_extract.assert_called_once()
    mock_find.assert_called_once()
    assert result["entities"] == 1


# ── 3.7: Client lookup skipped when flag=False ────────────────────────────────


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_client_lookup_skipped_when_flag_false(mock_extract):
    """batch_resolve_clients is NOT called when enable_client_lookup=False."""
    mock_extract.return_value = _make_result(["Carol White"])
    pats, _, _ = _db_patcher()
    mock_batch = AsyncMock()
    for p in pats:
        p.start()
    try:
        with patch("app.agent.batch_resolver.batch_resolve_clients", mock_batch):
            result = await _process_message(
                "sess-3", "Carol White is mentioned.",
                enable_client_lookup=False,
            )
    finally:
        for p in pats:
            p.stop()

    mock_batch.assert_not_called()
    assert result["client_lookups"] == 0


# ── 3.8: Client lookup runs when flag=True ────────────────────────────────────


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_client_lookup_runs_when_flag_true(mock_extract):
    """batch_resolve_clients IS called when enable_client_lookup=True."""
    mock_extract.return_value = _make_result(["Dave Brown", "Eve Davis"])
    pats, _, _ = _db_patcher()
    mock_batch = AsyncMock(return_value=[
        {"name": "Dave Brown", "status": "matched", "gwm_id": "G100"},
        {"name": "Eve Davis", "status": "no_match", "gwm_id": None},
    ])
    for p in pats:
        p.start()
    try:
        with patch("app.agent.batch_resolver.batch_resolve_clients", mock_batch):
            result = await _process_message(
                "sess-4", "Dave Brown and Eve Davis are mentioned.",
                enable_client_lookup=True,
            )
    finally:
        for p in pats:
            p.stop()

    mock_batch.assert_called_once()
    people_sent = {p["name"] for p in mock_batch.call_args.args[0]}
    assert people_sent == {"Dave Brown", "Eve Davis"}
    assert result["client_lookups"] == 2


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_client_lookup_only_sends_persons(mock_extract):
    """Only entities with type='person' are sent to batch_resolve_clients."""
    mock_extract.return_value = ExtractionResult(entities=[
        ExtractedEntity(name="Jane Doe", type="person"),
        ExtractedEntity(name="Acme Corp", type="company"),
        ExtractedEntity(name="London", type="location"),
    ], relationships=[])
    pats, _, _ = _db_patcher()
    mock_batch = AsyncMock(return_value=[
        {"name": "Jane Doe", "status": "matched", "gwm_id": "G200"},
    ])
    for p in pats:
        p.start()
    try:
        with patch("app.agent.batch_resolver.batch_resolve_clients", mock_batch):
            result = await _process_message(
                "sess-5", "Jane Doe from Acme Corp in London.",
                enable_client_lookup=True,
            )
    finally:
        for p in pats:
            p.stop()

    people_sent = mock_batch.call_args.args[0]
    assert len(people_sent) == 1
    assert people_sent[0]["name"] == "Jane Doe"
    assert result["client_lookups"] == 1


@pytest.mark.asyncio
@patch("worker.entity_extraction.extract_entities_and_relationships", new_callable=AsyncMock)
async def test_client_lookup_skipped_when_no_persons(mock_extract):
    """batch_resolve_clients is NOT called when there are no person entities."""
    mock_extract.return_value = ExtractionResult(entities=[
        ExtractedEntity(name="Acme Corp", type="company"),
    ], relationships=[])
    pats, _, _ = _db_patcher()
    mock_batch = AsyncMock()
    for p in pats:
        p.start()
    try:
        with patch("app.agent.batch_resolver.batch_resolve_clients", mock_batch):
            result = await _process_message(
                "sess-6", "Acme Corp is a company.",
                enable_client_lookup=True,
            )
    finally:
        for p in pats:
            p.stop()

    mock_batch.assert_not_called()
    assert result["client_lookups"] == 0


# ── publish_for_extraction stream field tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_publish_for_extraction_default_no_client_lookup():
    """publish_for_extraction defaults enable_client_lookup=False — field absent from stream."""
    from app.streams import publish_for_extraction

    captured: dict = {}

    async def fake_xadd(stream, fields, **kwargs):
        captured.update(fields)
        return "1-0"

    mock_redis = AsyncMock()
    mock_redis.xadd = fake_xadd

    with patch("app.streams.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        await publish_for_extraction("sess-x", "some text")

    assert "enable_client_lookup" not in captured


@pytest.mark.asyncio
async def test_publish_for_extraction_flag_propagated_as_string():
    """enable_client_lookup=True is written as 'true' in the stream fields."""
    from app.streams import publish_for_extraction

    captured: dict = {}

    async def fake_xadd(stream, fields, **kwargs):
        captured.update(fields)
        return "1-0"

    mock_redis = AsyncMock()
    mock_redis.xadd = fake_xadd

    with patch("app.streams.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        await publish_for_extraction("sess-y", "some text", enable_client_lookup=True)

    assert captured.get("enable_client_lookup") == "true"


# ── 3.9: Existing agent tools still work unchanged ────────────────────────────


@pytest.mark.asyncio
@patch("app.agent.batch_resolver.resolve_client", new_callable=AsyncMock)
async def test_batch_lookup_clients_tool_unchanged(mock_resolve):
    """batch_resolve_clients still resolves names correctly (no regression)."""
    from app.models.client_lookup import AdjudicationMethod

    mock_resolve.return_value = MagicMock(
        match_found=True,
        matched_name="Alice Smith",
        gwm_id="G999",
        source="hpq",
        confidence=0.95,
        adjudication=AdjudicationMethod.FAST_PATH,
        candidates=[],
        resolution_factors=[],
        warnings=[],
        ambiguous=False,
        conflict=False,
    )

    from app.agent.batch_resolver import batch_resolve_clients
    results = await batch_resolve_clients([{"name": "Alice Smith"}])
    assert len(results) == 1
    assert results[0]["status"] == "matched"
    assert results[0]["gwm_id"] == "G999"

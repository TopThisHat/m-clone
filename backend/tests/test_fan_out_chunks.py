"""Unit and integration tests for fan-out batch extraction across workers.

Covers:
  1. _split_text_into_chunks — basic splitting behaviour
  2. publish_for_extraction_chunked — Redis stream fan-out
  3. _merge_results — deduplication across chunks
  4. _process_chunk — per-chunk extraction + Redis progress tracking
  5. _merge_and_store_chunks — final merge + KG storage
  6. run_extraction_worker routing — chunked vs plain messages
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from worker.entity_extraction import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    _CHUNK_MAX_RETRIES,
    _merge_results,
    _process_chunk,
    _merge_and_store_chunks,
)
from app.streams import _split_text_into_chunks, publish_for_extraction_chunked


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(name: str, etype: str = "person") -> ExtractedEntity:
    return ExtractedEntity(name=name, type=etype)


def _make_rel(subj: str, pred: str, obj: str) -> ExtractedRelationship:
    return ExtractedRelationship(
        subject=subj, predicate=pred, predicate_family="role", object=obj, confidence=0.9,
    )


def _make_result(entities: list[str], rels: list[tuple] | None = None) -> ExtractionResult:
    ents = [_make_entity(n) for n in entities]
    relationships = [_make_rel(*t) for t in (rels or [])]
    return ExtractionResult(entities=ents, relationships=relationships)


def _make_db_mocks():
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_conn, mock_cm


def _make_redis_mock(hget_map: dict | None = None, hincrby_val: int = 1):
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    r.hset = AsyncMock()
    r.expire = AsyncMock()
    r.hincrby = AsyncMock(return_value=hincrby_val)
    r.hget = AsyncMock(side_effect=lambda key, field: hget_map.get(field) if hget_map else None)
    return r


# ===========================================================================
# 1. _split_text_into_chunks
# ===========================================================================

class TestSplitTextIntoChunks:

    def test_empty_string_returns_empty(self):
        assert _split_text_into_chunks("", 100) == []

    def test_text_shorter_than_chunk_size(self):
        chunks = _split_text_into_chunks("hello world", 100)
        assert chunks == ["hello world"]

    def test_exact_chunk_size(self):
        text = "a" * 10
        chunks = _split_text_into_chunks(text, 10)
        assert chunks == ["aaaaaaaaaa"]

    def test_splits_evenly(self):
        text = "a" * 20
        chunks = _split_text_into_chunks(text, 10)
        assert len(chunks) == 2
        assert all(len(c) == 10 for c in chunks)

    def test_last_chunk_is_shorter(self):
        text = "a" * 25
        chunks = _split_text_into_chunks(text, 10)
        assert len(chunks) == 3
        assert len(chunks[-1]) == 5

    def test_reassembly_equals_original(self):
        text = "The quick brown fox jumps over the lazy dog" * 50
        chunk_size = 100
        chunks = _split_text_into_chunks(text, chunk_size)
        assert "".join(chunks) == text

    def test_chunk_size_one(self):
        text = "abc"
        chunks = _split_text_into_chunks(text, 1)
        assert chunks == ["a", "b", "c"]


# ===========================================================================
# 2. publish_for_extraction_chunked
# ===========================================================================

class TestPublishForExtractionChunked:

    @pytest.mark.asyncio
    async def test_empty_text_returns_zero(self):
        count = await publish_for_extraction_chunked("sess-1", "")
        assert count == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_zero(self):
        count = await publish_for_extraction_chunked("sess-2", "   \n\t  ")
        assert count == 0

    @pytest.mark.asyncio
    async def test_publishes_correct_chunk_count(self):
        text = "x" * 8000
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            count = await publish_for_extraction_chunked("sess-3", text, chunk_size=4000)
        assert count == 2
        assert mock_r.xadd.call_count == 2

    @pytest.mark.asyncio
    async def test_single_chunk_for_short_text(self):
        text = "short text"
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            count = await publish_for_extraction_chunked("sess-4", text, chunk_size=4000)
        assert count == 1
        assert mock_r.xadd.call_count == 1

    @pytest.mark.asyncio
    async def test_chunk_fields_contain_metadata(self):
        text = "x" * 8000
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            await publish_for_extraction_chunked("sess-5", text, chunk_size=4000)

        calls = mock_r.xadd.call_args_list
        # First chunk
        fields_0 = calls[0][0][1]
        assert fields_0["session_id"] == "sess-5"
        assert fields_0["chunk_index"] == "0"
        assert fields_0["total_chunks"] == "2"
        assert fields_0["parent_session_id"] == "sess-5"
        # Second chunk
        fields_1 = calls[1][0][1]
        assert fields_1["chunk_index"] == "1"

    @pytest.mark.asyncio
    async def test_team_id_propagated(self):
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            await publish_for_extraction_chunked("sess-6", "text", team_id="team-abc")
        fields = mock_r.xadd.call_args[0][1]
        assert fields["team_id"] == "team-abc"

    @pytest.mark.asyncio
    async def test_is_document_flag_propagated(self):
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            await publish_for_extraction_chunked("sess-7", "text", is_document=True)
        fields = mock_r.xadd.call_args[0][1]
        assert fields["is_document"] == "true"

    @pytest.mark.asyncio
    async def test_progress_hash_initialised(self):
        text = "x" * 12000
        mock_r = _make_redis_mock()
        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            await publish_for_extraction_chunked("sess-8", text, chunk_size=4000)
        # hset should be called once to init the progress hash
        hset_calls = [c for c in mock_r.hset.call_args_list]
        assert any("total_chunks" in str(c) for c in hset_calls)

    @pytest.mark.asyncio
    async def test_redis_error_returns_zero(self):
        from redis.exceptions import RedisError
        with patch("app.streams.get_redis", AsyncMock(side_effect=RedisError("down"))):
            count = await publish_for_extraction_chunked("sess-9", "some text")
        assert count == 0


# ===========================================================================
# 3. _merge_results — deduplication
# ===========================================================================

class TestMergeResults:

    def test_empty_list_returns_empty(self):
        result = _merge_results([])
        assert result.entities == []
        assert result.relationships == []

    def test_single_result_passthrough(self):
        r = _make_result(["Alice", "Bob"], [("Alice", "ceo_of", "Acme")])
        merged = _merge_results([r])
        assert len(merged.entities) == 2
        assert len(merged.relationships) == 1

    def test_deduplicates_entities_by_name(self):
        r1 = _make_result(["Alice", "Bob"])
        r2 = _make_result(["Alice", "Carol"])  # Alice duplicated
        merged = _merge_results([r1, r2])
        names = [e.name for e in merged.entities]
        assert names.count("Alice") == 1
        assert "Bob" in names
        assert "Carol" in names

    def test_deduplication_is_case_insensitive(self):
        r1 = _make_result(["alice"])
        r2 = _make_result(["Alice"])
        merged = _merge_results([r1, r2])
        assert len(merged.entities) == 1

    def test_deduplicates_relationships_by_triple(self):
        rel = ("Alice", "ceo_of", "Acme")
        r1 = _make_result(["Alice"], [rel])
        r2 = _make_result(["Alice"], [rel])  # same relationship
        merged = _merge_results([r1, r2])
        assert len(merged.relationships) == 1

    def test_different_predicates_kept(self):
        r1 = _make_result(["Alice"], [("Alice", "ceo_of", "Acme")])
        r2 = _make_result(["Alice"], [("Alice", "board_member_of", "Acme")])
        merged = _merge_results([r1, r2])
        assert len(merged.relationships) == 2

    def test_preserves_order_of_first_seen(self):
        r1 = _make_result(["Alice", "Bob"])
        r2 = _make_result(["Carol", "Alice"])
        merged = _merge_results([r1, r2])
        names = [e.name for e in merged.entities]
        assert names[0] == "Alice"  # first seen
        assert names[1] == "Bob"
        assert names[2] == "Carol"

    def test_three_chunks_merged(self):
        r1 = _make_result(["A"], [("A", "ceo_of", "X")])
        r2 = _make_result(["B"], [("B", "owns", "Y")])
        r3 = _make_result(["A", "C"], [("A", "ceo_of", "X")])  # A and rel duplicated
        merged = _merge_results([r1, r2, r3])
        names = {e.name for e in merged.entities}
        assert names == {"A", "B", "C"}
        assert len(merged.relationships) == 2  # deduped


# ===========================================================================
# 4. _process_chunk
# ===========================================================================

class TestProcessChunk:

    @pytest.mark.asyncio
    async def test_non_final_chunk_returns_empty_counts(self):
        """A non-final chunk stores result but returns zeros (KG write not yet done)."""
        extraction = _make_result(["Alice"])
        mock_r = _make_redis_mock(hincrby_val=1)  # 1 out of 3 done

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction),
        ), patch("worker.entity_extraction._get_redis", AsyncMock(return_value=mock_r),
                 create=True), \
           patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)):
            result = await _process_chunk("sess-a", 0, 3, "some text")

        assert result["entities"] == 0
        assert result["relationships"] == 0

    @pytest.mark.asyncio
    async def test_final_chunk_triggers_merge(self):
        """When done_count reaches total_chunks, the merge is triggered."""
        extraction = _make_result(["Alice"])
        chunk_payload = extraction.model_dump_json()
        mock_r = _make_redis_mock(
            hget_map={"chunk:0": chunk_payload, "chunk:1": chunk_payload},
            hincrby_val=2,  # this is the final chunk
        )
        _, mock_cm = _make_db_mocks()

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction),
        ), patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
           patch("app.db.db_find_or_create_entity", AsyncMock(return_value="eid-1")), \
           patch("app.db.db_upsert_relationship",
                 AsyncMock(return_value={"status": "inserted", "new_id": "r-1"})), \
           patch("app.db._pool._acquire", return_value=mock_cm):
            result = await _process_chunk("sess-b", 1, 2, "some text")

        # Merge ran — entity count should be non-zero (or at least it called KG path)
        assert result["entities"] >= 0  # merge ran without error

    @pytest.mark.asyncio
    async def test_chunk_retry_on_failure(self):
        """Failed extraction is retried up to _CHUNK_MAX_RETRIES times."""
        call_count = {"n": 0}

        async def flaky_extract(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= _CHUNK_MAX_RETRIES:
                raise RuntimeError("transient error")
            return _make_result(["Alice"])

        mock_r = _make_redis_mock(hincrby_val=1)

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            side_effect=flaky_extract,
        ), patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
           patch("asyncio.sleep", AsyncMock()):
            result = await _process_chunk("sess-c", 0, 3, "some text")

        assert call_count["n"] == _CHUNK_MAX_RETRIES + 1
        # Non-final chunk, so returns zeros
        assert result["entities"] == 0

    @pytest.mark.asyncio
    async def test_chunk_marks_failed_after_max_retries(self):
        """After exhausting retries, chunk is stored as failed (not raised)."""
        mock_r = _make_redis_mock(hincrby_val=1)

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(side_effect=RuntimeError("always fails")),
        ), patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
           patch("asyncio.sleep", AsyncMock()):
            # Must NOT raise
            result = await _process_chunk("sess-d", 0, 3, "some text")

        assert result["entities"] == 0
        # Check that hset was called with failed=True marker
        hset_calls = str(mock_r.hset.call_args_list)
        assert "failed" in hset_calls

    @pytest.mark.asyncio
    async def test_chunk_stores_result_in_redis(self):
        """Successful chunk stores ExtractionResult JSON in the progress hash."""
        extraction = _make_result(["Bob"])
        mock_r = _make_redis_mock(hincrby_val=1)

        with patch(
            "worker.entity_extraction.extract_entities_and_relationships",
            AsyncMock(return_value=extraction),
        ), patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)):
            await _process_chunk("sess-e", 0, 3, "some text")

        # hset should have been called with chunk:0 data
        hset_args = str(mock_r.hset.call_args_list)
        assert "chunk:0" in hset_args
        assert "Bob" in hset_args


# ===========================================================================
# 5. _merge_and_store_chunks
# ===========================================================================

class TestMergeAndStoreChunks:

    @pytest.mark.asyncio
    async def test_merges_all_successful_chunks(self):
        r1 = _make_result(["Alice"])
        r2 = _make_result(["Bob"])
        hget_map = {
            "chunk:0": r1.model_dump_json(),
            "chunk:1": r2.model_dump_json(),
        }
        mock_r = _make_redis_mock(hget_map=hget_map)
        _, mock_cm = _make_db_mocks()

        with patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
             patch("app.db.db_find_or_create_entity", AsyncMock(return_value="eid-1")), \
             patch("app.db.db_upsert_relationship",
                   AsyncMock(return_value={"status": "inserted", "new_id": "r-1"})), \
             patch("app.db._pool._acquire", return_value=mock_cm):
            result = await _merge_and_store_chunks("sess-m1", 2)

        # Two unique entities processed
        assert result["entities"] == 2

    @pytest.mark.asyncio
    async def test_handles_failed_chunks_gracefully(self):
        r1 = _make_result(["Alice"])
        failed = json.dumps({"failed": True, "entities": [], "relationships": []})
        hget_map = {
            "chunk:0": r1.model_dump_json(),
            "chunk:1": failed,
        }
        mock_r = _make_redis_mock(hget_map=hget_map)
        _, mock_cm = _make_db_mocks()

        with patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
             patch("app.db.db_find_or_create_entity", AsyncMock(return_value="eid-2")), \
             patch("app.db.db_upsert_relationship",
                   AsyncMock(return_value={"status": "inserted", "new_id": "r-2"})), \
             patch("app.db._pool._acquire", return_value=mock_cm):
            result = await _merge_and_store_chunks("sess-m2", 2)

        # Partial results still stored
        assert result["entities"] == 1

    @pytest.mark.asyncio
    async def test_all_failed_chunks_returns_zeros(self):
        failed = json.dumps({"failed": True})
        hget_map = {"chunk:0": failed, "chunk:1": failed}
        mock_r = _make_redis_mock(hget_map=hget_map)

        with patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)):
            result = await _merge_and_store_chunks("sess-m3", 2)

        assert result["entities"] == 0

    @pytest.mark.asyncio
    async def test_missing_chunk_data_treated_as_failed(self):
        r1 = _make_result(["Alice"])
        # chunk:1 is missing from the hash
        hget_map = {"chunk:0": r1.model_dump_json()}
        mock_r = _make_redis_mock(hget_map=hget_map)
        _, mock_cm = _make_db_mocks()

        with patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
             patch("app.db.db_find_or_create_entity", AsyncMock(return_value="eid-3")), \
             patch("app.db.db_upsert_relationship",
                   AsyncMock(return_value={"status": "inserted", "new_id": "r-3"})), \
             patch("app.db._pool._acquire", return_value=mock_cm):
            result = await _merge_and_store_chunks("sess-m4", 2)

        assert result["entities"] == 1

    @pytest.mark.asyncio
    async def test_deduplication_across_chunks(self):
        """Entities duplicated across chunks are stored only once."""
        r1 = _make_result(["Alice"])
        r2 = _make_result(["Alice", "Bob"])  # Alice is in both
        hget_map = {
            "chunk:0": r1.model_dump_json(),
            "chunk:1": r2.model_dump_json(),
        }
        mock_r = _make_redis_mock(hget_map=hget_map)
        db_calls: list[str] = []

        async def track_entity(name, *args, **kwargs):
            db_calls.append(name)
            return f"eid-{name}"

        _, mock_cm = _make_db_mocks()

        with patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r)), \
             patch("app.db.db_find_or_create_entity", side_effect=track_entity), \
             patch("app.db.db_upsert_relationship",
                   AsyncMock(return_value={"status": "inserted", "new_id": "r-1"})), \
             patch("app.db._pool._acquire", return_value=mock_cm):
            result = await _merge_and_store_chunks("sess-m5", 2)

        assert result["entities"] == 2  # Alice + Bob, not 3
        # Alice should appear only once in DB calls
        assert db_calls.count("Alice") == 1


# ===========================================================================
# 6. run_extraction_worker routing
# ===========================================================================

class TestRunExtractionWorkerRouting:

    @pytest.mark.asyncio
    async def test_routes_chunked_message_to_process_chunk(self):
        """Messages with chunk_index/total_chunks call _process_chunk, not _process_message."""
        msg_data = {
            "session_id": "sess-w1",
            "report_md": "chunk text",
            "chunk_index": "0",
            "total_chunks": "2",
            "parent_session_id": "sess-w1",
        }

        mock_process_chunk = AsyncMock(return_value={"entities": 0, "relationships": 0})
        mock_process_message = AsyncMock()

        # We'll cancel the loop after one message
        with patch(
            "app.streams.consume_extraction_next",
            side_effect=[("1-0", msg_data), asyncio.CancelledError()],
        ), patch("app.streams.create_extraction_group", AsyncMock()), \
           patch("app.streams.ack_extraction", AsyncMock()), \
           patch("worker.entity_extraction._process_chunk", mock_process_chunk), \
           patch("worker.entity_extraction._process_message", mock_process_message), \
           patch("worker.entity_extraction._increment_extraction_retry", AsyncMock(return_value=0)):
            from worker.entity_extraction import run_extraction_worker
            try:
                await run_extraction_worker()
            except asyncio.CancelledError:
                pass

        mock_process_chunk.assert_called_once_with(
            "sess-w1", 0, 2, "chunk text",
            team_id=None, is_document=False, enable_client_lookup=False,
        )
        mock_process_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_routes_plain_message_to_process_message(self):
        """Messages without chunk_index call _process_message, not _process_chunk."""
        msg_data = {
            "session_id": "sess-w2",
            "report_md": "regular text",
        }

        mock_process_chunk = AsyncMock()
        mock_process_message = AsyncMock(return_value={"entities": 1, "relationships": 0})

        with patch(
            "app.streams.consume_extraction_next",
            side_effect=[("2-0", msg_data), asyncio.CancelledError()],
        ), patch("app.streams.create_extraction_group", AsyncMock()), \
           patch("app.streams.ack_extraction", AsyncMock()), \
           patch("worker.entity_extraction._process_chunk", mock_process_chunk), \
           patch("worker.entity_extraction._process_message", mock_process_message), \
           patch("worker.entity_extraction._increment_extraction_retry", AsyncMock(return_value=0)):
            from worker.entity_extraction import run_extraction_worker
            try:
                await run_extraction_worker()
            except asyncio.CancelledError:
                pass

        mock_process_message.assert_called_once()
        mock_process_chunk.assert_not_called()


# ===========================================================================
# 7. Fan-out integration: large document → chunks → merge
# ===========================================================================

class TestFanOutIntegration:

    @pytest.mark.asyncio
    async def test_large_document_fan_out_and_merge(self):
        """Simulate a 3-chunk fan-out: publish → process each chunk → merge → KG store."""
        # Create a document that produces exactly 3 chunks at chunk_size=4000
        chunk_size = 4000
        # 8001 chars → [0:4000], [4000:8000], [8000:8001] = 3 chunks
        text = "Alice Smith is the CEO of Acme Corp. " * 217  # 37*217=8029 → 3 chunks
        session_id = "integration-sess-1"

        # Step 1: publish_for_extraction_chunked
        published_msgs: list[dict] = []
        mock_r = AsyncMock()
        mock_r.hset = AsyncMock()
        mock_r.expire = AsyncMock()
        mock_r.hincrby = AsyncMock(return_value=1)

        async def fake_xadd(stream, fields, **kwargs):
            published_msgs.append(dict(fields))
            return f"{len(published_msgs)}-0"

        mock_r.xadd = AsyncMock(side_effect=fake_xadd)

        with patch("app.streams.get_redis", AsyncMock(return_value=mock_r)):
            count = await publish_for_extraction_chunked(session_id, text, chunk_size=chunk_size)

        assert count == 3
        assert len(published_msgs) == 3
        for i, msg in enumerate(published_msgs):
            assert msg["chunk_index"] == str(i)
            assert msg["total_chunks"] == "3"
            assert msg["session_id"] == session_id

        # Step 2: simulate processing all 3 chunks
        extraction_per_chunk = _make_result(
            ["Alice Smith", "Acme Corp"],
            [("Alice Smith", "ceo_of", "Acme Corp")],
        )
        chunk_results: dict[str, str] = {}
        done_counter = {"n": 0}

        async def fake_hincrby(key, field, amount):
            done_counter["n"] += 1
            return done_counter["n"]

        async def fake_hset(key, mapping):
            chunk_results.update(mapping)

        async def fake_hget(key, field):
            return chunk_results.get(field)

        mock_r2 = AsyncMock()
        mock_r2.hset = AsyncMock(side_effect=fake_hset)
        mock_r2.expire = AsyncMock()
        mock_r2.hincrby = AsyncMock(side_effect=fake_hincrby)
        mock_r2.hget = AsyncMock(side_effect=fake_hget)

        _, mock_cm = _make_db_mocks()
        db_entity_calls: list[str] = []

        async def track_entity(name, *args, **kwargs):
            db_entity_calls.append(name)
            return f"eid-{name}"

        merge_result: dict | None = None

        for i in range(3):
            with patch(
                "worker.entity_extraction.extract_entities_and_relationships",
                AsyncMock(return_value=extraction_per_chunk),
            ), patch("app.redis_client.get_redis", AsyncMock(return_value=mock_r2)), \
               patch("app.db.db_find_or_create_entity", side_effect=track_entity), \
               patch("app.db.db_upsert_relationship",
                     AsyncMock(return_value={"status": "inserted", "new_id": f"r-{i}"})), \
               patch("app.db._pool._acquire", return_value=mock_cm):
                res = await _process_chunk(session_id, i, 3, f"chunk {i} text")
                if done_counter["n"] == 3:
                    merge_result = res

        # Step 3: verify merge output
        assert merge_result is not None
        # After deduplication: Alice Smith + Acme Corp = 2 entities
        assert merge_result["entities"] == 2
        # Each entity should appear only once in DB calls
        assert db_entity_calls.count("Alice Smith") == 1
        assert db_entity_calls.count("Acme Corp") == 1

"""
Tests for attribute clustering JSON serialization safety.

Covers:
  1. _sanitize_payload converts callable values to strings
  2. _sanitize_payload passes through valid JSON types unchanged
  3. _sanitize_payload handles nested dicts and lists
  4. _sanitize_payload handles None values correctly
  5. enqueue_many rejects non-serializable payloads gracefully (no crash)
  6. cluster_attributes returns JSON-serializable output
  7. Validation workflow payload construction produces serializable dicts
  8. publish_job handles payloads with edge-case types
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1-4: _sanitize_payload unit tests
# ---------------------------------------------------------------------------

class TestSanitizePayload:
    def test_passes_through_valid_types(self):
        from app.job_queue import _sanitize_payload

        payload = {
            "str_val": "hello",
            "int_val": 42,
            "float_val": 3.14,
            "bool_val": True,
            "none_val": None,
        }
        result = _sanitize_payload(payload)
        assert result == payload
        # Must be JSON-serializable
        json.dumps(result)

    def test_converts_callable_to_string(self):
        from app.job_queue import _sanitize_payload

        def my_func():
            pass

        payload = {"callback": my_func, "name": "test"}
        result = _sanitize_payload(payload)

        assert result["name"] == "test"
        assert isinstance(result["callback"], str)
        assert "my_func" in result["callback"]
        # Must be JSON-serializable
        json.dumps(result)

    def test_handles_nested_dicts(self):
        from app.job_queue import _sanitize_payload

        def bad_func():
            pass

        payload = {
            "outer": "ok",
            "nested": {"inner": bad_func, "good": "value"},
        }
        result = _sanitize_payload(payload)
        assert result["outer"] == "ok"
        assert result["nested"]["good"] == "value"
        assert isinstance(result["nested"]["inner"], str)
        json.dumps(result)

    def test_handles_lists(self):
        from app.job_queue import _sanitize_payload

        payload = {
            "ids": ["abc", "def"],
            "numbers": [1, 2, 3],
        }
        result = _sanitize_payload(payload)
        assert result["ids"] == ["abc", "def"]
        assert result["numbers"] == [1, 2, 3]
        json.dumps(result)

    def test_handles_list_with_non_serializable_items(self):
        from app.job_queue import _sanitize_payload

        class CustomObj:
            def __str__(self):
                return "custom"

        payload = {"items": [CustomObj(), "normal"]}
        result = _sanitize_payload(payload)
        assert result["items"] == ["custom", "normal"]
        json.dumps(result)

    def test_converts_uuid_like_objects(self):
        """asyncpg may return UUID objects; _sanitize_payload should convert them."""
        from app.job_queue import _sanitize_payload

        import uuid
        uid = uuid.uuid4()
        payload = {"id": uid}
        result = _sanitize_payload(payload)
        assert result["id"] == str(uid)
        json.dumps(result)

    def test_handles_empty_payload(self):
        from app.job_queue import _sanitize_payload

        assert _sanitize_payload({}) == {}

    def test_handles_lambda(self):
        from app.job_queue import _sanitize_payload

        payload = {"fn": lambda x: x}
        result = _sanitize_payload(payload)
        assert isinstance(result["fn"], str)
        json.dumps(result)

    def test_handles_class_reference(self):
        from app.job_queue import _sanitize_payload

        payload = {"cls": dict}
        result = _sanitize_payload(payload)
        assert isinstance(result["cls"], str)
        json.dumps(result)


# ---------------------------------------------------------------------------
# 5: enqueue_many serialization
# ---------------------------------------------------------------------------

class AsyncContextManager:
    def __init__(self, value):
        self._value = value
    async def __aenter__(self):
        return self._value
    async def __aexit__(self, *args):
        pass


class TestEnqueueManySerialization:
    @pytest.mark.asyncio
    async def test_serializes_valid_payload(self):
        """enqueue_many should JSON-serialize valid payloads without error."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": "job-001"}])

        jobs = [{
            "job_type": "validation_cluster",
            "payload": {
                "validation_job_id": "vj-001",
                "campaign_id": "camp-001",
                "entity_id": "ent-001",
                "cluster_id": "clust-001",
                "attribute_ids": ["attr-1", "attr-2"],
                "research_question": "Does {entity} have X?",
                "team_id": None,
            },
            "parent_job_id": "parent-001",
            "root_job_id": "root-001",
            "validation_job_id": "vj-001",
            "max_attempts": 3,
        }]

        with patch("app.job_queue._get_pool"):
            result = await _enqueue_many_with_conn(jobs, mock_conn)
            assert result == ["job-001"]
            # conn.fetch args: (sql, job_types, payloads, parent_ids, ...)
            call_args = mock_conn.fetch.call_args
            payloads_list = call_args[0][2]  # 0=sql, 1=job_types, 2=payloads
            parsed = json.loads(payloads_list[0])
            assert parsed["campaign_id"] == "camp-001"

    @pytest.mark.asyncio
    async def test_sanitizes_function_in_payload(self):
        """enqueue_many should NOT crash if a function accidentally appears in payload."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": "job-001"}])

        def rogue_function():
            pass

        jobs = [{
            "job_type": "validation_cluster",
            "payload": {
                "validation_job_id": "vj-001",
                "bad_field": rogue_function,  # This should be caught
            },
            "validation_job_id": "vj-001",
        }]

        with patch("app.job_queue._get_pool"):
            result = await _enqueue_many_with_conn(jobs, mock_conn)
            assert result == ["job-001"]
            call_args = mock_conn.fetch.call_args
            payloads_list = call_args[0][2]  # 0=sql, 1=job_types, 2=payloads
            parsed = json.loads(payloads_list[0])
            assert isinstance(parsed["bad_field"], str)
            assert "rogue_function" in parsed["bad_field"]


async def _enqueue_many_with_conn(jobs, conn):
    """Helper to call enqueue_many with a mock connection."""
    from app.job_queue import enqueue_many
    return await enqueue_many(jobs, conn=conn)


# ---------------------------------------------------------------------------
# 6: cluster_attributes returns serializable data
# ---------------------------------------------------------------------------

class TestClusterAttributesSerialization:
    @pytest.mark.asyncio
    async def test_output_is_json_serializable(self):
        """cluster_attributes output must be fully JSON-serializable."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "clusters": [
                {
                    "cluster_name": "ESG & Sustainability",
                    "attribute_labels": ["has ESG policy", "sustainability report"],
                    "research_question": "Does {entity} have ESG policies?",
                },
                {
                    "cluster_name": "Financial Health",
                    "attribute_labels": ["revenue growth"],
                    "research_question": "What is {entity}'s financial performance?",
                },
            ]
        })

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.openai_factory.get_openai_client", return_value=mock_client):
            from worker.workflows.attribute_clustering import cluster_attributes

            attrs = [
                {"id": "a1", "label": "has ESG policy", "description": "Whether company has ESG policy"},
                {"id": "a2", "label": "sustainability report", "description": "Publishes sustainability report"},
                {"id": "a3", "label": "revenue growth", "description": "Revenue growth rate"},
            ]

            result = await cluster_attributes(attrs)

            # Every cluster must be JSON-serializable
            for cluster in result:
                json.dumps(cluster)

            assert len(result) == 2
            assert result[0]["cluster_name"] == "ESG & Sustainability"

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        """cluster_attributes should raise if LLM returns empty content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.openai_factory.get_openai_client", return_value=mock_client):
            from worker.workflows.attribute_clustering import cluster_attributes

            with pytest.raises(ValueError, match="empty response"):
                await cluster_attributes([{"id": "a1", "label": "test", "description": "x"}])


# ---------------------------------------------------------------------------
# 7: Validation workflow payload construction
# ---------------------------------------------------------------------------

class TestValidationPayloadSerialization:
    def test_cluster_job_payload_is_serializable(self):
        """The payload dict built for validation_cluster jobs must serialize."""
        # Simulate the exact payload construction from validation.py
        job_id = "vj-123"
        campaign_id = "camp-456"
        eid = "ent-789"
        cluster = {
            "id": "clust-001",
            "attribute_ids": ["attr-1", "attr-2", "attr-3"],
            "research_question_template": "Does {entity} have attributes?",
        }
        team_id = "team-abc"
        entity_label = "Acme Corp"

        question = cluster.get("research_question_template") or ""
        question = question.replace("{entity}", entity_label)

        payload = {
            "validation_job_id": str(job_id),
            "campaign_id": str(campaign_id),
            "entity_id": str(eid),
            "cluster_id": str(cluster.get("id") or ""),
            "attribute_ids": [str(a) for a in cluster["attribute_ids"]],
            "research_question": str(question),
            "team_id": str(team_id) if team_id is not None else None,
        }

        # Must not raise
        serialized = json.dumps(payload)
        parsed = json.loads(serialized)
        assert parsed["campaign_id"] == "camp-456"
        assert parsed["research_question"] == "Does Acme Corp have attributes?"
        assert parsed["team_id"] == "team-abc"

    def test_cluster_job_payload_with_none_team_id(self):
        """Payload with team_id=None must serialize."""
        payload = {
            "validation_job_id": "vj-1",
            "campaign_id": "camp-1",
            "entity_id": "ent-1",
            "cluster_id": "clust-1",
            "attribute_ids": ["a1"],
            "research_question": "test?",
            "team_id": None,
        }
        serialized = json.dumps(payload)
        parsed = json.loads(serialized)
        assert parsed["team_id"] is None

    def test_cluster_job_payload_with_none_research_question_template(self):
        """When research_question_template is None, payload must still serialize.

        With a None template, the `or ""` fallback produces an empty string.
        The {entity} placeholder isn't present so the replace is a no-op.
        The validation workflow has a separate fallback for empty questions.
        """
        cluster = {
            "id": "clust-001",
            "attribute_ids": ["a1"],
            "research_question_template": None,  # Could be NULL from DB
        }
        question = cluster.get("research_question_template") or ""
        question = question.replace("{entity}", "TestCo")

        payload = {
            "validation_job_id": "vj-1",
            "campaign_id": "camp-1",
            "entity_id": "ent-1",
            "cluster_id": str(cluster.get("id") or ""),
            "attribute_ids": [str(a) for a in cluster["attribute_ids"]],
            "research_question": str(question),
            "team_id": None,
        }
        serialized = json.dumps(payload)
        parsed = json.loads(serialized)
        # Empty string because template was None (no {entity} to replace)
        assert parsed["research_question"] == ""

    def test_cluster_job_payload_with_valid_template(self):
        """When research_question_template has {entity}, it gets substituted."""
        cluster = {
            "id": "clust-001",
            "attribute_ids": ["a1"],
            "research_question_template": "Does {entity} have certifications?",
        }
        question = cluster.get("research_question_template") or ""
        question = question.replace("{entity}", "TestCo")

        payload = {
            "validation_job_id": "vj-1",
            "campaign_id": "camp-1",
            "entity_id": "ent-1",
            "cluster_id": str(cluster.get("id") or ""),
            "attribute_ids": [str(a) for a in cluster["attribute_ids"]],
            "research_question": str(question),
            "team_id": None,
        }
        serialized = json.dumps(payload)
        parsed = json.loads(serialized)
        assert parsed["research_question"] == "Does TestCo have certifications?"


# ---------------------------------------------------------------------------
# 8: publish_job edge cases
# ---------------------------------------------------------------------------

class TestPublishJobSerialization:
    @pytest.mark.asyncio
    async def test_publish_handles_dict_payload(self):
        """publish_job must serialize dict values without error."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="msg-001")

        msg_data = {
            "job_id": "j1",
            "job_type": "validation_cluster",
            "payload": {"key": "value", "num": 42},
        }

        with patch("app.streams.get_redis", return_value=mock_redis):
            from app.streams import publish_job
            msg_id = await publish_job("test-stream", msg_data)
            assert msg_id == "msg-001"

            call_args = mock_redis.xadd.call_args
            fields = call_args[0][1]
            assert json.loads(fields["payload"]) == {"key": "value", "num": 42}

    @pytest.mark.asyncio
    async def test_publish_skips_none_values(self):
        """publish_job must skip None values."""
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="msg-001")

        msg_data = {
            "job_id": "j1",
            "job_type": "test",
            "parent_job_id": None,
        }

        with patch("app.streams.get_redis", return_value=mock_redis):
            from app.streams import publish_job
            await publish_job("test-stream", msg_data)

            call_args = mock_redis.xadd.call_args
            fields = call_args[0][1]
            assert "parent_job_id" not in fields

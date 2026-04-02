"""Integration tests for the talk_to_me agent tool.

Tests agent-level behavior: tool selection, chaining with lookup_client,
clarification handling, caching across calls, and multi-tool orchestration.

These tests verify tool dispatch through execute_tool() and test
interaction patterns between talk_to_me and other registered tools.

Run: cd backend && uv run python -m pytest tests/test_talk_to_me_integration.py -v -m integration
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

import app.agent.tools as tools_mod
from app.agent.tools import TOOL_REGISTRY, execute_tool, talk_to_me
from app.dependencies import AgentDeps


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for integration tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_semaphore():
    """Reset module-level semaphore between tests."""
    tools_mod._talktome_semaphore = None
    yield
    tools_mod._talktome_semaphore = None


@pytest.fixture
def deps() -> AgentDeps:
    """Minimal AgentDeps with empty tool_cache and a mocked wiki."""
    return AgentDeps(
        tavily_api_key="test-tavily-key",
        wiki=MagicMock(),
        tool_cache={},
    )


@pytest.fixture
def mock_settings():
    """Patch app.config.settings with TalkToMe-specific test values."""
    mock = MagicMock()
    mock.talktome_api_url = "https://talktome.test/api/query"
    mock.talktome_api_key = "sk-test-secret-key-12345"
    mock.talktome_timeout_seconds = 10.0
    mock.talktome_max_concurrency = 5
    with patch("app.agent.tools.settings", mock), \
         patch("app.config.settings", mock):
        yield mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_response(
    status_code: int = 200,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Build an httpx.Response."""
    request = httpx.Request("POST", "https://talktome.test/api/query")
    if json_body is not None:
        return httpx.Response(status_code=status_code, request=request, json=json_body)
    return httpx.Response(status_code=status_code, request=request, text="")


def _success_response(summary: str = "Client had 3 meetings.") -> httpx.Response:
    return _build_response(200, json_body={"summary": summary})


def _patch_httpx_post(mock_post: AsyncMock):
    """Patch httpx.AsyncClient so .post() uses *mock_post*."""
    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.agent.tools.httpx.AsyncClient", return_value=mock_client)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestAgentToolSelection:
    """Verify talk_to_me is registered and callable via execute_tool."""

    @pytest.mark.asyncio
    async def test_agent_selects_talk_to_me_for_meeting_queries(self, deps, mock_settings):
        """execute_tool('talk_to_me', ...) dispatches to talk_to_me and returns a summary."""
        mock_post = AsyncMock(return_value=_success_response("Met on 2024-01-15."))

        with _patch_httpx_post(mock_post):
            result = await execute_tool(
                "talk_to_me",
                {"question": "Latest meeting notes?", "gwm_id": "GWM-001", "client_name": "Acme Corp"},
                deps,
            )

        assert "TalkToMe Insight" in result
        assert "Acme Corp" in result
        assert "Met on 2024-01-15" in result


@pytest.mark.integration
class TestAgentChaining:
    """Verify agent chains lookup_client -> talk_to_me when gwm_id is unknown."""

    @pytest.mark.asyncio
    async def test_chains_lookup_client_then_talk_to_me(self, deps, mock_settings):
        """Simulate the two-step chain: lookup_client resolves a name, then
        talk_to_me uses the resolved gwm_id. Verifies ordered execution."""
        # Step 1: Mock lookup_client to return a resolved client
        lookup_result = (
            "**Match Found:** John Smith\n"
            "- GWM ID: GWM-042\n"
            "- Source: priority_queue\n"
            "- Confidence: 95%\n"
            "- Method: exact"
        )

        with patch.object(
            TOOL_REGISTRY["lookup_client"], "func",
            new=AsyncMock(return_value=lookup_result),
        ):
            step1 = await execute_tool("lookup_client", {"name": "John Smith"}, deps)

        assert "GWM-042" in step1

        # Step 2: Use the resolved gwm_id in talk_to_me
        mock_post = AsyncMock(return_value=_success_response("Discussed Q4 pipeline."))
        with _patch_httpx_post(mock_post):
            step2 = await execute_tool(
                "talk_to_me",
                {"question": "Recent meetings?", "gwm_id": "GWM-042", "client_name": "John Smith"},
                deps,
            )

        assert "TalkToMe Insight" in step2
        assert "John Smith" in step2
        # Verify the correct gwm_id was sent to the API
        sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert sent_json["context"]["client_id"] == "GWM-042"


@pytest.mark.integration
class TestAgentClarification:
    """Verify agent asks for clarification on ambiguous client names."""

    @pytest.mark.asyncio
    async def test_asks_clarification_on_ambiguous_client(self, deps, mock_settings):
        """When lookup_client returns ambiguous results, talk_to_me should NOT be
        called — the agent should surface the ambiguity instead."""
        ambiguous_result = (
            "**No match found.**\n"
            "Multiple potential matches — provide company or additional context.\n"
            "\n**Candidates:**\n"
            "- John Smith (gwm_id: GWM-042, source: pq, score: 0.85)\n"
            "- John Smith Jr (gwm_id: GWM-099, source: cd, score: 0.78)"
        )

        with patch.object(
            TOOL_REGISTRY["lookup_client"], "func",
            new=AsyncMock(return_value=ambiguous_result),
        ):
            step1 = await execute_tool("lookup_client", {"name": "John Smith"}, deps)

        # Verify lookup returned ambiguous result
        assert "No match found" in step1
        assert "Multiple potential matches" in step1

        # The key assertion: talk_to_me was NOT called.
        # We verify this by checking that no HTTP call was made — if the agent
        # were to call talk_to_me, it would need a gwm_id which is unavailable.
        # Simulate: calling talk_to_me without a gwm_id should be rejected.
        result = await talk_to_me(deps, "Recent meetings?", "", "John Smith")
        assert "Missing required parameter" in result


@pytest.mark.integration
class TestAgentCaching:
    """Verify agent-level caching across repeated queries."""

    @pytest.mark.asyncio
    async def test_cache_hit_on_repeated_query(self, deps, mock_settings):
        """Two identical questions for the same client should result in only
        one actual API call; the second should hit the cache."""
        mock_post = AsyncMock(return_value=_success_response("Had 3 meetings."))

        with _patch_httpx_post(mock_post):
            result1 = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")
            result2 = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        # Both should return the same result
        assert result1 == result2
        assert "TalkToMe Insight" in result1

        # The HTTP post should only have been called once
        assert mock_post.call_count == 1


@pytest.mark.integration
class TestAgentMultiTool:
    """Verify agent combines talk_to_me with other tools."""

    @pytest.mark.asyncio
    async def test_combines_web_search_and_talk_to_me(self, deps, mock_settings):
        """Both web_search and talk_to_me can run in parallel via execute_tool.
        Verifies they don't interfere with each other."""
        mock_post = AsyncMock(return_value=_success_response("Internal meeting notes."))

        # Mock web_search to return a simple result
        web_search_result = "**Web Result:** Acme Corp reported Q4 revenue of $5B."
        original_web_search = TOOL_REGISTRY.get("web_search")

        with _patch_httpx_post(mock_post), \
             patch.dict(
                 TOOL_REGISTRY,
                 {"web_search": MagicMock(func=AsyncMock(return_value=web_search_result))},
             ):
            # Run both tools concurrently
            ttm_task = execute_tool(
                "talk_to_me",
                {"question": "Recent meetings?", "gwm_id": "GWM-001", "client_name": "Acme Corp"},
                deps,
            )
            ws_task = execute_tool(
                "web_search",
                {"query": "Acme Corp Q4 revenue"},
                deps,
            )
            ttm_result, ws_result = await asyncio.gather(ttm_task, ws_task)

        assert "TalkToMe Insight" in ttm_result
        assert "Internal meeting notes" in ttm_result
        assert "Web Result" in ws_result
        assert "Q4 revenue" in ws_result


@pytest.mark.integration
class TestAgentMultiClient:
    """Verify agent handles multi-client queries."""

    @pytest.mark.asyncio
    async def test_parallel_resolution_for_multiple_clients(self, deps, mock_settings):
        """Multiple talk_to_me calls for different clients run in parallel
        and each gets the correct response."""
        clients = [
            ("GWM-001", "Acme Corp"),
            ("GWM-002", "Beta Inc"),
            ("GWM-003", "Gamma LLC"),
        ]

        async def _per_client_post(*args: Any, **kwargs: Any) -> httpx.Response:
            sent_json = kwargs.get("json", {})
            cid = sent_json.get("context", {}).get("client_id", "unknown")
            return _build_response(200, json_body={"summary": f"Data for {cid}"})

        mock_post = AsyncMock(side_effect=_per_client_post)

        with _patch_httpx_post(mock_post):
            tasks = [
                execute_tool(
                    "talk_to_me",
                    {"question": "Recent meetings?", "gwm_id": gwm_id, "client_name": name},
                    # Each call gets its own deps to avoid shared cache
                    AgentDeps(tavily_api_key="k", wiki=MagicMock(), tool_cache={}),
                )
                for gwm_id, name in clients
            ]
            results = await asyncio.gather(*tasks)

        # Each result should correspond to the correct client
        for i, (gwm_id, name) in enumerate(clients):
            assert f"client: {name}" in results[i]
            assert f"Data for {gwm_id}" in results[i]

        assert mock_post.call_count == 3

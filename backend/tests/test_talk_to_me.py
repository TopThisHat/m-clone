"""Tests for the talk_to_me agent tool.

Covers:
  - Security: API key leak prevention, PII logging, injection safety
  - Validation: empty params, whitespace, feature gate
  - Error handling: timeout, 4xx, 5xx, retry, connection errors, malformed responses
  - Happy paths: successful call, caching, payload structure, auth headers
  - Edge cases: long questions, special chars, concurrency

Run: cd backend && uv run python -m pytest tests/test_talk_to_me.py -v
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

import app.agent.tools as tools_mod
from app.agent.tools import talk_to_me
from app.dependencies import AgentDeps


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def deps() -> AgentDeps:
    """Minimal AgentDeps with empty tool_cache and a mocked wiki."""
    return AgentDeps(
        tavily_api_key="test-tavily-key",
        wiki=MagicMock(),
        tool_cache={},
    )


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """Reset module-level semaphore between tests to avoid cross-contamination."""
    tools_mod._talktome_semaphore = None
    yield
    tools_mod._talktome_semaphore = None


@pytest.fixture
def mock_settings():
    """Patch app.config.settings with TalkToMe-specific test values."""
    mock = MagicMock()
    mock.talktome_api_url = "https://talktome.test/api/query"
    mock.talktome_api_key = "sk-test-secret-key-12345"
    mock.talktome_timeout_seconds = 10.0
    mock.talktome_max_concurrency = 5
    with patch("app.agent.tools.settings", mock):
        yield mock


@pytest.fixture
def mock_settings_no_url():
    """Patch settings with empty talktome_api_url (feature gate off)."""
    mock = MagicMock()
    mock.talktome_api_url = ""
    mock.talktome_api_key = ""
    mock.talktome_timeout_seconds = 10.0
    mock.talktome_max_concurrency = 5
    with patch("app.agent.tools.settings", mock):
        yield mock


@pytest.fixture
def mock_settings_no_key():
    """Patch settings with a URL but empty API key."""
    mock = MagicMock()
    mock.talktome_api_url = "https://talktome.test/api/query"
    mock.talktome_api_key = ""
    mock.talktome_timeout_seconds = 10.0
    mock.talktome_max_concurrency = 5
    with patch("app.agent.tools.settings", mock):
        yield mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_post(response: httpx.Response) -> AsyncMock:
    """Return an AsyncMock that acts as httpx.AsyncClient().post returning *response*."""
    mock_post = AsyncMock(return_value=response)
    return mock_post


def _build_response(
    status_code: int = 200,
    json_body: dict[str, Any] | None = None,
    text: str = "",
) -> httpx.Response:
    """Build an httpx.Response with the given status and body."""
    request = httpx.Request("POST", "https://talktome.test/api/query")
    if json_body is not None:
        return httpx.Response(status_code=status_code, request=request, json=json_body)
    return httpx.Response(status_code=status_code, request=request, text=text)


def _success_response(summary: str = "Client had 3 meetings last quarter.") -> httpx.Response:
    """Shortcut for a 200 response with a summary field."""
    return _build_response(status_code=200, json_body={"summary": summary})


def _error_response(status_code: int) -> httpx.Response:
    """Shortcut for an error response."""
    return _build_response(status_code=status_code, json_body={"error": "fail"})


def _patch_httpx_post(mock_post: AsyncMock):
    """Context manager that patches httpx.AsyncClient to use *mock_post*."""
    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.agent.tools.httpx.AsyncClient", return_value=mock_client)


# ---------------------------------------------------------------------------
# Security Tests
# ---------------------------------------------------------------------------

class TestSecurity:
    """Verify API keys and PII are never leaked to callers or logs."""

    @pytest.mark.asyncio
    async def test_api_key_not_in_error_response(self, deps, mock_settings):
        """Error messages returned to the user must not contain the API key."""
        api_key = mock_settings.talktome_api_key  # "sk-test-secret-key-12345"

        # Trigger a 500 error — the returned message must not contain the key
        resp = _error_response(500)
        mock_post = _mock_post(resp)
        mock_post.return_value = resp
        # raise_for_status will raise HTTPStatusError
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "What meetings?", "GWM-001", "Acme Corp")

        assert api_key not in result

    @pytest.mark.asyncio
    async def test_api_key_not_in_exception_trace(self, deps, mock_settings):
        """Internal exceptions must not embed the API key in their message."""
        api_key = mock_settings.talktome_api_key

        # Force a connection error and capture any exception
        mock_post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "What meetings?", "GWM-001", "Acme Corp")

        # The function should never raise, but verify the return string is clean
        assert api_key not in result

    @pytest.mark.asyncio
    async def test_pii_not_logged_above_debug(self, deps, mock_settings):
        """Response bodies (potential PII) must not appear in INFO/WARNING logs."""
        pii_summary = "John Smith discussed $5M deal with Jane Doe"
        resp = _success_response(summary=pii_summary)
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            with patch.object(tools_mod.logger, "info") as mock_info, \
                 patch.object(tools_mod.logger, "warning") as mock_warning, \
                 patch.object(tools_mod.logger, "error") as mock_error:
                await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        # Check that no log call at INFO/WARNING/ERROR contains the PII summary
        for mock_log in (mock_info, mock_warning, mock_error):
            for call in mock_log.call_args_list:
                log_msg = str(call)
                assert pii_summary not in log_msg

    @pytest.mark.asyncio
    async def test_injection_passed_as_json_value(self, deps, mock_settings):
        """SQL/prompt injection in `question` is sent as a JSON string value, not interpolated."""
        injection = "'; DROP TABLE users; --"
        resp = _success_response(summary="No relevant data.")
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            await talk_to_me(deps, injection, "GWM-001", "Acme Corp")

        # Verify the injection string was passed as-is in the JSON payload
        call_kwargs = mock_post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_json["question"] == injection


# ---------------------------------------------------------------------------
# Parameter Validation Tests
# ---------------------------------------------------------------------------

class TestParameterValidation:
    """Validate that bad inputs are rejected before any HTTP call."""

    VALIDATION_MSG = "Missing required parameter"

    @pytest.mark.asyncio
    async def test_empty_question_rejected(self, deps, mock_settings):
        """Empty string for `question` should return a validation error."""
        result = await talk_to_me(deps, "", "GWM-001", "Acme Corp")
        assert self.VALIDATION_MSG in result

    @pytest.mark.asyncio
    async def test_empty_gwm_id_rejected(self, deps, mock_settings):
        """Empty string for `gwm_id` should return a validation error."""
        result = await talk_to_me(deps, "What meetings?", "", "Acme Corp")
        assert self.VALIDATION_MSG in result

    @pytest.mark.asyncio
    async def test_empty_client_name_rejected(self, deps, mock_settings):
        """Empty string for `client_name` should return a validation error."""
        result = await talk_to_me(deps, "What meetings?", "GWM-001", "")
        assert self.VALIDATION_MSG in result

    @pytest.mark.asyncio
    async def test_whitespace_only_question_rejected(self, deps, mock_settings):
        """Whitespace-only `question` should be rejected as empty."""
        result = await talk_to_me(deps, "   \t\n  ", "GWM-001", "Acme Corp")
        assert self.VALIDATION_MSG in result

    @pytest.mark.asyncio
    async def test_whitespace_only_gwm_id_rejected(self, deps, mock_settings):
        """Whitespace-only `gwm_id` should be rejected as empty."""
        result = await talk_to_me(deps, "What meetings?", "   ", "Acme Corp")
        assert self.VALIDATION_MSG in result


# ---------------------------------------------------------------------------
# Feature Gate Tests
# ---------------------------------------------------------------------------

class TestFeatureGate:
    """Verify tool is disabled when talktome_api_url is not configured."""

    @pytest.mark.asyncio
    async def test_returns_error_when_url_not_configured(self, deps, mock_settings_no_url):
        """When talktome_api_url is empty, return a config error string."""
        result = await talk_to_me(deps, "What meetings?", "GWM-001", "Acme Corp")
        assert "not configured" in result.lower()


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Verify each HTTP error code returns a user-friendly message."""

    @pytest.mark.asyncio
    async def test_timeout_returns_friendly_message(self, deps, mock_settings):
        """httpx.TimeoutException should return a timeout message with seconds."""
        mock_post = AsyncMock(
            side_effect=httpx.ReadTimeout("timed out"),
        )
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "timed out" in result.lower()
        assert "10" in result  # talktome_timeout_seconds = 10.0

    @pytest.mark.asyncio
    async def test_401_returns_auth_failure(self, deps, mock_settings):
        """HTTP 401 should return an authentication failure message."""
        resp = _error_response(401)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "authentication failed" in result.lower()

    @pytest.mark.asyncio
    async def test_403_returns_auth_failure(self, deps, mock_settings):
        """HTTP 403 should return an authorization failure message."""
        resp = _error_response(403)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "authentication failed" in result.lower()

    @pytest.mark.asyncio
    async def test_404_returns_not_found_with_client_name(self, deps, mock_settings):
        """HTTP 404 should mention the client_name in the not-found message."""
        resp = _error_response(404)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "Acme Corp" in result

    @pytest.mark.asyncio
    async def test_429_returns_rate_limit_message(self, deps, mock_settings):
        """HTTP 429 should return a rate-limit message."""
        resp = _error_response(429)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "rate-limited" in result.lower()

    @pytest.mark.asyncio
    async def test_500_returns_service_error(self, deps, mock_settings):
        """HTTP 500 should return a generic service error message."""
        resp = _error_response(500)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "HTTP 500" in result

    @pytest.mark.asyncio
    async def test_502_triggers_retry_then_fails(self, deps, mock_settings):
        """HTTP 502 should trigger one retry; if retry also 502, return error."""
        resp = _error_response(502)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post), \
             patch("app.agent.tools.asyncio.sleep", new_callable=AsyncMock):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "HTTP 502" in result
        assert mock_post.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_503_triggers_retry_then_fails(self, deps, mock_settings):
        """HTTP 503 should trigger one retry; if retry also 503, return error."""
        resp = _error_response(503)
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post), \
             patch("app.agent.tools.asyncio.sleep", new_callable=AsyncMock):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "HTTP 503" in result
        assert mock_post.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_connection_error_returns_network_message(self, deps, mock_settings):
        """httpx.ConnectError should return a network failure message."""
        mock_post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused"),
        )
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "unreachable" in result.lower()

    @pytest.mark.asyncio
    async def test_malformed_response_missing_summary(self, deps, mock_settings):
        """JSON response without `summary` key should be handled gracefully."""
        resp = _build_response(200, json_body={"other": "data"})
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "unexpected response format" in result.lower()

    @pytest.mark.asyncio
    async def test_malformed_response_non_json(self, deps, mock_settings):
        """Non-JSON response body should be handled gracefully."""
        resp = _build_response(200, json_body={"summary": "ok"})
        # Override .json() to raise ValueError (simulates non-JSON body)
        resp.json = MagicMock(side_effect=ValueError("No JSON"))  # type: ignore[method-assign]
        mock_post = _mock_post(resp)
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert "unexpected response format" in result.lower()


# ---------------------------------------------------------------------------
# Happy Path Tests
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Verify correct behavior for successful API interactions."""

    @pytest.mark.asyncio
    async def test_successful_call_returns_formatted_summary(self, deps, mock_settings):
        """Successful call should return '**TalkToMe Insight** (client: X)\\n\\nSummary'."""
        resp = _success_response(summary="Met on 2024-01-15 to discuss portfolio.")
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Latest meeting notes?", "GWM-001", "Acme Corp")

        assert result == "**TalkToMe Insight** (client: Acme Corp)\n\nMet on 2024-01-15 to discuss portfolio."

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self, deps, mock_settings):
        """Second call with same params should return cached result, no HTTP call."""
        cached = "**TalkToMe Insight** (client: Acme Corp)\n\nCached summary."
        deps.tool_cache[("talk_to_me", "GWM-001", "recent meetings?")] = cached

        mock_post = AsyncMock()
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        assert result == cached
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_case_insensitive_cache_hit(self, deps, mock_settings):
        """Cache lookup should be case-insensitive on the question."""
        cached = "**TalkToMe Insight** (client: Acme Corp)\n\nCached."
        deps.tool_cache[("talk_to_me", "GWM-001", "recent meetings?")] = cached

        mock_post = AsyncMock()
        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "RECENT MEETINGS?", "GWM-001", "Acme Corp")

        assert result == cached
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_populated_after_success(self, deps, mock_settings):
        """After a successful call, deps.tool_cache should contain the result."""
        resp = _success_response(summary="Had 3 meetings.")
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Recent meetings?", "GWM-001", "Acme Corp")

        cache_key = ("talk_to_me", "GWM-001", "recent meetings?")
        assert cache_key in deps.tool_cache
        assert deps.tool_cache[cache_key] == result

    @pytest.mark.asyncio
    async def test_payload_matches_api_contract(self, deps, mock_settings):
        """POST body should match: {"question", "id", "context": {"client_id"}}."""
        resp = _success_response()
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            await talk_to_me(deps, "Any meetings?", "GWM-042", "John Smith")

        sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert sent_json["question"] == "Any meetings?"
        assert isinstance(sent_json["id"], str) and len(sent_json["id"]) == 36  # UUID
        assert sent_json["context"] == {"client_id": "GWM-042"}
        assert set(sent_json.keys()) == {"question", "id", "context"}

    @pytest.mark.asyncio
    async def test_bearer_token_sent_when_configured(self, deps, mock_settings):
        """When talktome_api_key is set, Authorization: Bearer <key> header is sent."""
        resp = _success_response()
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        sent_headers = mock_post.call_args.kwargs.get("headers") or mock_post.call_args[1].get("headers")
        assert sent_headers["Authorization"] == "Bearer sk-test-secret-key-12345"

    @pytest.mark.asyncio
    async def test_no_auth_header_when_key_empty(self, deps, mock_settings_no_key):
        """When talktome_api_key is empty, no Authorization header should be sent."""
        resp = _success_response()
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        sent_headers = mock_post.call_args.kwargs.get("headers") or mock_post.call_args[1].get("headers")
        assert "Authorization" not in sent_headers

    @pytest.mark.asyncio
    async def test_empty_summary_returns_no_records_message(self, deps, mock_settings):
        """Empty summary string should return a 'no interactions found' message."""
        resp = _build_response(200, json_body={"summary": "   "})
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        assert "No relevant interaction records" in result
        assert "Acme Corp" in result

    @pytest.mark.asyncio
    async def test_502_retry_succeeds_on_second_attempt(self, deps, mock_settings):
        """First call returns 502, retry returns 200 — should succeed."""
        resp_502 = _error_response(502)
        resp_200 = _success_response(summary="Retry worked.")
        mock_post = AsyncMock(side_effect=[resp_502, resp_200])

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        assert "TalkToMe Insight" in result
        assert "Retry worked." in result
        assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary conditions, concurrency, and unusual inputs."""

    @pytest.mark.asyncio
    async def test_very_long_question(self, deps, mock_settings):
        """A 10,000-character question should be handled gracefully."""
        long_q = "a" * 10_000
        resp = _success_response(summary="Summary for long question.")
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, long_q, "GWM-001", "Acme Corp")

        assert "TalkToMe Insight" in result
        # Verify the full question was sent in the payload
        sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert sent_json["question"] == long_q

    @pytest.mark.asyncio
    async def test_special_characters_in_question(self, deps, mock_settings):
        """Unicode, newlines, and HTML tags in question should not break the call."""
        special_q = 'What about "Müller & Söhne"?\n<script>alert(1)</script>\t日本語'
        resp = _success_response(summary="Found 2 interactions.")
        mock_post = _mock_post(resp)

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, special_q, "GWM-001", "Acme Corp")

        assert "TalkToMe Insight" in result
        sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert sent_json["question"] == special_q.strip()

    @pytest.mark.asyncio
    async def test_concurrent_calls_no_cross_contamination(self, deps, mock_settings):
        """5 parallel calls for different clients should return correct results."""
        clients = [
            ("GWM-001", "Alpha Corp"),
            ("GWM-002", "Beta Inc"),
            ("GWM-003", "Gamma LLC"),
            ("GWM-004", "Delta Ltd"),
            ("GWM-005", "Epsilon SA"),
        ]

        async def _side_effect(*args: Any, **kwargs: Any) -> httpx.Response:
            sent_json = kwargs.get("json", {})
            client_id = sent_json.get("context", {}).get("client_id", "")
            summary = f"Summary for {client_id}"
            return _build_response(200, json_body={"summary": summary})

        mock_post = AsyncMock(side_effect=_side_effect)

        with _patch_httpx_post(mock_post):
            tasks = [
                talk_to_me(
                    AgentDeps(tavily_api_key="k", wiki=MagicMock(), tool_cache={}),
                    "Recent meetings?", gwm_id, name,
                )
                for gwm_id, name in clients
            ]
            results = await asyncio.gather(*tasks)

        for i, (gwm_id, name) in enumerate(clients):
            assert f"client: {name}" in results[i]
            assert f"Summary for {gwm_id}" in results[i]

    @pytest.mark.asyncio
    async def test_semaphore_backpressure(self, deps, mock_settings):
        """6+ concurrent calls should all complete (semaphore queues, not rejects)."""
        mock_settings.talktome_max_concurrency = 2  # tight limit

        call_count = 0

        async def _counting_post(*args: Any, **kwargs: Any) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # simulate latency
            return _success_response("ok")

        mock_post = AsyncMock(side_effect=_counting_post)

        with _patch_httpx_post(mock_post):
            tasks = [
                talk_to_me(
                    AgentDeps(tavily_api_key="k", wiki=MagicMock(), tool_cache={}),
                    f"Question {i}", f"GWM-{i:03d}", f"Client {i}",
                )
                for i in range(6)
            ]
            results = await asyncio.gather(*tasks)

        # All 6 calls should complete successfully despite semaphore limit of 2
        assert len(results) == 6
        assert all("TalkToMe Insight" in r for r in results)
        assert call_count == 6

    @pytest.mark.asyncio
    async def test_dns_resolution_failure(self, deps, mock_settings):
        """DNS failure should return a network error message, not raise."""
        mock_post = AsyncMock(
            side_effect=httpx.ConnectError("Name or service not known"),
        )

        with _patch_httpx_post(mock_post):
            result = await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        assert "unreachable" in result.lower()

"""Tests for user SID threading through agent dependencies and talk_to_me.

Validates that the user's session ID (SID) is properly threaded from
the request context through AgentDeps into the talk_to_me tool payload,
with a UUID fallback when no SID is available.

Coverage:
  - AgentDeps dataclass has user_sid field
  - get_agent_deps factory function accepts user_sid param
  - talk_to_me payload uses SID when present
  - talk_to_me payload falls back to UUID when no SID
  - Correlation ID (UUID) preserved for logging regardless of SID

Run: cd backend && uv run python -m pytest tests/test_user_sid_threading.py -v
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

import app.agent.tools as tools_mod
from app.agent.tools import talk_to_me
from app.dependencies import AgentDeps, get_agent_deps


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Helpers (borrowed patterns from test_talk_to_me.py)
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _build_response(status_code: int = 200, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://talktome.test/api/query")
    if json_body is not None:
        return httpx.Response(status_code=status_code, request=request, json=json_body)
    return httpx.Response(status_code=status_code, request=request, text="")


def _success_response(summary: str = "Client had 3 meetings.") -> httpx.Response:
    return _build_response(200, json_body={"summary": summary})


def _patch_httpx_post(mock_post: AsyncMock):
    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.agent.tools.httpx.AsyncClient", return_value=mock_client)


def _mock_settings():
    mock = MagicMock()
    mock.talktome_api_url = "https://talktome.test/api/query"
    mock.talktome_api_key = "sk-test-key"
    mock.talktome_timeout_seconds = 10.0
    mock.talktome_max_concurrency = 5
    return mock


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """Reset module-level semaphore between tests."""
    tools_mod._talktome_semaphore = None
    yield
    tools_mod._talktome_semaphore = None


# ---------------------------------------------------------------------------
# AgentDeps user_sid Field
# ---------------------------------------------------------------------------

class TestAgentDepsUserSid:
    """Verify AgentDeps dataclass has the user_sid field."""

    def test_agent_deps_has_user_sid_field(self):
        """The AgentDeps dataclass must have a 'user_sid' field so that
        the user's session identity can be passed to downstream tools
        (especially talk_to_me) for per-user attribution and audit logging.

        Spec ref: m-clone-v936, user SID threading — data model.
        """
        deps = AgentDeps(
            tavily_api_key="test-key",
            wiki=MagicMock(),
        )
        # user_sid should exist as a field and default to None
        assert hasattr(deps, "user_sid")
        assert deps.user_sid is None

        # Setting it explicitly should work
        deps_with_sid = AgentDeps(
            tavily_api_key="test-key",
            wiki=MagicMock(),
            user_sid="my-sid-123",
        )
        assert deps_with_sid.user_sid == "my-sid-123"


# ---------------------------------------------------------------------------
# get_agent_deps Factory
# ---------------------------------------------------------------------------

class TestGetAgentDepsFactory:
    """Verify get_agent_deps accepts and threads user_sid."""

    def test_get_agent_deps_accepts_user_sid(self):
        """The get_agent_deps() factory function must accept a user_sid
        keyword argument and set it on the returned AgentDeps instance.
        When user_sid is not provided, it must default to None.

        Spec ref: m-clone-v936, user SID threading — factory function.
        """
        # With user_sid provided
        deps = get_agent_deps(user_sid="test-sid-456")
        assert deps.user_sid == "test-sid-456"

        # Without user_sid — should default to None
        deps_default = get_agent_deps()
        assert deps_default.user_sid is None


# ---------------------------------------------------------------------------
# talk_to_me Payload — SID Present
# ---------------------------------------------------------------------------

class TestTalkToMePayloadWithSid:
    """Verify SID is used in the talk_to_me payload when available."""

    @pytest.mark.asyncio
    async def test_talk_to_me_payload_uses_sid_when_present(self):
        """When AgentDeps.user_sid is set, the talk_to_me tool must include
        the SID in its POST payload 'id' field so the TalkToMe API can
        attribute the query to a specific user.

        Spec ref: m-clone-v936, user SID threading — payload contract.
        """
        deps = AgentDeps(
            tavily_api_key="test-key",
            wiki=MagicMock(),
            tool_cache={},
            user_sid="user-sid-789",
        )

        resp = _success_response()
        mock_post = AsyncMock(return_value=resp)

        mock_settings = _mock_settings()

        with patch("app.agent.tools.settings", mock_settings), \
             _patch_httpx_post(mock_post):
            await talk_to_me(deps, "What meetings?", "GWM-001", "Test Client")

        # Extract the JSON payload sent to the API
        call_kwargs = mock_post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_json["id"] == "user-sid-789"


# ---------------------------------------------------------------------------
# talk_to_me Payload — UUID Fallback
# ---------------------------------------------------------------------------

class TestTalkToMePayloadFallback:
    """Verify UUID fallback when no SID is available."""

    @pytest.mark.asyncio
    async def test_talk_to_me_payload_falls_back_to_uuid(self):
        """When AgentDeps.user_sid is None or empty, the talk_to_me tool
        must fall back to generating a random UUID for the 'id' field in
        the POST payload, preserving the existing behavior.

        Spec ref: m-clone-v936, user SID threading — UUID fallback.
        """
        deps = AgentDeps(
            tavily_api_key="test-key",
            wiki=MagicMock(),
            tool_cache={},
            user_sid=None,
        )

        resp = _success_response()
        mock_post = AsyncMock(return_value=resp)

        mock_settings = _mock_settings()

        with patch("app.agent.tools.settings", mock_settings), \
             _patch_httpx_post(mock_post):
            await talk_to_me(deps, "What meetings?", "GWM-001", "Test Client")

        call_kwargs = mock_post.call_args
        sent_json = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")

        # The id field should be a valid UUID (36 chars with hyphens)
        assert _UUID_RE.match(sent_json["id"]), (
            f"Expected a UUID when user_sid is None, got: {sent_json['id']!r}"
        )


# ---------------------------------------------------------------------------
# Correlation ID Preservation
# ---------------------------------------------------------------------------

class TestCorrelationIdPreserved:
    """Verify UUID is still used for log correlation regardless of SID."""

    @pytest.mark.asyncio
    async def test_correlation_id_preserved_for_logging(self):
        """Even when user_sid is available and used in the payload, a UUID
        correlation ID must still be generated and used in log messages
        so that individual requests can be traced in logs independently
        of the user identity.

        Spec ref: m-clone-v936, user SID threading — logging correlation.
        """
        deps = AgentDeps(
            tavily_api_key="test-key",
            wiki=MagicMock(),
            tool_cache={},
            user_sid="user-sid-for-logging-test",
        )

        resp = _success_response()
        mock_post = AsyncMock(return_value=resp)

        mock_settings = _mock_settings()

        with patch("app.agent.tools.settings", mock_settings), \
             _patch_httpx_post(mock_post), \
             patch.object(tools_mod.logger, "info") as mock_info:
            await talk_to_me(deps, "Any meetings?", "GWM-001", "Acme Corp")

        # The logger.info should have been called with a correlation_id in extra
        # that is a UUID, not the user SID
        found_correlation_id = False
        for call in mock_info.call_args_list:
            extra = call.kwargs.get("extra", {})
            cid = extra.get("correlation_id")
            if cid is not None:
                # correlation_id must be a UUID even when SID is set
                assert _UUID_RE.match(cid), (
                    f"Expected correlation_id to be a UUID, got: {cid!r}"
                )
                # It must NOT be the user_sid (they serve different purposes)
                assert cid != "user-sid-for-logging-test"
                found_correlation_id = True

        assert found_correlation_id, (
            "Expected at least one log call with a 'correlation_id' in extra"
        )

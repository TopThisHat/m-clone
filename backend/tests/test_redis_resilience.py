"""
Unit tests for get_redis() Redis connection resilience.

Covers:
  1. Returns client immediately when Redis reachable on first attempt
  2. Retries with correct exponential backoff delays (1s, 2s)
  3. RuntimeError after all 3 attempts fail
  4. RuntimeError immediately when REDIS_URL is empty — no retry
  5. asyncio.Lock prevents duplicate client creation under concurrency
  6. Socket timeout parameters are passed to from_url()
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# These are unit tests — no database needed
@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_redis_state():
    """Reset module-level Redis singleton before and after each test."""
    import app.streams as mod
    mod._redis = None
    mod._redis_lock = None
    yield
    mod._redis = None
    mod._redis_lock = None


def _make_client(*, ping_raises=None) -> AsyncMock:
    """Helper: build a mock Redis client."""
    client = AsyncMock()
    if ping_raises is not None:
        client.ping = AsyncMock(side_effect=ping_raises)
    else:
        client.ping = AsyncMock(return_value=True)
    return client


# ---------------------------------------------------------------------------
# 1. Successful first attempt
# ---------------------------------------------------------------------------

class TestGetRedisSuccess:
    @pytest.mark.asyncio
    async def test_returns_client_on_first_attempt(self):
        """Returns the Redis client immediately when reachable — no sleep."""
        mock_client = _make_client()

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            result = await get_redis()

        assert result is mock_client
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_socket_timeout_params_passed_to_from_url(self):
        """from_url() called with the required socket timeout settings."""
        mock_client = _make_client()

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", return_value=mock_client) as mock_from_url,
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            await get_redis()

        mock_from_url.assert_called_once_with(
            "redis://localhost:6379",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            retry_on_timeout=True,
            health_check_interval=30,
        )

    @pytest.mark.asyncio
    async def test_ping_called_after_client_creation(self):
        """ping() is called to verify the connection before caching the client."""
        mock_client = _make_client()

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", return_value=mock_client),
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            await get_redis()

        mock_client.ping.assert_called_once()


# ---------------------------------------------------------------------------
# 2. Retry logic with correct backoff delays
# ---------------------------------------------------------------------------

class TestGetRedisRetry:
    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt_after_1s_backoff(self):
        """Sleeps 1s after first failure, then succeeds on second attempt."""
        attempt = 0

        def from_url_factory(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            client = AsyncMock()
            if attempt == 1:
                client.ping = AsyncMock(side_effect=ConnectionError("refused"))
            else:
                client.ping = AsyncMock(return_value=True)
            return client

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", side_effect=from_url_factory),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            result = await get_redis()

        assert result is not None
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_succeeds_on_third_attempt_with_1s_2s_backoffs(self):
        """Sleeps 1s then 2s when first two attempts fail, succeeds on third."""
        attempt = 0

        def from_url_factory(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            client = AsyncMock()
            if attempt < 3:
                client.ping = AsyncMock(side_effect=ConnectionError("refused"))
            else:
                client.ping = AsyncMock(return_value=True)
            return client

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", side_effect=from_url_factory),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            await get_redis()

        assert mock_sleep.call_count == 2
        sleep_delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_delays == [1, 2]

    @pytest.mark.asyncio
    async def test_no_sleep_after_final_failed_attempt(self):
        """Does not sleep after the 3rd (final) failed attempt — fails fast."""
        mock_client = _make_client(ping_raises=ConnectionError("refused"))

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            with pytest.raises(RuntimeError):
                await get_redis()

        # Sleeps only after attempt 1 (1s) and attempt 2 (2s), not attempt 3
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# 3. RuntimeError after exhausting all retries
# ---------------------------------------------------------------------------

class TestGetRedisExhausted:
    @pytest.mark.asyncio
    async def test_raises_runtime_error_after_three_failures(self):
        """RuntimeError raised with correct message after all 3 attempts fail."""
        mock_client = _make_client(ping_raises=ConnectionError("refused"))

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            with pytest.raises(RuntimeError, match="Redis connection failed after 3 retries"):
                await get_redis()

    @pytest.mark.asyncio
    async def test_exactly_three_connection_attempts_made(self):
        """Exactly 3 connection attempts before giving up."""
        attempt_count = 0

        def from_url_factory(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            client = AsyncMock()
            client.ping = AsyncMock(side_effect=ConnectionError("refused"))
            return client

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", side_effect=from_url_factory),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            with pytest.raises(RuntimeError):
                await get_redis()

        assert attempt_count == 3


# ---------------------------------------------------------------------------
# 4. Fail-fast when REDIS_URL is not configured
# ---------------------------------------------------------------------------

class TestGetRedisNoUrl:
    @pytest.mark.asyncio
    async def test_raises_runtime_error_for_empty_url(self):
        """RuntimeError raised immediately when REDIS_URL is empty — no retry."""
        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url") as mock_from_url,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            s.redis_url = ""
            from app.streams import get_redis
            with pytest.raises(RuntimeError, match="REDIS_URL is not configured"):
                await get_redis()

        mock_from_url.assert_not_called()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_runtime_error_for_none_url(self):
        """RuntimeError raised immediately when REDIS_URL is None — no retry."""
        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url") as mock_from_url,
        ):
            s.redis_url = None
            from app.streams import get_redis
            with pytest.raises(RuntimeError, match="REDIS_URL is not configured"):
                await get_redis()

        mock_from_url.assert_not_called()


# ---------------------------------------------------------------------------
# 5. asyncio.Lock prevents concurrent double-initialization
# ---------------------------------------------------------------------------

class TestGetRedisLock:
    @pytest.mark.asyncio
    async def test_concurrent_calls_create_only_one_client(self):
        """Two concurrent get_redis() calls result in exactly one client being created."""
        creation_count = 0

        def from_url_factory(*args, **kwargs):
            nonlocal creation_count
            creation_count += 1

            async def slow_ping():
                # Yield once to allow other coroutines to attempt lock acquisition
                await asyncio.sleep(0)
                return True

            client = AsyncMock()
            client.ping = slow_ping
            return client

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", side_effect=from_url_factory),
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            results = await asyncio.gather(get_redis(), get_redis())

        # Lock + double-check ensures only one client is created
        assert creation_count == 1
        # Both callers receive the same singleton
        assert results[0] is results[1]

    @pytest.mark.asyncio
    async def test_second_call_returns_cached_client(self):
        """Second sequential call returns the cached client without creating a new one."""
        creation_count = 0

        def from_url_factory(*args, **kwargs):
            nonlocal creation_count
            creation_count += 1
            return _make_client()

        with (
            patch("app.config.settings") as s,
            patch("redis.asyncio.from_url", side_effect=from_url_factory),
        ):
            s.redis_url = "redis://localhost:6379"
            from app.streams import get_redis
            first = await get_redis()
            second = await get_redis()

        assert creation_count == 1
        assert first is second

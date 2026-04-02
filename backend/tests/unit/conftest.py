"""Conftest for unit tests -- no database connection required."""
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    """Override parent conftest fixture -- unit tests need no DB."""
    yield

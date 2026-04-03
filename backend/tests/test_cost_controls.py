"""Tests for cost controls and circuit breaker (Sprint 2, Tasks 6.1-6.7).

Validates:
  - RunState.tool_call_count initializes to 0
  - RunState.tool_call_count can be incremented (single and batch)
  - RunState.estimated_cost accumulates correctly
  - estimate_turn_cost calculation matches expected formula
  - _TOOL_CALL_COST_USD constant is set to the expected value
  - Circuit breaker constant (_MAX_TOOL_CALLS) matches settings
  - Settings.max_tool_calls_per_turn has correct default

Run: cd backend && uv run python -m pytest tests/test_cost_controls.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.agent.run_state import (
    RunState,
    _TOOL_CALL_COST_USD,
    estimate_turn_cost,
)
from app.config import Settings


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# RunState — tool_call_count defaults
# ---------------------------------------------------------------------------

class TestToolCallCountDefaults:
    """Verify RunState.tool_call_count initializes correctly."""

    def test_tool_call_count_starts_at_zero(self):
        """RunState.tool_call_count must default to 0 so the circuit
        breaker starts with a clean slate for every new execution.
        """
        state = RunState()
        assert state.tool_call_count == 0

    def test_estimated_cost_starts_at_zero(self):
        """RunState.estimated_cost must default to 0.0 so cost tracking
        accumulates from zero for every new execution.
        """
        state = RunState()
        assert state.estimated_cost == 0.0


# ---------------------------------------------------------------------------
# RunState — tool_call_count increment
# ---------------------------------------------------------------------------

class TestToolCallCountIncrement:
    """Verify RunState.tool_call_count supports the increment patterns
    used by the orchestrator loop."""

    def test_tool_call_count_increment_by_one(self):
        """Single tool call in a turn increments count by 1, matching
        the case where len(sorted_tcs) == 1 in the orchestrator.
        """
        state = RunState()
        state.tool_call_count += 1
        assert state.tool_call_count == 1

    def test_tool_call_count_increment_by_batch(self):
        """Parallel tool calls in a turn increment count by the batch
        size, matching deps.run_state.tool_call_count += len(sorted_tcs).
        """
        state = RunState()
        state.tool_call_count += 4  # simulate 4 parallel tool calls
        assert state.tool_call_count == 4

    def test_tool_call_count_accumulates_across_turns(self):
        """Multiple turns accumulate tool calls correctly, simulating
        the orchestrator loop executing tools across several iterations.
        """
        state = RunState()
        state.tool_call_count += 3  # turn 1: 3 parallel calls
        state.tool_call_count += 1  # turn 2: 1 sequential call
        state.tool_call_count += 5  # turn 3: 5 parallel calls
        assert state.tool_call_count == 9

    def test_tool_call_count_large_batch(self):
        """Large batch increments work correctly for data processing
        modes that may issue many tool calls per turn.
        """
        state = RunState()
        state.tool_call_count += 50
        state.tool_call_count += 50
        assert state.tool_call_count == 100


# ---------------------------------------------------------------------------
# estimate_turn_cost — calculation
# ---------------------------------------------------------------------------

class TestEstimateTurnCost:
    """Verify estimate_turn_cost computes cost correctly."""

    def test_estimate_turn_cost_zero_calls(self):
        """Zero tool calls must produce zero cost."""
        assert estimate_turn_cost(0) == 0.0

    def test_estimate_turn_cost_single_call(self):
        """A single tool call must cost exactly _TOOL_CALL_COST_USD."""
        cost = estimate_turn_cost(1)
        assert cost == _TOOL_CALL_COST_USD

    def test_estimate_turn_cost_multiple_calls(self):
        """Cost scales linearly with tool call count."""
        cost = estimate_turn_cost(5)
        assert cost == pytest.approx(5 * _TOOL_CALL_COST_USD)

    def test_estimate_turn_cost_large_batch(self):
        """Large batch cost is computed correctly without overflow or
        floating point drift beyond acceptable tolerance.
        """
        cost = estimate_turn_cost(200)
        assert cost == pytest.approx(200 * _TOOL_CALL_COST_USD)

    def test_estimate_turn_cost_returns_float(self):
        """estimate_turn_cost must always return a float for consistent
        accumulation in RunState.estimated_cost.
        """
        result = estimate_turn_cost(3)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Cost constant
# ---------------------------------------------------------------------------

class TestCostConstant:
    """Verify the per-tool-call cost constant is set correctly."""

    def test_tool_call_cost_usd_value(self):
        """_TOOL_CALL_COST_USD must be 0.02 (conservative average per
        tool call including tokens in and out).
        """
        assert _TOOL_CALL_COST_USD == 0.02

    def test_tool_call_cost_usd_is_positive(self):
        """_TOOL_CALL_COST_USD must be a positive value to produce
        meaningful cost estimates.
        """
        assert _TOOL_CALL_COST_USD > 0


# ---------------------------------------------------------------------------
# RunState — estimated_cost accumulation with estimate_turn_cost
# ---------------------------------------------------------------------------

class TestEstimatedCostAccumulation:
    """Verify RunState.estimated_cost accumulates correctly when using
    estimate_turn_cost, matching the orchestrator pattern:
        deps.run_state.estimated_cost += estimate_turn_cost(len(sorted_tcs))
    """

    def test_cost_accumulation_single_turn(self):
        """Cost accumulates correctly for a single turn with multiple
        tool calls.
        """
        state = RunState()
        tool_calls_in_turn = 3
        state.estimated_cost += estimate_turn_cost(tool_calls_in_turn)
        assert state.estimated_cost == pytest.approx(3 * _TOOL_CALL_COST_USD)

    def test_cost_accumulation_multiple_turns(self):
        """Cost accumulates correctly across multiple turns, simulating
        the full orchestrator loop.
        """
        state = RunState()
        turns = [2, 4, 1, 3]  # tool calls per turn
        for n in turns:
            state.tool_call_count += n
            state.estimated_cost += estimate_turn_cost(n)
        assert state.tool_call_count == sum(turns)
        assert state.estimated_cost == pytest.approx(sum(turns) * _TOOL_CALL_COST_USD)


# ---------------------------------------------------------------------------
# Circuit breaker constant — _MAX_TOOL_CALLS
# ---------------------------------------------------------------------------

class TestCircuitBreakerConstant:
    """Verify the circuit breaker constant is wired to settings."""

    def test_max_tool_calls_matches_settings_default(self):
        """_MAX_TOOL_CALLS in agent.py must equal settings.max_tool_calls_per_turn
        (200 by default). We import it here to verify the wiring.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        assert _MAX_TOOL_CALLS == 200

    def test_max_tool_calls_equals_settings(self):
        """_MAX_TOOL_CALLS must be sourced from settings so it is configurable
        via environment variables at deploy time.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        from app.config import settings
        assert _MAX_TOOL_CALLS == settings.max_tool_calls_per_turn

    def test_settings_max_tool_calls_per_turn_default(self):
        """Settings.max_tool_calls_per_turn must default to 200, matching
        the highest mode limit (TASK_EXECUTION).
        """
        # Check the field default on the model class
        field_info = Settings.model_fields["max_tool_calls_per_turn"]
        assert field_info.default == 200

    def test_circuit_breaker_matches_highest_mode_limit(self):
        """The default circuit breaker limit (200) must equal the highest
        max_tool_calls across all RunnerConfig presets.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        from app.agent.runner_config import RUNNER_CONFIGS

        highest = max(cfg.max_tool_calls for cfg in RUNNER_CONFIGS.values())
        assert _MAX_TOOL_CALLS == highest


# ---------------------------------------------------------------------------
# Circuit breaker — logic simulation
# ---------------------------------------------------------------------------

class TestCircuitBreakerLogic:
    """Simulate the circuit breaker check to verify it would trigger
    correctly in the orchestrator loop."""

    def test_circuit_breaker_does_not_trigger_below_limit(self):
        """When tool_call_count is below _MAX_TOOL_CALLS, the circuit
        breaker condition is False and the loop should continue.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        state = RunState()
        state.tool_call_count = _MAX_TOOL_CALLS - 1
        assert not (state.tool_call_count >= _MAX_TOOL_CALLS)

    def test_circuit_breaker_triggers_at_limit(self):
        """When tool_call_count equals _MAX_TOOL_CALLS, the circuit
        breaker condition is True and the loop should break.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        state = RunState()
        state.tool_call_count = _MAX_TOOL_CALLS
        assert state.tool_call_count >= _MAX_TOOL_CALLS

    def test_circuit_breaker_triggers_above_limit(self):
        """When tool_call_count exceeds _MAX_TOOL_CALLS (e.g. a batch
        increment pushed it past), the circuit breaker must still trigger.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        state = RunState()
        state.tool_call_count = _MAX_TOOL_CALLS + 10
        assert state.tool_call_count >= _MAX_TOOL_CALLS

    def test_circuit_breaker_allows_normal_research(self):
        """Normal research mode uses ~10-20 tool calls, well below the
        200 limit. The breaker must not interfere.
        """
        from app.agent.agent import _MAX_TOOL_CALLS
        state = RunState()
        # Simulate a typical research session
        for _ in range(5):  # 5 turns
            state.tool_call_count += 4  # 4 parallel calls each
        assert state.tool_call_count == 20
        assert not (state.tool_call_count >= _MAX_TOOL_CALLS)

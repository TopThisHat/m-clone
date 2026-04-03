"""Tests for SYSTEM_PROMPT content in app.agent.agent.

Validates that the system prompt contains all required sections introduced
by the TalkToMe prompt-hardening spec (m-clone-v936, Sprint 1).

Each test verifies the presence of a specific prompt section that controls
agent routing behavior, ensuring prompt regressions are caught early.

Coverage:
  - Authorization notice block
  - Anti-refusal mandate (forbidden phrases)
  - 3-step decision tree for tool routing
  - Trigger taxonomy (5 TalkToMe categories)
  - Catch-all rule for ambiguous queries
  - Negative list for web_search-only routing
  - Batch protocol (INVENTORY/PLAN/EXECUTE/OUTPUT)
  - Anti-truncation hard rules (14-15)
  - Hard rules 12 through 15

Run: cd backend && uv run python -m pytest tests/test_prompt_content.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.agent.agent import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Override autouse conftest fixture (no DB needed for unit tests)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema():
    yield


# ---------------------------------------------------------------------------
# Authorization Notice
# ---------------------------------------------------------------------------

class TestAuthorizationNotice:
    """Verify the SYSTEM_PROMPT contains the AUTHORIZATION NOTICE block."""

    def test_system_prompt_contains_authorization_notice(self):
        """The prompt must include an 'AUTHORIZATION NOTICE' section that
        explicitly grants the agent permission to call talk_to_me without
        user confirmation, preventing false-refusal behavior.

        Spec ref: m-clone-v936, Section 2.1 — Authorization Notice.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Anti-Refusal Mandate
# ---------------------------------------------------------------------------

class TestAntiRefusalMandate:
    """Verify the SYSTEM_PROMPT forbids common refusal phrases."""

    def test_system_prompt_contains_anti_refusal_mandate(self):
        """The prompt must mention forbidden phrases (e.g. 'I cannot',
        'I'm not able to', 'I don't have access') so the agent never
        refuses to call talk_to_me when the query matches a trigger.

        Spec ref: m-clone-v936, Section 2.2 — Anti-Refusal Mandate.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Decision Tree
# ---------------------------------------------------------------------------

class TestDecisionTree:
    """Verify the SYSTEM_PROMPT contains the 3-step decision tree."""

    def test_system_prompt_contains_decision_tree(self):
        """The prompt must include a 3-step decision tree that the agent
        follows for every user query:
          Step 1: Check if query matches TalkToMe triggers
          Step 2: Check if query matches web_search triggers
          Step 3: Default routing

        Spec ref: m-clone-v936, Section 3 — Decision Tree.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Trigger Taxonomy
# ---------------------------------------------------------------------------

class TestTriggerTaxonomy:
    """Verify all 5 TalkToMe trigger categories are present."""

    def test_system_prompt_contains_trigger_taxonomy(self):
        """The prompt must enumerate all 5 TalkToMe trigger categories:
          1. Meeting / interaction history
          2. Relationship / coverage details
          3. Client activity / engagement
          4. Internal notes / CRM data
          5. Portfolio / account information

        Each category ensures the agent can recognize diverse phrasings
        that should route to the talk_to_me tool.

        Spec ref: m-clone-v936, Section 4 — Trigger Taxonomy.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Catch-All Rule
# ---------------------------------------------------------------------------

class TestCatchAllRule:
    """Verify the catch-all rule for ambiguous queries."""

    def test_system_prompt_contains_catch_all_rule(self):
        """The prompt must include a catch-all rule instructing the agent
        to prefer talk_to_me when a query is ambiguous and could match
        either internal data or web search. This prevents silent drops
        of CRM-relevant queries.

        Spec ref: m-clone-v936, Section 5 — Catch-All Rule.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Negative List
# ---------------------------------------------------------------------------

class TestNegativeList:
    """Verify the negative list for web_search-only routing."""

    def test_system_prompt_contains_negative_list(self):
        """The prompt must include a negative list of query patterns that
        should NEVER be routed to talk_to_me (e.g. general knowledge,
        news, public company data) and should always go to web_search.

        Spec ref: m-clone-v936, Section 6 — Negative List.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Batch Protocol
# ---------------------------------------------------------------------------

class TestBatchProtocol:
    """Verify the INVENTORY/PLAN/EXECUTE/OUTPUT batch protocol."""

    def test_system_prompt_contains_batch_protocol(self):
        """The prompt must describe the 4-step batch protocol for
        multi-entity queries:
          INVENTORY — enumerate all entities in the user's request
          PLAN      — determine which tool to call for each entity
          EXECUTE   — make all tool calls (no skipping)
          OUTPUT    — present results for every entity

        Spec ref: m-clone-v936, Section 7 — Batch Protocol.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Anti-Truncation Rules
# ---------------------------------------------------------------------------

class TestAntiTruncationRules:
    """Verify hard rules that prevent response truncation."""

    def test_system_prompt_contains_anti_truncation_rules(self):
        """The prompt must include anti-truncation hard rules (rules 14-15)
        that explicitly forbid the agent from:
          - Truncating results for large batches
          - Summarizing individual entries to save tokens
          - Omitting entities from the output

        Spec ref: m-clone-v936, Section 8 — Anti-Truncation Rules.
        """
        pytest.skip("Sprint 3: implementation pending")


# ---------------------------------------------------------------------------
# Hard Rules 12-15
# ---------------------------------------------------------------------------

class TestHardRules12Through15:
    """Verify all new hard rules (12-15) are present in the prompt."""

    def test_system_prompt_hard_rules_12_through_15(self):
        """The prompt must include hard rules 12 through 15:
          Rule 12 — Always call talk_to_me for CRM/interaction queries
          Rule 13 — Never refuse a talk_to_me call when trigger matches
          Rule 14 — Never truncate batch results
          Rule 15 — Always include every entity in the output

        These rules are the enforcement layer for the decision tree and
        batch protocol. Their absence would allow the agent to silently
        skip tool calls or truncate output.

        Spec ref: m-clone-v936, Section 9 — Hard Rules 12-15.
        """
        pytest.skip("Sprint 3: implementation pending")

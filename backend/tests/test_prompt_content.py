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
  - Anti-truncation hard rules (13-14)
  - Hard rules 12 through 16

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
        assert "AUTHORIZATION NOTICE" in SYSTEM_PROMPT
        # Must mention that users are authorized financial professionals
        assert "authorized financial professionals" in SYSTEM_PROMPT
        # Must mention the client data tools by name
        assert "talk_to_me" in SYSTEM_PROMPT
        assert "lookup_client" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Anti-Refusal Mandate
# ---------------------------------------------------------------------------

class TestAntiRefusalMandate:
    """Verify the SYSTEM_PROMPT forbids common refusal phrases."""

    def test_system_prompt_contains_anti_refusal_mandate(self):
        """The prompt must mention forbidden phrases (e.g. 'sensitive data',
        'privacy concerns') so the agent never refuses to call talk_to_me
        when the query matches a trigger.

        Spec ref: m-clone-v936, Section 2.2 — Anti-Refusal Mandate.
        """
        assert "Anti-refusal mandate" in SYSTEM_PROMPT
        # Verify that the forbidden phrases are listed
        assert "sensitive data" in SYSTEM_PROMPT
        assert "privacy concerns" in SYSTEM_PROMPT
        assert "check with compliance" in SYSTEM_PROMPT
        assert "verify permissions" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Decision Tree
# ---------------------------------------------------------------------------

class TestDecisionTree:
    """Verify the SYSTEM_PROMPT contains the 3-step decision tree."""

    def test_system_prompt_contains_decision_tree(self):
        """The prompt must include a multi-step decision tree that the agent
        follows for every user query involving a person name:
          Step 1: Classify the person
          Step 2: Resolve GWM ID
          Step 3: Route to TalkToMe if applicable

        Spec ref: m-clone-v936, Section 3 — Decision Tree.
        """
        assert "Client Tool Decision Tree" in SYSTEM_PROMPT
        assert "Step 1" in SYSTEM_PROMPT
        assert "Step 2" in SYSTEM_PROMPT
        assert "Step 3" in SYSTEM_PROMPT
        # Verify the decision tree covers classification + routing
        assert "Classify the person" in SYSTEM_PROMPT
        assert "Resolve GWM ID" in SYSTEM_PROMPT
        assert "Route to TalkToMe" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Trigger Taxonomy
# ---------------------------------------------------------------------------

class TestTriggerTaxonomy:
    """Verify all 5 TalkToMe trigger categories are present."""

    def test_system_prompt_contains_trigger_taxonomy(self):
        """The prompt must enumerate all 5 TalkToMe trigger categories:
          1. Interaction history (meetings, calls, emails)
          2. Personal profile (family, interests, hobbies)
          3. Preferences and opinions (investment, risk, goals)
          4. Relationship context (account management, history)
          5. Behavioral signals (sentiment, concerns, engagement)

        Each category ensures the agent can recognize diverse phrasings
        that should route to the talk_to_me tool.

        Spec ref: m-clone-v936, Section 4 — Trigger Taxonomy.
        """
        assert "TalkToMe Trigger Taxonomy" in SYSTEM_PROMPT
        # Category 1
        assert "Category 1" in SYSTEM_PROMPT
        assert "Interaction history" in SYSTEM_PROMPT
        # Category 2
        assert "Category 2" in SYSTEM_PROMPT
        assert "Personal profile" in SYSTEM_PROMPT
        # Category 3
        assert "Category 3" in SYSTEM_PROMPT
        assert "Preferences and opinions" in SYSTEM_PROMPT
        # Category 4
        assert "Category 4" in SYSTEM_PROMPT
        assert "Relationship context" in SYSTEM_PROMPT
        # Category 5
        assert "Category 5" in SYSTEM_PROMPT
        assert "Behavioral signals" in SYSTEM_PROMPT


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
        assert "Catch-all" in SYSTEM_PROMPT
        # Must instruct to prefer talk_to_me for ambiguous queries
        assert "talk_to_me" in SYSTEM_PROMPT
        # The catch-all explicitly says to prefer internal data first
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "when in doubt" in prompt_lower


# ---------------------------------------------------------------------------
# Negative List
# ---------------------------------------------------------------------------

class TestNegativeList:
    """Verify the negative list for web_search-only routing."""

    def test_system_prompt_contains_negative_list(self):
        """The prompt must include a negative list of query patterns that
        should NEVER be routed to talk_to_me (e.g. public company data,
        stock prices, general industry research) and should always go
        to web_search.

        Spec ref: m-clone-v936, Section 6 — Negative List.
        """
        assert "Negative List" in SYSTEM_PROMPT
        # Must mention public company financials / stock prices as excluded
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "public company financials" in prompt_lower or "stock prices" in prompt_lower
        # Must route excluded items to web_search / get_financials
        assert "web_search" in SYSTEM_PROMPT


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
        assert "INVENTORY" in SYSTEM_PROMPT
        assert "PLAN" in SYSTEM_PROMPT
        assert "EXECUTE" in SYSTEM_PROMPT
        assert "OUTPUT" in SYSTEM_PROMPT
        # Verify these appear in the batch protocol section
        assert "Step 1" in SYSTEM_PROMPT
        assert "Step 2" in SYSTEM_PROMPT
        assert "Step 3" in SYSTEM_PROMPT
        assert "Step 4" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Anti-Truncation Rules
# ---------------------------------------------------------------------------

class TestAntiTruncationRules:
    """Verify hard rules that prevent response truncation."""

    def test_system_prompt_contains_anti_truncation_rules(self):
        """The prompt must include anti-truncation mandates that explicitly
        forbid the agent from:
          - Saying a file is 'too large'
          - Outputting only a subset of results
          - Summarizing instead of showing all results

        Spec ref: m-clone-v936, Section 8 — Anti-Truncation Rules.
        """
        # Check for the anti-truncation mandates section
        assert "Anti-truncation" in SYSTEM_PROMPT
        # Specific prohibitions
        prompt_lower = SYSTEM_PROMPT.lower()
        assert "too many rows" in prompt_lower or "too large" in prompt_lower
        assert "never truncate" in prompt_lower or "never say" in prompt_lower


# ---------------------------------------------------------------------------
# Hard Rules 12-16
# ---------------------------------------------------------------------------

class TestHardRules12Through16:
    """Verify all new hard rules (12-16) are present in the prompt."""

    def test_system_prompt_hard_rules_12_through_16(self):
        """The prompt must include hard rules 12 through 16:
          Rule 12 — Never add disclaimers about privacy/sensitivity for client tools
          Rule 13 — Never truncate, sample, or skip rows
          Rule 14 — Never tell the user a file is 'too large'
          Rule 15 — ask_clarification must be the first tool call if used
          Rule 16 — Call ask_clarification at most once per session

        These rules are the enforcement layer for the decision tree and
        batch protocol.

        Spec ref: m-clone-v936, Section 9 — Hard Rules 12-16.
        """
        # Verify hard rules section exists
        assert "Hard Rules" in SYSTEM_PROMPT

        # Rule 12 — never add disclaimers about privacy/data ethics for client tools
        assert "12." in SYSTEM_PROMPT
        # Rule 13 — never truncate, sample, or skip rows
        assert "13." in SYSTEM_PROMPT
        # Rule 14 — never tell the user a file is too large
        assert "14." in SYSTEM_PROMPT
        # Rule 15
        assert "15." in SYSTEM_PROMPT
        # Rule 16
        assert "16." in SYSTEM_PROMPT

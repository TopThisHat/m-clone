"""
Knowledge Graph Ontology for Private Banking — Sports Deal Origination.

This module is the single source of truth for:
  - Which entity types are permitted in the KG (closed set, hard limit)
  - Which relationship predicates are canonical per family (no unbounded growth)
  - How raw LLM-extracted predicates are normalized to canonical form
  - Which signals are high-value vs. droppable noise for deal origination
  - Anti-explosion rules that prevent unbounded KG growth over time

Design philosophy
-----------------
The private bank cares about *closing sports deals*.  Every entity type and
every predicate must earn its place by contributing to that purpose.

A graph that grows unbounded is a graph that becomes un-queryable.  Hard limits
force curation discipline — if a new concept matters, something less important
must be retired first.

Usage
-----
    from app.kg_ontology import (
        ENTITY_TYPES,
        RELATIONSHIP_FAMILIES,
        normalize_predicate,
        should_keep_relationship,
        should_keep_entity,
        get_lm_prompt_section,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
# 1. CONTROLLED ENTITY TYPES — closed set, hard limit = 10
# ─────────────────────────────────────────────────────────────────────────────
#
# Rule: no "other" catch-all.  If an entity cannot be classified into one of
# the types below, it is DROPPED from the KG.  This forces the LLM extraction
# prompt to be precise and prevents noise accumulation.
#
# Hard limit rationale: 10 types covers every entity class that directly
# touches a sports deal.  Adding more types requires retiring one.

ENTITY_TYPE_MAX = 10  # Hard ceiling — do not exceed without retiring a type


@dataclass(frozen=True)
class EntityTypeSpec:
    name: str
    # One-sentence rationale for why this type earns a place in a sports-deal KG
    rationale: str
    # Signals that this entity is present in a deal-relevant document
    keywords: list[str]
    # Minimum relevance score to retain in the KG (0.0 – 1.0)
    relevance_floor: float = 0.5


ENTITY_TYPES: dict[str, EntityTypeSpec] = {
    # ── People ──────────────────────────────────────────────────────────────
    "person": EntityTypeSpec(
        name="person",
        rationale=(
            "The primary deal-making unit.  Covers UHNW individuals, athletes,"
            " coaches, team executives, PE partners — anyone who signs, influences,"
            " or initiates a transaction."
        ),
        keywords=["CEO", "founder", "owner", "partner", "investor", "athlete",
                  "coach", "chairman", "director", "principal"],
        relevance_floor=0.4,  # Lower floor: person relevance is proven by their relationships
    ),

    # ── Organizations ────────────────────────────────────────────────────────
    "sports_team": EntityTypeSpec(
        name="sports_team",
        rationale=(
            "The core deal asset.  NFL, NBA, MLB, Premier League, F1 teams and"
            " franchises.  Kept separate from 'company' because valuation logic,"
            " league rules, and ownership transfer mechanics differ fundamentally."
        ),
        keywords=["FC", "SC", "team", "franchise", "club", "squad", "Racing",
                  "Athletics", "United", "City", "Lakers", "Cowboys", "Chiefs"],
        relevance_floor=0.6,
    ),
    "sports_league": EntityTypeSpec(
        name="sports_league",
        rationale=(
            "Leagues (NFL, NBA, EPL, F1) govern ownership approval, cap rules,"
            " and media rights.  Understanding league context is essential for"
            " deal structuring and regulatory clearance."
        ),
        keywords=["NFL", "NBA", "MLB", "NHL", "EPL", "La Liga", "Bundesliga",
                  "MLS", "F1", "Formula One", "league", "association", "federation"],
        relevance_floor=0.7,
    ),
    "company": EntityTypeSpec(
        name="company",
        rationale=(
            "Holding companies, operating businesses, and portfolio companies"
            " that own or invest in sports assets.  Captures the legal vehicle"
            " through which UHNW clients hold their sports exposure."
        ),
        keywords=["Inc", "LLC", "Ltd", "Corp", "Holdings", "Group", "Ventures",
                  "Capital", "Partners", "Enterprises"],
        relevance_floor=0.5,
    ),
    "pe_fund": EntityTypeSpec(
        name="pe_fund",
        rationale=(
            "Private equity and growth equity funds are the primary institutional"
            " co-investors alongside private bank clients in sports M&A.  Tracking"
            " PE fund activity reveals deal flow, LP networks, and pricing comps."
        ),
        keywords=["Fund", "Capital", "Equity", "Ventures", "LP", "GP",
                  "private equity", "growth equity", "buyout", "venture capital",
                  "family office"],
        relevance_floor=0.65,
    ),
    "sports_foundation": EntityTypeSpec(
        name="sports_foundation",
        rationale=(
            "Foundations and philanthropic vehicles tied to sports (athlete"
            " foundations, team charities) reveal client affinity and values-based"
            " motivations — critical soft context for relationship managers."
        ),
        keywords=["Foundation", "Charitable", "Fund", "Institute", "Trust",
                  "Endowment", "nonprofit", "501(c)"],
        relevance_floor=0.55,
    ),

    # ── Financial instruments ────────────────────────────────────────────────
    "transaction_event": EntityTypeSpec(
        name="transaction_event",
        rationale=(
            "Named liquidity events: IPOs, acquisitions, exits, and fundraising"
            " rounds.  Treating a transaction as a first-class node lets the KG"
            " answer 'who participated in deal X' and 'what are comps for team Y'."
        ),
        keywords=["IPO", "acquisition", "merger", "round", "Series A", "Series B",
                  "exit", "buyout", "sale", "investment round"],
        relevance_floor=0.7,
    ),

    # ── Geography ───────────────────────────────────────────────────────────
    "location": EntityTypeSpec(
        name="location",
        rationale=(
            "City and country-level geography scopes deal jurisdiction, tax"
            " domicile, and bankers' coverage maps.  Street-level addresses are"
            " not stored — only deal-relevant markets."
        ),
        keywords=["City", "State", "Country", "Region", "Market", "Metro"],
        relevance_floor=0.3,  # Low floor: location is cheap to store and always useful
    ),

    # ── Life events ──────────────────────────────────────────────────────────
    "life_event": EntityTypeSpec(
        name="life_event",
        rationale=(
            "Marriage, divorce, inheritance, and succession events are wealth"
            " triggers that reshape a client's liquidity profile and risk appetite."
            " Modeling them as nodes (rather than metadata) allows temporal queries:"
            " 'who had a liquidity event within 24 months of a life event'."
        ),
        keywords=["married", "divorced", "inheritance", "estate", "succession",
                  "death", "passed away", "legacy", "bequest"],
        relevance_floor=0.6,
    ),

    # ── Media & IP ───────────────────────────────────────────────────────────
    "media_rights_deal": EntityTypeSpec(
        name="media_rights_deal",
        rationale=(
            "Broadcast deals, streaming agreements, and naming rights are large"
            " monetisation events that affect team valuations and create client"
            " investment opportunities (debt financing, equity stakes)."
        ),
        keywords=["broadcast", "streaming", "naming rights", "media deal",
                  "rights package", "TV deal", "ESPN", "Amazon", "Apple TV"],
        relevance_floor=0.7,
    ),
}

# Validate hard limit at import time — fail fast if someone added a type
assert len(ENTITY_TYPES) <= ENTITY_TYPE_MAX, (
    f"ENTITY_TYPE_MAX={ENTITY_TYPE_MAX} exceeded.  Current count: {len(ENTITY_TYPES)}. "
    "Retire an entity type before adding a new one."
)

# Convenience set for O(1) membership checks in the extraction pipeline
ALLOWED_ENTITY_TYPE_NAMES: frozenset[str] = frozenset(ENTITY_TYPES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 2. RELATIONSHIP FAMILIES & CANONICAL PREDICATES
# ─────────────────────────────────────────────────────────────────────────────
#
# Design decisions:
#   - Each family has a hard maximum of 8 canonical predicates.
#   - Every predicate is either directional or explicitly symmetric.
#   - High-signal predicates are tagged — they drive deal origination scoring.
#   - Variant mappings are the ONLY allowed synonyms.  A raw predicate not in
#     the variant map is rejected or coerced to the nearest canonical form.

PREDICATE_MAX_PER_FAMILY = 8  # Hard ceiling per family


class SignalLevel(str, Enum):
    HIGH = "high"      # Always keep; directly surfaces deal opportunity
    MEDIUM = "medium"  # Keep if confidence >= 0.70
    LOW = "low"        # Drop; contextual noise for this use case


@dataclass(frozen=True)
class PredicateSpec:
    canonical: str
    signal: SignalLevel
    # Is the predicate symmetric (A→B implies B→A)?
    symmetric: bool = False
    # Optional human-readable description for prompt engineering
    description: str = ""


@dataclass
class RelationshipFamily:
    name: str
    description: str
    predicates: dict[str, PredicateSpec]  # canonical_name → spec
    # variant → canonical_name (the normalization dictionary)
    variants: dict[str, str]

    def canonical_names(self) -> list[str]:
        return list(self.predicates.keys())

    def normalize(self, raw: str) -> str | None:
        """Return the canonical predicate name, or None if unknown."""
        key = raw.lower().strip().replace(" ", "_").replace("-", "_")
        if key in self.predicates:
            return key
        return self.variants.get(key)


# ── Family: ownership ────────────────────────────────────────────────────────
#
# Who owns what.  The most important family for sports deal origination.
# "buys a team" and "owns a team" are the same fact at different moments in
# time — both normalize to `owns`.  Temporal context lives in the evidence
# field and source document, not the predicate.

_OWNERSHIP_PREDICATES: dict[str, PredicateSpec] = {
    "owns": PredicateSpec(
        canonical="owns",
        signal=SignalLevel.HIGH,
        description="Subject has majority or full ownership stake in object.",
    ),
    "minority_stake_in": PredicateSpec(
        canonical="minority_stake_in",
        signal=SignalLevel.HIGH,
        description="Subject holds a sub-50% equity stake in object.  "
                    "Important for LP/co-investor identification.",
    ),
    "co_owns": PredicateSpec(
        canonical="co_owns",
        signal=SignalLevel.HIGH,
        symmetric=True,
        description="Subject and object share ownership; neither has majority.",
    ),
    "formerly_owned": PredicateSpec(
        canonical="formerly_owned",
        signal=SignalLevel.MEDIUM,
        description="Subject previously owned object.  Useful for comp analysis.",
    ),
    "controls": PredicateSpec(
        canonical="controls",
        signal=SignalLevel.HIGH,
        description="Subject exercises operational control (voting, board seats) "
                    "without necessarily holding majority equity.",
    ),
    "subsidiary_of": PredicateSpec(
        canonical="subsidiary_of",
        signal=SignalLevel.MEDIUM,
        description="Object is the parent holding company of subject.",
    ),
}

_OWNERSHIP_VARIANTS: dict[str, str] = {
    # Acquisition variants → owns
    "buys": "owns",
    "bought": "owns",
    "purchased": "owns",
    "acquires": "owns",
    "acquired": "owns",
    "has_ownership": "owns",
    "is_owner_of": "owns",
    "owner_of": "owns",
    "takes_ownership": "owns",
    "takes_over": "owns",
    "completes_acquisition": "owns",
    "acquires_team": "owns",
    "buys_team": "owns",
    "purchases_team": "owns",
    # Minority / stake
    "minority_owns": "minority_stake_in",
    "minority_owner": "minority_stake_in",
    "partial_owner": "minority_stake_in",
    "holds_stake": "minority_stake_in",
    "lp_in": "minority_stake_in",
    "limited_partner_in": "minority_stake_in",
    "invested_equity_in": "minority_stake_in",
    # Co-ownership
    "co_owner": "co_owns",
    "co_owner_of": "co_owns",
    "joint_owner": "co_owns",
    "majority_owns": "co_owns",    # majority → owns is more accurate, but without
    # explicit majority % use co_owns as the safer default
    "controlling_owner": "controls",
    "controlling_interest_in": "controls",
    "voting_control_of": "controls",
    # Formerly
    "formerly_owned": "formerly_owned",
    "previously_owned": "formerly_owned",
    "sold_stake_in": "formerly_owned",
    "divested": "formerly_owned",
    # Subsidiary
    "parent_of": "subsidiary_of",
    "parent_company_of": "subsidiary_of",
    "holding_company_of": "subsidiary_of",
    "owned_by": "subsidiary_of",
    "belongs_to": "subsidiary_of",
}

OWNERSHIP_FAMILY = RelationshipFamily(
    name="ownership",
    description="Equity and control relationships between entities and sports assets.",
    predicates=_OWNERSHIP_PREDICATES,
    variants=_OWNERSHIP_VARIANTS,
)


# ── Family: investment ────────────────────────────────────────────────────────
#
# Financial commitments that are not full ownership.  LP positions, fund
# investments, foundation grants.  This family drives prospecting for co-LP
# and deal network queries.

_INVESTMENT_PREDICATES: dict[str, PredicateSpec] = {
    "invested_in": PredicateSpec(
        canonical="invested_in",
        signal=SignalLevel.HIGH,
        description="Subject committed capital to object (fund, company, foundation).",
    ),
    "lp_in": PredicateSpec(
        canonical="lp_in",
        signal=SignalLevel.HIGH,
        description="Subject is a limited partner in a PE/VC fund (object).",
    ),
    "gp_of": PredicateSpec(
        canonical="gp_of",
        signal=SignalLevel.HIGH,
        description="Subject is the general partner / manager of fund (object).",
    ),
    "co_invested_with": PredicateSpec(
        canonical="co_invested_with",
        signal=SignalLevel.HIGH,
        symmetric=True,
        description="Subject and object deployed capital side-by-side into a deal.",
    ),
    "donated_to": PredicateSpec(
        canonical="donated_to",
        signal=SignalLevel.MEDIUM,
        description="Subject made a philanthropic contribution to object (foundation).",
    ),
    "exited": PredicateSpec(
        canonical="exited",
        signal=SignalLevel.HIGH,
        description="Subject completed a liquidity event from object.  "
                    "A primary trigger for re-deployment conversations.",
    ),
}

_INVESTMENT_VARIANTS: dict[str, str] = {
    # invested_in variants
    "invests_in": "invested_in",
    "investor_in": "invested_in",
    "backed": "invested_in",
    "funded": "invested_in",
    "financed": "invested_in",
    "committed_capital_to": "invested_in",
    "acquired_stake_in": "invested_in",
    "put_money_into": "invested_in",
    "writing_check_into": "invested_in",
    "deployed_capital_in": "invested_in",
    # lp_in variants
    "limited_partner_in": "lp_in",
    "lp_commitment_in": "lp_in",
    "fund_investor_in": "lp_in",
    # gp_of variants
    "general_partner_of": "gp_of",
    "fund_manager_of": "gp_of",
    "manages_fund": "gp_of",
    "runs_fund": "gp_of",
    # co-invest
    "co_invest_with": "co_invested_with",
    "co_investor_with": "co_invested_with",
    "coinvested_with": "co_invested_with",
    "joint_investor_with": "co_invested_with",
    "syndicate_partner_with": "co_invested_with",
    # donated
    "donated_to": "donated_to",
    "contributed_to": "donated_to",
    "gifted_to": "donated_to",
    "supports_foundation": "donated_to",
    # exited
    "sold": "exited",
    "sold_stake": "exited",
    "ipo": "exited",
    "took_public": "exited",
    "completed_exit": "exited",
    "realized_investment": "exited",
    "sold_to": "exited",
    "divested_from": "exited",
}

INVESTMENT_FAMILY = RelationshipFamily(
    name="investment",
    description="Capital deployment, fund relationships, and liquidity events.",
    predicates=_INVESTMENT_PREDICATES,
    variants=_INVESTMENT_VARIANTS,
)


# ── Family: role ──────────────────────────────────────────────────────────────
#
# Professional roles and affiliations.  Only roles that are material to deal
# origination are canonical.  "Works at" without a role is LOW signal — the
# bank needs to know if someone is the *decision-maker*, not merely employed.

_ROLE_PREDICATES: dict[str, PredicateSpec] = {
    "ceo_of": PredicateSpec(
        canonical="ceo_of",
        signal=SignalLevel.HIGH,
        description="Subject is the Chief Executive Officer / President of object.",
    ),
    "board_member_of": PredicateSpec(
        canonical="board_member_of",
        signal=SignalLevel.HIGH,
        description="Subject holds a board or director seat at object.",
    ),
    "founded": PredicateSpec(
        canonical="founded",
        signal=SignalLevel.HIGH,
        description="Subject was a founding principal of object.",
    ),
    "executive_at": PredicateSpec(
        canonical="executive_at",
        signal=SignalLevel.MEDIUM,
        description="Subject holds a C-suite or VP role at object "
                    "(when more specific predicate is not available).",
    ),
    "advisor_to": PredicateSpec(
        canonical="advisor_to",
        signal=SignalLevel.MEDIUM,
        description="Subject serves in a formal advisory capacity at object.",
    ),
    "plays_for": PredicateSpec(
        canonical="plays_for",
        signal=SignalLevel.MEDIUM,
        description="Subject (athlete) is an active player at sports_team object.  "
                    "Signals affinity and future wealth event (endorsements, exits).",
    ),
    "coaches": PredicateSpec(
        canonical="coaches",
        signal=SignalLevel.LOW,
        description="Subject coaches object.  Included for completeness but rarely"
                    " a direct deal signal.",
    ),
}

_ROLE_VARIANTS: dict[str, str] = {
    # ceo_of
    "chief_executive_of": "ceo_of",
    "leads": "ceo_of",
    "heads": "ceo_of",
    "runs": "ceo_of",
    "president_of": "ceo_of",
    "managing_director_of": "ceo_of",
    "md_of": "ceo_of",
    # board_member_of
    "on_board_of": "board_member_of",
    "director_of": "board_member_of",
    "board_director_of": "board_member_of",
    "board_chair_of": "board_member_of",
    "chairman_of": "board_member_of",
    "trustee_of": "board_member_of",
    # founded
    "founder_of": "founded",
    "co_founded": "founded",
    "co_founder_of": "founded",
    "started": "founded",
    "established": "founded",
    # executive_at
    "works_for": "executive_at",
    "employed_by": "executive_at",
    "coo_of": "executive_at",
    "cfo_of": "executive_at",
    "vp_of": "executive_at",
    "svp_of": "executive_at",
    "partner_at": "executive_at",
    "senior_partner_at": "executive_at",
    "managing_partner_at": "executive_at",
    # advisor_to
    "advises": "advisor_to",
    "advisory_board_of": "advisor_to",
    "strategic_advisor_to": "advisor_to",
    # plays_for
    "athlete_at": "plays_for",
    "plays_on": "plays_for",
    "signed_with": "plays_for",
    "drafted_by": "plays_for",
    # coaches
    "head_coach_of": "coaches",
    "coached_by": "coaches",
    "assistant_coach_of": "coaches",
}

ROLE_FAMILY = RelationshipFamily(
    name="role",
    description="Professional roles, C-suite positions, and team affiliations.",
    predicates=_ROLE_PREDICATES,
    variants=_ROLE_VARIANTS,
)


# ── Family: deal_network ──────────────────────────────────────────────────────
#
# Who does business with whom.  This family encodes the informal deal network
# that private bankers rely on.  "Partnered on deal" is HIGH signal because it
# reveals trusted relationships and transaction appetite.

_DEAL_NETWORK_PREDICATES: dict[str, PredicateSpec] = {
    "partnered_on_deal": PredicateSpec(
        canonical="partnered_on_deal",
        signal=SignalLevel.HIGH,
        symmetric=True,
        description="Subject and object closed or pursued a named transaction together.",
    ),
    "bid_for": PredicateSpec(
        canonical="bid_for",
        signal=SignalLevel.HIGH,
        description="Subject submitted a bid or letter of intent for object.",
    ),
    "merged_with": PredicateSpec(
        canonical="merged_with",
        signal=SignalLevel.HIGH,
        symmetric=True,
        description="Subject and object completed a merger.",
    ),
    "competes_with": PredicateSpec(
        canonical="competes_with",
        signal=SignalLevel.LOW,
        symmetric=True,
        description="On-field or business competition.  LOW signal for deal origination.",
    ),
    "sponsors": PredicateSpec(
        canonical="sponsors",
        signal=SignalLevel.MEDIUM,
        description="Subject provides financial sponsorship to object.  "
                    "Indicates affinity and existing financial relationship.",
    ),
    "endorsed_by": PredicateSpec(
        canonical="endorsed_by",
        signal=SignalLevel.MEDIUM,
        description="Object (athlete/person) publicly endorses subject (brand/company).",
    ),
}

_DEAL_NETWORK_VARIANTS: dict[str, str] = {
    # partnered_on_deal
    "partnered_with_on_deal": "partnered_on_deal",
    "co_investor_in_deal": "partnered_on_deal",
    "joint_venture_with": "partnered_on_deal",
    "jv_with": "partnered_on_deal",
    "syndicated_with": "partnered_on_deal",
    "clubbed_with": "partnered_on_deal",  # club deal terminology
    # bid_for
    "bid_on": "bid_for",
    "submitted_bid_for": "bid_for",
    "loi_for": "bid_for",
    "letter_of_intent_for": "bid_for",
    "made_offer_for": "bid_for",
    "attempted_to_acquire": "bid_for",
    "failed_bid_for": "bid_for",
    # merged_with
    "merges_with": "merged_with",
    "merger_with": "merged_with",
    "combined_with": "merged_with",
    # competes_with
    "rival_of": "competes_with",
    "competitor_of": "competes_with",
    "competes_against": "competes_with",
    # sponsors
    "sponsored_by": "sponsors",
    "title_sponsor_of": "sponsors",
    "jersey_sponsor_of": "sponsors",
    "naming_rights_with": "sponsors",
    # endorsed_by
    "endorses": "endorsed_by",
    "brand_ambassador_for": "endorsed_by",
    "spokesperson_for": "endorsed_by",
}

DEAL_NETWORK_FAMILY = RelationshipFamily(
    name="deal_network",
    description="Co-investment, bidding activity, and partnership relationships.",
    predicates=_DEAL_NETWORK_PREDICATES,
    variants=_DEAL_NETWORK_VARIANTS,
)


# ── Family: affinity ──────────────────────────────────────────────────────────
#
# Soft signals that indicate a person's passion for sports.  These rarely
# close a deal alone, but they are essential context for the relationship
# manager: "this client is a lifelong Arsenal fan" shapes how you present
# an opportunity.

_AFFINITY_PREDICATES: dict[str, PredicateSpec] = {
    "fan_of": PredicateSpec(
        canonical="fan_of",
        signal=SignalLevel.MEDIUM,
        description="Subject has expressed public fandom for object (team or sport).",
    ),
    "attended_event": PredicateSpec(
        canonical="attended_event",
        signal=SignalLevel.LOW,
        description="Subject attended a named sports event.  Weak signal alone,"
                    " but strengthens affinity profile when combined with fan_of.",
    ),
    "played_sport": PredicateSpec(
        canonical="played_sport",
        signal=SignalLevel.MEDIUM,
        description="Subject played the sport professionally or at college/elite"
                    " amateur level.  Indicates deep domain knowledge.",
    ),
    "named_in_honor_of": PredicateSpec(
        canonical="named_in_honor_of",
        signal=SignalLevel.LOW,
        description="A facility or award is named after subject (vanity/legacy signal).",
    ),
}

_AFFINITY_VARIANTS: dict[str, str] = {
    # fan_of
    "supporter_of": "fan_of",
    "lifelong_fan_of": "fan_of",
    "avid_fan_of": "fan_of",
    "passionate_about": "fan_of",
    "follows": "fan_of",
    # attended_event
    "attended": "attended_event",
    "was_at": "attended_event",
    "present_at": "attended_event",
    # played_sport
    "played": "played_sport",
    "former_player_of": "played_sport",
    "played_professionally": "played_sport",
    "collegiate_athlete_at": "played_sport",
    # named_in_honor_of
    "named_after": "named_in_honor_of",
    "honors": "named_in_honor_of",
}

AFFINITY_FAMILY = RelationshipFamily(
    name="affinity",
    description="Sports fandom, event attendance, and personal connection to sports.",
    predicates=_AFFINITY_PREDICATES,
    variants=_AFFINITY_VARIANTS,
)


# ── Family: life_event ────────────────────────────────────────────────────────
#
# Life events restructure wealth.  Divorce triggers asset re-allocation.
# Inheritance creates new UHNW clients.  The bank needs to know about these
# events to approach clients at the right moment.

_LIFE_EVENT_PREDICATES: dict[str, PredicateSpec] = {
    "married": PredicateSpec(
        canonical="married",
        signal=SignalLevel.HIGH,
        description="Subject married object (person).  Triggers joint wealth planning.",
    ),
    "divorced": PredicateSpec(
        canonical="divorced",
        signal=SignalLevel.HIGH,
        description="Subject and object completed a divorce.  "
                    "Major wealth restructuring trigger.",
    ),
    "inherited_from": PredicateSpec(
        canonical="inherited_from",
        signal=SignalLevel.HIGH,
        description="Subject received an inheritance from object.  "
                    "New capital deployment event.",
    ),
    "succession_from": PredicateSpec(
        canonical="succession_from",
        signal=SignalLevel.HIGH,
        description="Subject assumed control of a business or estate from object.",
    ),
}

_LIFE_EVENT_VARIANTS: dict[str, str] = {
    # married
    "wed": "married",
    "got_married_to": "married",
    "married_to": "married",
    "spouse_of": "married",
    # divorced
    "divorced_from": "divorced",
    "separated_from": "divorced",
    "split_from": "divorced",
    # inherited_from
    "inherited": "inherited_from",
    "heir_of": "inherited_from",
    "beneficiary_of": "inherited_from",
    "received_estate_from": "inherited_from",
    # succession_from
    "succeeded": "succession_from",
    "took_over_from": "succession_from",
    "assumed_control_from": "succession_from",
}

LIFE_EVENT_FAMILY = RelationshipFamily(
    name="life_event",
    description="Marriage, divorce, inheritance, and succession — wealth trigger events.",
    predicates=_LIFE_EVENT_PREDICATES,
    variants=_LIFE_EVENT_VARIANTS,
)


# ── Family: location ──────────────────────────────────────────────────────────
#
# Kept minimal.  Location relationships mostly exist to scope queries
# ("show me deals in the Southeast US").  They are MEDIUM or LOW signal
# for deal origination in isolation.

_LOCATION_PREDICATES: dict[str, PredicateSpec] = {
    "headquartered_in": PredicateSpec(
        canonical="headquartered_in",
        signal=SignalLevel.MEDIUM,
        description="Subject's primary place of business is object (location).",
    ),
    "resides_in": PredicateSpec(
        canonical="resides_in",
        signal=SignalLevel.MEDIUM,
        description="Subject (person) has their primary residence in object.",
    ),
    "operates_in": PredicateSpec(
        canonical="operates_in",
        signal=SignalLevel.LOW,
        description="Subject has business operations (office, subsidiary) in object.",
    ),
    "plays_in": PredicateSpec(
        canonical="plays_in",
        signal=SignalLevel.LOW,
        description="Sports team (subject) plays in the market/arena of object.",
    ),
}

_LOCATION_VARIANTS: dict[str, str] = {
    # headquartered_in
    "hq_in": "headquartered_in",
    "based_in": "headquartered_in",
    "located_in": "headquartered_in",
    "registered_in": "headquartered_in",
    "incorporated_in": "headquartered_in",
    # resides_in
    "lives_in": "resides_in",
    "home_in": "resides_in",
    "domiciled_in": "resides_in",
    "resident_of": "resides_in",
    # operates_in
    "has_office_in": "operates_in",
    "branch_in": "operates_in",
    "active_in": "operates_in",
    # plays_in
    "home_arena_in": "plays_in",
    "home_stadium_in": "plays_in",
    "market_in": "plays_in",
}

LOCATION_FAMILY = RelationshipFamily(
    name="location",
    description="Geographic relationships — headquarters, residence, and operational markets.",
    predicates=_LOCATION_PREDICATES,
    variants=_LOCATION_VARIANTS,
)


# ── Master family registry ────────────────────────────────────────────────────

RELATIONSHIP_FAMILIES: dict[str, RelationshipFamily] = {
    "ownership": OWNERSHIP_FAMILY,
    "investment": INVESTMENT_FAMILY,
    "role": ROLE_FAMILY,
    "deal_network": DEAL_NETWORK_FAMILY,
    "affinity": AFFINITY_FAMILY,
    "life_event": LIFE_EVENT_FAMILY,
    "location": LOCATION_FAMILY,
}

# Validate predicate limits at import time
for _fname, _fam in RELATIONSHIP_FAMILIES.items():
    assert len(_fam.predicates) <= PREDICATE_MAX_PER_FAMILY, (
        f"Family '{_fname}' exceeds PREDICATE_MAX_PER_FAMILY={PREDICATE_MAX_PER_FAMILY}. "
        f"Current count: {len(_fam.predicates)}.  Retire a predicate before adding."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. RELEVANCE RULES
# ─────────────────────────────────────────────────────────────────────────────
#
# Three-tier rules control what enters the KG.  The goal: every stored
# relationship must *directly* support deal origination queries.


@dataclass(frozen=True)
class RelevanceRule:
    tier: Literal["keep", "conditional", "drop"]
    # Minimum confidence score required (0.0 = always keep regardless)
    min_confidence: float
    # Human-readable explanation
    reason: str


# Map (family, signal_level) → RelevanceRule
RELEVANCE_RULES: dict[tuple[str, SignalLevel], RelevanceRule] = {
    # HIGH-signal predicates are always stored (confidence floor: 0.50)
    ("ownership",    SignalLevel.HIGH):   RelevanceRule("keep",        0.50, "Core deal asset relationship"),
    ("investment",   SignalLevel.HIGH):   RelevanceRule("keep",        0.50, "Capital deployment / liquidity event"),
    ("role",         SignalLevel.HIGH):   RelevanceRule("keep",        0.55, "Decision-maker identification"),
    ("deal_network", SignalLevel.HIGH):   RelevanceRule("keep",        0.55, "Proven deal relationship"),
    ("life_event",   SignalLevel.HIGH):   RelevanceRule("keep",        0.60, "Wealth trigger event"),

    # MEDIUM-signal predicates require 0.70 confidence
    ("ownership",    SignalLevel.MEDIUM): RelevanceRule("conditional", 0.70, "Ownership history — keep if well-evidenced"),
    ("investment",   SignalLevel.MEDIUM): RelevanceRule("conditional", 0.70, "Philanthropic signal — contextually useful"),
    ("role",         SignalLevel.MEDIUM): RelevanceRule("conditional", 0.70, "Non-C-suite role — keep only if high confidence"),
    ("deal_network", SignalLevel.MEDIUM): RelevanceRule("conditional", 0.70, "Sponsorship / endorsement deal"),
    ("affinity",     SignalLevel.MEDIUM): RelevanceRule("conditional", 0.75, "Soft affinity — needs strong evidence"),
    ("location",     SignalLevel.MEDIUM): RelevanceRule("conditional", 0.65, "HQ / residence — useful for coverage scoping"),
    ("life_event",   SignalLevel.MEDIUM): RelevanceRule("conditional", 0.70, "Life event — keep if explicitly stated"),

    # LOW-signal predicates are dropped
    ("role",         SignalLevel.LOW):    RelevanceRule("drop",        1.01, "Coaching role — not deal-relevant"),
    ("deal_network", SignalLevel.LOW):    RelevanceRule("drop",        1.01, "On-field rivalry — irrelevant to banking"),
    ("affinity",     SignalLevel.LOW):    RelevanceRule("drop",        1.01, "Event attendance / vanity — not deal signal"),
    ("location",     SignalLevel.LOW):    RelevanceRule("drop",        1.01, "Operational geography — too granular"),
}

# Global confidence floor below which ALL relationships are dropped
GLOBAL_CONFIDENCE_FLOOR: float = 0.50


def should_keep_relationship(
    family: str,
    predicate: str,
    confidence: float,
) -> bool:
    """
    Return True if this relationship should be stored in the KG.

    Decision logic:
    1. Drop anything below the global confidence floor unconditionally.
    2. Look up the (family, signal_level) rule.
    3. Apply the tier: keep → True if above min_confidence; drop → always False.
    """
    if confidence < GLOBAL_CONFIDENCE_FLOOR:
        return False

    fam = RELATIONSHIP_FAMILIES.get(family)
    if fam is None:
        # Unknown family: reject
        return False

    pred_spec = fam.predicates.get(predicate)
    if pred_spec is None:
        # Unknown predicate: reject
        return False

    rule = RELEVANCE_RULES.get((family, pred_spec.signal))
    if rule is None:
        # No explicit rule → apply medium default
        return confidence >= 0.70

    if rule.tier == "drop":
        return False

    return confidence >= rule.min_confidence


# ─────────────────────────────────────────────────────────────────────────────
# 4. ENTITY RELEVANCE SCORING
# ─────────────────────────────────────────────────────────────────────────────
#
# Not every entity extracted from a document belongs in the KG.  A mention of
# "the NFL" in a passing sentence is not worth a node.  An entity earns its
# place by:
#   a) Being of an allowed type
#   b) Carrying at least one HIGH-signal relationship
#   c) Scoring above ENTITY_RELEVANCE_FLOOR
#
# Scoring formula (additive, capped at 1.0):
#   base                           = entity type relevance_floor
#   + 0.20 per HIGH-signal rel     (max +0.40)
#   + 0.10 per MEDIUM-signal rel   (max +0.20)
#   - 0.10 if only LOW-signal rels (noise penalty)


ENTITY_RELEVANCE_FLOOR: float = 0.40  # Below this: entity is dropped


def score_entity_relevance(
    entity_type: str,
    high_signal_rel_count: int,
    medium_signal_rel_count: int,
    low_signal_only: bool = False,
) -> float:
    """
    Compute an entity's relevance score for KG inclusion.

    Args:
        entity_type: One of the allowed entity type names.
        high_signal_rel_count: Number of HIGH-signal relationships touching this entity.
        medium_signal_rel_count: Number of MEDIUM-signal relationships.
        low_signal_only: True if the entity has ONLY low-signal relationships.

    Returns:
        A float score in [0.0, 1.0].  Scores below ENTITY_RELEVANCE_FLOOR
        indicate the entity should be dropped.
    """
    spec = ENTITY_TYPES.get(entity_type)
    if spec is None:
        # Unknown entity type: always drop
        return 0.0

    score: float = spec.relevance_floor
    score += min(high_signal_rel_count * 0.20, 0.40)
    score += min(medium_signal_rel_count * 0.10, 0.20)
    if low_signal_only:
        score -= 0.10

    return min(score, 1.0)


def should_keep_entity(
    entity_type: str,
    high_signal_rel_count: int,
    medium_signal_rel_count: int,
    low_signal_only: bool = False,
) -> bool:
    """Return True if this entity should be stored in the KG."""
    if entity_type not in ALLOWED_ENTITY_TYPE_NAMES:
        return False
    score = score_entity_relevance(
        entity_type, high_signal_rel_count, medium_signal_rel_count, low_signal_only
    )
    return score >= ENTITY_RELEVANCE_FLOOR


# ─────────────────────────────────────────────────────────────────────────────
# 5. PREDICATE NORMALIZATION — public API
# ─────────────────────────────────────────────────────────────────────────────
#
# Two-pass normalization:
#   Pass 1: Exact match against family variant dictionaries.
#   Pass 2: Cross-family search (LLM may omit the family).
# If both passes fail, returns None — caller should reject the relationship.


def normalize_predicate(
    raw_predicate: str,
    family_hint: str = "",
) -> tuple[str, str] | None:
    """
    Normalize a raw LLM-extracted predicate to (canonical_predicate, family).

    Returns None if the predicate cannot be mapped to any canonical form.
    The caller should drop relationships with None normalization.

    Args:
        raw_predicate: The predicate string as returned by the LLM.
        family_hint: The family the LLM assigned (optional; used for tie-breaking).
    """
    key = raw_predicate.lower().strip().replace(" ", "_").replace("-", "_")

    # Pass 1: Try the hinted family first (fast path)
    if family_hint:
        fam = RELATIONSHIP_FAMILIES.get(family_hint)
        if fam:
            result = fam.normalize(key)
            if result:
                return result, family_hint

    # Pass 2: Search all families in priority order
    # Priority: ownership > investment > role > deal_network > life_event > affinity > location
    PRIORITY_ORDER = [
        "ownership", "investment", "role",
        "deal_network", "life_event", "affinity", "location",
    ]
    for fname in PRIORITY_ORDER:
        fam = RELATIONSHIP_FAMILIES[fname]
        result = fam.normalize(key)
        if result:
            return result, fname

    # Pass 3: Fuzzy strip of trailing connective suffixes
    for suffix in ("_of", "_by", "_with", "_in", "_for", "_at", "_to", "_from"):
        if key.endswith(suffix):
            stripped = key[: -len(suffix)]
            for fname in PRIORITY_ORDER:
                fam = RELATIONSHIP_FAMILIES[fname]
                result = fam.normalize(stripped)
                if result:
                    return result, fname

    return None  # Unknown predicate — caller must drop this relationship


# ─────────────────────────────────────────────────────────────────────────────
# 6. ANTI-EXPLOSION RULES
# ─────────────────────────────────────────────────────────────────────────────
#
# Structural guardrails that prevent the KG from growing unbounded.
# These are enforced at ingestion time in the extraction worker.


@dataclass(frozen=True)
class AntiExplosionRules:
    # Hard limits
    max_entity_types: int
    max_predicates_per_family: int

    # Confidence floors
    global_relationship_confidence_floor: float

    # Entity caps per KG scope (per team)
    max_entities_per_type_per_team: int

    # Relationship caps: at most N relationships per (subject, object) pair
    # Prevents "owns + co_owns + minority_stake_in + controls" on same edge
    max_predicates_per_entity_pair: int

    # High-signal relationship requirement: an entity with zero HIGH-signal
    # relationships is a candidate for pruning during compaction
    min_high_signal_rels_to_retain: int

    # Decay: relationships older than this many days with no corroboration
    # are flagged for review (not auto-deleted — requires human confirmation)
    relationship_staleness_days: int


ANTI_EXPLOSION_RULES = AntiExplosionRules(
    max_entity_types=ENTITY_TYPE_MAX,                     # 10 types, hard ceiling
    max_predicates_per_family=PREDICATE_MAX_PER_FAMILY,   # 8 predicates per family
    global_relationship_confidence_floor=GLOBAL_CONFIDENCE_FLOOR,  # 0.50
    max_entities_per_type_per_team=500,   # A team KG should not exceed 500 persons, 200 companies, etc.
    max_predicates_per_entity_pair=3,     # A→B should not have >3 different predicates (noise signal)
    min_high_signal_rels_to_retain=1,     # An isolated entity with no HIGH rels is a pruning candidate
    relationship_staleness_days=730,      # 2 years without corroboration → flag for review
)


# ─────────────────────────────────────────────────────────────────────────────
# 7. LLM PROMPT HELPERS
# ─────────────────────────────────────────────────────────────────────────────
#
# Structured prompt sections that replace the ad-hoc strings in entity_extraction.py.


def get_entity_types_prompt() -> str:
    """Return the entity types section for the extraction prompt."""
    lines = [
        "ENTITY TYPES — use EXACTLY one of the following (no other types allowed):\n"
    ]
    for name, spec in ENTITY_TYPES.items():
        lines.append(f"  {name!r}: {spec.rationale}")
    lines.append(
        "\nIf an entity does not fit any type above, DO NOT extract it."
    )
    return "\n".join(lines)


def get_canonical_predicates_prompt() -> str:
    """
    Return the canonical predicates section for the extraction prompt.

    Only HIGH and MEDIUM signal predicates are listed — LOW signal predicates
    are intentionally omitted to discourage the LLM from generating them.
    """
    lines = [
        "RELATIONSHIP PREDICATES — use EXACTLY one canonical predicate per relationship.\n"
        "Do NOT invent predicates.  Map all synonyms to the canonical form shown.\n"
    ]
    for fname, fam in RELATIONSHIP_FAMILIES.items():
        # Only surface HIGH+MEDIUM predicates in the prompt
        visible = [
            p.canonical for p in fam.predicates.values()
            if p.signal in (SignalLevel.HIGH, SignalLevel.MEDIUM)
        ]
        if visible:
            lines.append(f"  {fname}: {', '.join(visible)}")
    lines.append(
        "\nFor synonyms (e.g. 'buys', 'purchased', 'acquires') always use the "
        "canonical predicate (e.g. 'owns')."
    )
    return "\n".join(lines)


def get_lm_prompt_section() -> str:
    """Return the full ontology constraint section to embed in extraction prompts."""
    return "\n\n".join([
        get_entity_types_prompt(),
        get_canonical_predicates_prompt(),
    ])


# ─────────────────────────────────────────────────────────────────────────────
# 8. MIGRATION HELPERS — map old predicate_normalization.py to new ontology
# ─────────────────────────────────────────────────────────────────────────────
#
# The existing predicate_normalization.py uses the 5-family schema
# (ownership, employment, transaction, location, partnership).
# This mapping allows a zero-downtime migration: the extraction worker can
# call translate_legacy_family() to route old family names to new ones.

LEGACY_FAMILY_MAP: dict[str, str] = {
    "ownership":   "ownership",
    "employment":  "role",
    "transaction": "investment",
    "location":    "location",
    "partnership": "deal_network",
}


def translate_legacy_predicate(
    predicate: str,
    legacy_family: str,
) -> tuple[str, str] | None:
    """
    Translate a predicate from the legacy 5-family schema to the new ontology.

    Returns (new_canonical_predicate, new_family) or None if unmappable.
    """
    new_family_hint = LEGACY_FAMILY_MAP.get(legacy_family, "")
    return normalize_predicate(predicate, new_family_hint)

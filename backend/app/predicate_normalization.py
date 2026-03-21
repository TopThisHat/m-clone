"""
Canonical predicate normalization for knowledge graph relationships.

Prevents inconsistent predicates like "buys team" vs "owns team" vs
"purchased team" by mapping variants to a canonical set.
"""
from __future__ import annotations

# ── Canonical predicates per family ──────────────────────────────────────────

CANONICAL_PREDICATES: dict[str, dict[str, str]] = {
    "ownership": {
        # Canonical: owns, owned_by, co_owns, majority_owns, minority_owns
        "owns": "owns",
        "owned_by": "owned_by",
        "co_owns": "co_owns",
        "majority_owns": "majority_owns",
        "minority_owns": "minority_owns",
        # Variants that should normalize
        "buys": "owns",
        "bought": "owns",
        "purchased": "owns",
        "acquires": "owns",
        "acquired": "owns",
        "has_ownership": "owns",
        "is_owner_of": "owns",
        "owner_of": "owns",
        "is_owned_by": "owned_by",
        "belongs_to": "owned_by",
        "property_of": "owned_by",
        "co_owner": "co_owns",
        "co_owner_of": "co_owns",
        "joint_owner": "co_owns",
        "majority_owner": "majority_owns",
        "majority_stake": "majority_owns",
        "controlling_owner": "majority_owns",
        "minority_owner": "minority_owns",
        "minority_stake": "minority_owns",
        "partial_owner": "minority_owns",
    },
    "employment": {
        # Canonical: employs, employed_by, ceo_of, founded, board_member_of
        "employs": "employs",
        "employed_by": "employed_by",
        "works_for": "employed_by",
        "works_at": "employed_by",
        "employee_of": "employed_by",
        "hired_by": "employed_by",
        "ceo_of": "ceo_of",
        "chief_executive_of": "ceo_of",
        "leads": "ceo_of",
        "heads": "ceo_of",
        "runs": "ceo_of",
        "manages": "manages",
        "managed_by": "managed_by",
        "founded": "founded",
        "founded_by": "founded_by",
        "founder_of": "founded",
        "co_founded": "co_founded",
        "co_founder_of": "co_founded",
        "board_member_of": "board_member_of",
        "on_board_of": "board_member_of",
        "director_of": "board_member_of",
        "chairman_of": "chairman_of",
        "president_of": "president_of",
        "vp_of": "vp_of",
        "coaches": "coaches",
        "coached_by": "coached_by",
        "plays_for": "plays_for",
        "member_of": "member_of",
    },
    "transaction": {
        # Canonical: invested_in, sold, merged_with, joint_venture_with
        "invested_in": "invested_in",
        "invests_in": "invested_in",
        "investor_in": "invested_in",
        "backed": "invested_in",
        "funded": "invested_in",
        "financed": "invested_in",
        "sold": "sold",
        "sells": "sold",
        "divested": "sold",
        "sold_to": "sold_to",
        "merged_with": "merged_with",
        "merges_with": "merged_with",
        "merger_with": "merged_with",
        "joint_venture_with": "joint_venture_with",
        "jv_with": "joint_venture_with",
        "partnered_on_deal": "partnered_on_deal",
        "bid_for": "bid_for",
        "acquired_stake_in": "invested_in",
    },
    "location": {
        # Canonical: located_in, headquartered_in, operates_in
        "located_in": "located_in",
        "based_in": "located_in",
        "location": "located_in",
        "headquartered_in": "headquartered_in",
        "hq_in": "headquartered_in",
        "headquarters_in": "headquartered_in",
        "operates_in": "operates_in",
        "has_office_in": "operates_in",
        "branch_in": "operates_in",
        "resides_in": "resides_in",
        "lives_in": "resides_in",
        "born_in": "born_in",
        "from": "from",
    },
    "partnership": {
        # Canonical: partnered_with, allied_with, sponsors, competes_with
        "partnered_with": "partnered_with",
        "partner_of": "partnered_with",
        "partners_with": "partnered_with",
        "allied_with": "allied_with",
        "alliance_with": "allied_with",
        "sponsors": "sponsors",
        "sponsored_by": "sponsored_by",
        "endorses": "endorses",
        "endorsed_by": "endorsed_by",
        "competes_with": "competes_with",
        "rival_of": "competes_with",
        "competitor_of": "competes_with",
        "collaborates_with": "collaborates_with",
        "affiliated_with": "affiliated_with",
        "subsidiary_of": "subsidiary_of",
        "parent_of": "parent_of",
        "parent_company_of": "parent_of",
    },
}

# Flatten for O(1) lookup
_FLAT_MAP: dict[str, tuple[str, str]] = {}  # variant → (canonical_predicate, family)
for _family, _variants in CANONICAL_PREDICATES.items():
    for _variant, _canonical in _variants.items():
        _FLAT_MAP[_variant.lower()] = (_canonical, _family)


def normalize_predicate(predicate: str, predicate_family: str = "") -> tuple[str, str]:
    """
    Normalize a predicate to its canonical form.

    Returns (canonical_predicate, canonical_family).
    If no match is found, returns the input as-is.
    """
    key = predicate.lower().strip().replace(" ", "_").replace("-", "_")

    # Direct lookup
    if key in _FLAT_MAP:
        return _FLAT_MAP[key]

    # Check within the specified family
    if predicate_family:
        family_map = CANONICAL_PREDICATES.get(predicate_family, {})
        if key in family_map:
            return family_map[key], predicate_family

    # Fuzzy: strip common suffixes/prefixes
    for suffix in ("_of", "_by", "_with", "_in", "_for", "_at", "_to"):
        stripped = key.rstrip(suffix) if key.endswith(suffix) else key
        if stripped != key and stripped in _FLAT_MAP:
            return _FLAT_MAP[stripped]

    # No match — return as-is with the provided family
    return predicate, predicate_family or "partnership"


def get_canonical_predicates_prompt() -> str:
    """Generate a prompt section listing all canonical predicates per family."""
    lines = ["The following are the ONLY allowed predicates per family. "
             "You MUST use exactly one of these — do NOT invent new ones:\n"]
    for family, variants in CANONICAL_PREDICATES.items():
        canonicals = sorted(set(variants.values()))
        lines.append(f"  {family}: {', '.join(canonicals)}")
    return "\n".join(lines)

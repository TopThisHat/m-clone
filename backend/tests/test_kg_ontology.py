"""
Unit tests for backend/app/kg_ontology.py.

Validates:
  - Closed entity type set and hard limit
  - Predicate hard limits per family
  - Normalization: exact match, variant match, cross-family, fuzzy-strip, unknown
  - should_keep_relationship: all three tiers
  - should_keep_entity / score_entity_relevance
  - Anti-explosion rules are structurally correct
  - Prompt helper functions produce non-empty, correct content
  - Legacy migration helper
"""
from __future__ import annotations

import pytest

from app.kg_ontology import (
    ALLOWED_ENTITY_TYPE_NAMES,
    ANTI_EXPLOSION_RULES,
    ENTITY_TYPE_MAX,
    ENTITY_TYPES,
    GLOBAL_CONFIDENCE_FLOOR,
    PREDICATE_MAX_PER_FAMILY,
    RELATIONSHIP_FAMILIES,
    SignalLevel,
    normalize_predicate,
    score_entity_relevance,
    should_keep_entity,
    should_keep_relationship,
    translate_legacy_predicate,
    get_lm_prompt_section,
    get_entity_types_prompt,
    get_canonical_predicates_prompt,
)


# ─────────────────────────────────────────────────────────────────────────────
# Entity type tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityTypes:
    def test_hard_limit_not_exceeded(self):
        assert len(ENTITY_TYPES) <= ENTITY_TYPE_MAX

    def test_no_other_catch_all(self):
        assert "other" not in ENTITY_TYPES

    def test_all_types_have_rationale(self):
        for name, spec in ENTITY_TYPES.items():
            assert spec.rationale, f"Entity type '{name}' missing rationale"

    def test_all_types_have_keywords(self):
        for name, spec in ENTITY_TYPES.items():
            assert spec.keywords, f"Entity type '{name}' missing keywords"

    def test_relevance_floors_in_range(self):
        for name, spec in ENTITY_TYPES.items():
            assert 0.0 <= spec.relevance_floor <= 1.0, (
                f"Entity type '{name}' relevance_floor out of range: {spec.relevance_floor}"
            )

    def test_allowed_entity_type_names_matches_dict(self):
        assert ALLOWED_ENTITY_TYPE_NAMES == frozenset(ENTITY_TYPES.keys())

    @pytest.mark.parametrize("expected_type", [
        "person", "sports_team", "sports_league", "company", "pe_fund",
        "sports_foundation", "transaction_event", "location", "life_event",
        "media_rights_deal",
    ])
    def test_required_types_present(self, expected_type: str):
        assert expected_type in ENTITY_TYPES, (
            f"Required entity type '{expected_type}' is missing from ontology"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Relationship family tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRelationshipFamilies:
    def test_all_required_families_present(self):
        required = {
            "ownership", "investment", "role",
            "deal_network", "affinity", "life_event", "location",
        }
        assert required <= set(RELATIONSHIP_FAMILIES.keys())

    def test_no_family_exceeds_predicate_limit(self):
        for fname, fam in RELATIONSHIP_FAMILIES.items():
            assert len(fam.predicates) <= PREDICATE_MAX_PER_FAMILY, (
                f"Family '{fname}' has {len(fam.predicates)} predicates, "
                f"exceeds limit of {PREDICATE_MAX_PER_FAMILY}"
            )

    def test_all_predicates_have_signal_levels(self):
        for fname, fam in RELATIONSHIP_FAMILIES.items():
            for pname, spec in fam.predicates.items():
                assert isinstance(spec.signal, SignalLevel), (
                    f"{fname}.{pname}: signal must be a SignalLevel enum"
                )

    def test_all_canonicals_self_map(self):
        """Every canonical predicate must normalize to itself within its family."""
        for fname, fam in RELATIONSHIP_FAMILIES.items():
            for canonical in fam.predicates:
                result = fam.normalize(canonical)
                assert result == canonical, (
                    f"Family '{fname}': canonical '{canonical}' did not self-map "
                    f"(got {result!r})"
                )

    def test_variants_map_to_known_canonical(self):
        """Every variant must point to a canonical predicate that exists."""
        for fname, fam in RELATIONSHIP_FAMILIES.items():
            for variant, target in fam.variants.items():
                assert target in fam.predicates, (
                    f"Family '{fname}': variant '{variant}' → '{target}' "
                    f"but '{target}' is not a canonical predicate"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Normalization tests
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizePredicate:
    # ── Exact canonical self-mapping ────────────────────────────────────────

    def test_canonical_owns_with_hint(self):
        result = normalize_predicate("owns", "ownership")
        assert result == ("owns", "ownership")

    def test_canonical_invested_in_with_hint(self):
        result = normalize_predicate("invested_in", "investment")
        assert result == ("invested_in", "investment")

    def test_canonical_ceo_of_with_hint(self):
        result = normalize_predicate("ceo_of", "role")
        assert result == ("ceo_of", "role")

    def test_canonical_married_with_hint(self):
        result = normalize_predicate("married", "life_event")
        assert result == ("married", "life_event")

    # ── Variant normalization within hinted family ───────────────────────────

    def test_buys_normalizes_to_owns(self):
        result = normalize_predicate("buys", "ownership")
        assert result == ("owns", "ownership")

    def test_purchased_normalizes_to_owns(self):
        result = normalize_predicate("purchased", "ownership")
        assert result == ("owns", "ownership")

    def test_acquires_normalizes_to_owns(self):
        result = normalize_predicate("acquires", "ownership")
        assert result == ("owns", "ownership")

    def test_acquires_team_normalizes_to_owns(self):
        result = normalize_predicate("acquires_team", "ownership")
        assert result == ("owns", "ownership")

    def test_buys_team_normalizes_to_owns(self):
        result = normalize_predicate("buys_team", "ownership")
        assert result == ("owns", "ownership")

    def test_lp_in_normalizes_to_lp_in(self):
        result = normalize_predicate("limited_partner_in", "investment")
        assert result == ("lp_in", "investment")

    def test_committed_capital_normalizes_to_invested_in(self):
        result = normalize_predicate("committed_capital_to", "investment")
        assert result == ("invested_in", "investment")

    def test_chief_executive_normalizes_to_ceo_of(self):
        result = normalize_predicate("chief_executive_of", "role")
        assert result == ("ceo_of", "role")

    def test_founder_of_normalizes_to_founded(self):
        result = normalize_predicate("founder_of", "role")
        assert result == ("founded", "role")

    def test_jv_with_normalizes_to_partnered_on_deal(self):
        result = normalize_predicate("jv_with", "deal_network")
        assert result == ("partnered_on_deal", "deal_network")

    def test_married_to_normalizes_to_married(self):
        result = normalize_predicate("married_to", "life_event")
        assert result == ("married", "life_event")

    def test_inherited_normalizes_to_inherited_from(self):
        result = normalize_predicate("inherited", "life_event")
        assert result == ("inherited_from", "life_event")

    def test_fan_of_variants(self):
        for variant in ("supporter_of", "lifelong_fan_of", "follows"):
            result = normalize_predicate(variant, "affinity")
            assert result == ("fan_of", "affinity"), (
                f"Variant '{variant}' should normalize to fan_of"
            )

    # ── Cross-family normalization (no hint) ─────────────────────────────────

    def test_buys_no_hint_resolves_to_owns(self):
        result = normalize_predicate("buys")
        assert result is not None
        canonical, family = result
        assert canonical == "owns"
        assert family == "ownership"

    def test_ipo_no_hint_resolves_to_exited(self):
        result = normalize_predicate("ipo")
        assert result is not None
        canonical, family = result
        assert canonical == "exited"
        assert family == "investment"

    def test_divorced_from_no_hint(self):
        result = normalize_predicate("divorced_from")
        assert result is not None
        assert result[0] == "divorced"

    def test_hq_in_no_hint(self):
        result = normalize_predicate("hq_in")
        assert result is not None
        assert result[0] == "headquartered_in"
        assert result[1] == "location"

    # ── Case / whitespace insensitivity ─────────────────────────────────────

    def test_uppercase_normalizes(self):
        result = normalize_predicate("OWNS", "ownership")
        assert result == ("owns", "ownership")

    def test_space_separated_normalizes(self):
        result = normalize_predicate("invested in", "investment")
        assert result == ("invested_in", "investment")

    def test_hyphenated_normalizes(self):
        result = normalize_predicate("ceo-of", "role")
        assert result == ("ceo_of", "role")

    # ── Unknown predicates return None ───────────────────────────────────────

    def test_unknown_predicate_returns_none(self):
        result = normalize_predicate("likes_dogs")
        assert result is None

    def test_nonsense_predicate_returns_none(self):
        result = normalize_predicate("xyz_abc_123")
        assert result is None

    def test_empty_predicate_returns_none(self):
        result = normalize_predicate("")
        assert result is None

    # ── Fuzzy suffix strip ───────────────────────────────────────────────────

    def test_fuzzy_strip_owns_of(self):
        # "owns_of" is not a variant but "owns" is canonical — fuzzy should find it
        result = normalize_predicate("owns_of", "ownership")
        # After stripping "_of" we get "owns" which is canonical
        assert result is not None
        assert result[0] == "owns"


# ─────────────────────────────────────────────────────────────────────────────
# Relationship relevance / filtering tests
# ─────────────────────────────────────────────────────────────────────────────


class TestShouldKeepRelationship:
    # ── HIGH signal predicates ───────────────────────────────────────────────

    def test_high_signal_at_floor_is_kept(self):
        # 'owns' is HIGH signal; floor is 0.50
        assert should_keep_relationship("ownership", "owns", confidence=0.50)

    def test_high_signal_above_floor_is_kept(self):
        assert should_keep_relationship("ownership", "owns", confidence=0.95)

    def test_high_signal_below_global_floor_is_dropped(self):
        assert not should_keep_relationship("ownership", "owns", confidence=0.49)

    def test_investment_exited_high_signal_kept(self):
        assert should_keep_relationship("investment", "exited", confidence=0.60)

    def test_life_event_married_high_signal_kept(self):
        assert should_keep_relationship("life_event", "married", confidence=0.65)

    # ── MEDIUM signal predicates ─────────────────────────────────────────────

    def test_medium_signal_above_threshold_kept(self):
        # 'fan_of' is MEDIUM in affinity; threshold is 0.75
        assert should_keep_relationship("affinity", "fan_of", confidence=0.80)

    def test_medium_signal_below_threshold_dropped(self):
        assert not should_keep_relationship("affinity", "fan_of", confidence=0.74)

    def test_medium_signal_exactly_at_threshold_kept(self):
        assert should_keep_relationship("affinity", "fan_of", confidence=0.75)

    def test_sponsorship_medium_kept(self):
        assert should_keep_relationship("deal_network", "sponsors", confidence=0.70)

    def test_sponsorship_medium_dropped_low_confidence(self):
        assert not should_keep_relationship("deal_network", "sponsors", confidence=0.65)

    # ── LOW signal predicates → always dropped ────────────────────────────────

    def test_low_signal_coaches_dropped_regardless_of_confidence(self):
        assert not should_keep_relationship("role", "coaches", confidence=1.0)

    def test_low_signal_competes_with_dropped(self):
        assert not should_keep_relationship("deal_network", "competes_with", confidence=1.0)

    def test_low_signal_operates_in_dropped(self):
        assert not should_keep_relationship("location", "operates_in", confidence=0.99)

    # ── Unknown family / predicate ────────────────────────────────────────────

    def test_unknown_family_dropped(self):
        assert not should_keep_relationship("made_up_family", "owns", confidence=0.90)

    def test_unknown_predicate_dropped(self):
        assert not should_keep_relationship("ownership", "nonexistent_pred", confidence=0.90)


# ─────────────────────────────────────────────────────────────────────────────
# Entity relevance scoring tests
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityRelevance:
    def test_unknown_entity_type_scores_zero(self):
        score = score_entity_relevance("alien", 5, 5)
        assert score == 0.0

    def test_unknown_entity_type_dropped(self):
        assert not should_keep_entity("alien", 5, 5)

    def test_person_with_no_rels_at_floor(self):
        score = score_entity_relevance("person", 0, 0)
        # person relevance_floor = 0.40; with no rels: 0.40 >= 0.40
        assert score == pytest.approx(0.40)
        assert should_keep_entity("person", 0, 0)

    def test_person_with_low_signal_only_penalised(self):
        score = score_entity_relevance("person", 0, 0, low_signal_only=True)
        # 0.40 - 0.10 = 0.30 < 0.40 floor
        assert score == pytest.approx(0.30)
        assert not should_keep_entity("person", 0, 0, low_signal_only=True)

    def test_high_signal_rels_boost_score(self):
        # person: 0.40 + 2 * 0.20 = 0.80
        score = score_entity_relevance("person", 2, 0)
        assert score == pytest.approx(0.80)

    def test_high_signal_boost_is_capped_at_040(self):
        # 5 high-signal rels: boost = min(5 * 0.20, 0.40) = 0.40
        score = score_entity_relevance("person", 5, 0)
        assert score == pytest.approx(min(0.40 + 0.40, 1.0))

    def test_score_capped_at_one(self):
        score = score_entity_relevance("sports_team", 10, 10)
        assert score <= 1.0

    def test_location_with_no_rels_kept(self):
        # location relevance_floor = 0.30 which is below ENTITY_RELEVANCE_FLOOR 0.40
        assert not should_keep_entity("location", 0, 0)

    def test_location_with_one_medium_rel_kept(self):
        # 0.30 + 0.10 = 0.40 >= 0.40
        assert should_keep_entity("location", 0, 1)

    def test_pe_fund_kept_with_one_high_signal_rel(self):
        # 0.65 + 0.20 = 0.85
        assert should_keep_entity("pe_fund", 1, 0)

    def test_transaction_event_kept_with_one_high_signal_rel(self):
        assert should_keep_entity("transaction_event", 1, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Anti-explosion rules tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAntiExplosionRules:
    def test_entity_type_max_is_10(self):
        assert ANTI_EXPLOSION_RULES.max_entity_types == 10

    def test_predicate_max_per_family_is_8(self):
        assert ANTI_EXPLOSION_RULES.max_predicates_per_family == 8

    def test_global_confidence_floor_is_050(self):
        assert ANTI_EXPLOSION_RULES.global_relationship_confidence_floor == pytest.approx(0.50)

    def test_max_predicates_per_entity_pair_set(self):
        assert ANTI_EXPLOSION_RULES.max_predicates_per_entity_pair > 0

    def test_staleness_days_reasonable(self):
        # Should be at least 1 year
        assert ANTI_EXPLOSION_RULES.relationship_staleness_days >= 365

    def test_global_confidence_floor_matches_constant(self):
        assert ANTI_EXPLOSION_RULES.global_relationship_confidence_floor == GLOBAL_CONFIDENCE_FLOOR


# ─────────────────────────────────────────────────────────────────────────────
# Prompt helper tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptHelpers:
    def test_entity_types_prompt_contains_all_types(self):
        prompt = get_entity_types_prompt()
        for type_name in ENTITY_TYPES:
            assert type_name in prompt, (
                f"Entity type '{type_name}' missing from entity types prompt"
            )

    def test_entity_types_prompt_has_no_other(self):
        prompt = get_entity_types_prompt()
        assert "'other'" not in prompt

    def test_canonical_predicates_prompt_lists_high_medium_only(self):
        prompt = get_canonical_predicates_prompt()
        # 'coaches' is LOW signal — should not appear
        assert "coaches" not in prompt

    def test_canonical_predicates_prompt_contains_key_predicates(self):
        prompt = get_canonical_predicates_prompt()
        for key_pred in ("owns", "invested_in", "ceo_of", "married", "partnered_on_deal"):
            assert key_pred in prompt, (
                f"Key predicate '{key_pred}' missing from canonical predicates prompt"
            )

    def test_lm_prompt_section_is_nonempty(self):
        section = get_lm_prompt_section()
        assert len(section) > 100

    def test_lm_prompt_section_contains_both_parts(self):
        section = get_lm_prompt_section()
        assert "ENTITY TYPES" in section
        assert "RELATIONSHIP PREDICATES" in section


# ─────────────────────────────────────────────────────────────────────────────
# Legacy migration helper tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLegacyMigration:
    def test_legacy_owns_maps_correctly(self):
        result = translate_legacy_predicate("owns", "ownership")
        assert result is not None
        assert result[0] == "owns"
        assert result[1] == "ownership"

    def test_legacy_buys_maps_to_owns(self):
        result = translate_legacy_predicate("buys", "ownership")
        assert result is not None
        assert result[0] == "owns"

    def test_legacy_invested_in_maps_correctly(self):
        result = translate_legacy_predicate("invested_in", "transaction")
        assert result is not None
        assert result[0] == "invested_in"
        assert result[1] == "investment"

    def test_legacy_backed_maps_to_invested_in(self):
        result = translate_legacy_predicate("backed", "transaction")
        assert result is not None
        assert result[0] == "invested_in"

    def test_legacy_employment_family_maps_to_role(self):
        result = translate_legacy_predicate("ceo_of", "employment")
        assert result is not None
        assert result[0] == "ceo_of"
        assert result[1] == "role"

    def test_legacy_board_member_of_maps_correctly(self):
        result = translate_legacy_predicate("board_member_of", "employment")
        assert result is not None
        assert result[0] == "board_member_of"
        assert result[1] == "role"

    def test_legacy_partnership_maps_to_deal_network(self):
        result = translate_legacy_predicate("jv_with", "partnership")
        assert result is not None
        assert result[0] == "partnered_on_deal"
        assert result[1] == "deal_network"

    def test_legacy_located_in_maps_correctly(self):
        result = translate_legacy_predicate("located_in", "location")
        assert result is not None
        assert result[0] == "headquartered_in"
        assert result[1] == "location"

    def test_unknown_legacy_predicate_returns_none(self):
        result = translate_legacy_predicate("made_up_predicate_xyz", "employment")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Integration: full normalization → filter pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeThenFilter:
    """Simulates the extraction worker pipeline for representative cases."""

    def _pipe(self, raw: str, raw_family: str, confidence: float) -> bool:
        norm = normalize_predicate(raw, raw_family)
        if norm is None:
            return False
        canonical, family = norm
        return should_keep_relationship(family, canonical, confidence)

    def test_buys_team_high_confidence_kept(self):
        assert self._pipe("buys_team", "ownership", 0.90)

    def test_purchases_team_medium_confidence_kept(self):
        assert self._pipe("purchased", "ownership", 0.55)

    def test_committed_capital_to_high_confidence_kept(self):
        assert self._pipe("committed_capital_to", "transaction", 0.80)

    def test_jv_with_high_confidence_kept(self):
        assert self._pipe("jv_with", "partnership", 0.85)

    def test_coaches_dropped_regardless(self):
        assert not self._pipe("coaches", "role", 0.99)

    def test_unknown_predicate_dropped(self):
        assert not self._pipe("likes_sports", "ownership", 0.99)

    def test_low_confidence_high_signal_dropped(self):
        assert not self._pipe("owns", "ownership", 0.30)

    def test_rival_of_dropped(self):
        # rival_of → competes_with (LOW signal) → dropped
        assert not self._pipe("rival_of", "deal_network", 0.99)

    def test_married_to_high_confidence_kept(self):
        assert self._pipe("married_to", "life_event", 0.75)

    def test_divorced_from_high_confidence_kept(self):
        assert self._pipe("divorced_from", "life_event", 0.80)

    def test_ipo_event_kept(self):
        # ipo → exited (HIGH) in investment family
        assert self._pipe("ipo", "transaction", 0.70)


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility shim: app.predicate_normalization
# ─────────────────────────────────────────────────────────────────────────────


class TestCompatibilityShim:
    """Verify that the deprecated predicate_normalization module still works."""

    # ── Old import path works ──────────────────────────────────────────────

    def test_import_normalize_predicate(self):
        from app.predicate_normalization import normalize_predicate  # noqa: F811
        assert callable(normalize_predicate)

    def test_import_get_canonical_predicates_prompt(self):
        from app.predicate_normalization import get_canonical_predicates_prompt  # noqa: F811
        assert callable(get_canonical_predicates_prompt)

    def test_import_canonical_predicates_dict(self):
        from app.predicate_normalization import CANONICAL_PREDICATES  # noqa: F811
        assert isinstance(CANONICAL_PREDICATES, dict)

    # ── CANONICAL_PREDICATES dict is non-empty and well-formed ─────────────

    def test_canonical_predicates_dict_is_nonempty(self):
        from app.predicate_normalization import CANONICAL_PREDICATES
        assert len(CANONICAL_PREDICATES) > 0

    def test_canonical_predicates_has_ownership_family(self):
        from app.predicate_normalization import CANONICAL_PREDICATES
        assert "ownership" in CANONICAL_PREDICATES
        assert "owns" in CANONICAL_PREDICATES["ownership"]

    def test_canonical_predicates_has_investment_family(self):
        from app.predicate_normalization import CANONICAL_PREDICATES
        assert "investment" in CANONICAL_PREDICATES

    def test_canonical_predicates_has_role_family(self):
        from app.predicate_normalization import CANONICAL_PREDICATES
        assert "role" in CANONICAL_PREDICATES

    # ── Old return contract: always tuple, never None ──────────────────────

    def test_known_predicate_returns_tuple(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("owns", "ownership")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_unknown_predicate_returns_tuple_not_none(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("likes_dogs", "ownership")
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_unknown_predicate_no_family_defaults_to_deal_network(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("random_unknown_verb")
        assert result is not None
        canonical, family = result
        assert canonical == "random_unknown_verb"
        assert family == "deal_network"

    def test_unknown_predicate_with_family_preserves_family(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("random_unknown", "ownership")
        assert result == ("random_unknown", "ownership")

    def test_empty_predicate_returns_tuple(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("")
        assert result is not None
        assert isinstance(result, tuple)

    # ── Known predicates delegate correctly to ontology ─────────────────────

    def test_buys_delegates_to_owns(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("buys", "ownership")
        assert result == ("owns", "ownership")

    def test_purchased_delegates_to_owns(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("purchased", "ownership")
        assert result == ("owns", "ownership")

    def test_invested_in_delegates_correctly(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("invested_in", "investment")
        assert result == ("invested_in", "investment")

    def test_ceo_of_delegates_correctly(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("ceo_of", "role")
        assert result == ("ceo_of", "role")

    def test_cross_family_buys_no_hint(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("buys")
        assert result == ("owns", "ownership")

    def test_case_insensitive(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("OWNS", "ownership")
        assert result == ("owns", "ownership")

    def test_hyphenated_input(self):
        from app.predicate_normalization import normalize_predicate
        result = normalize_predicate("ceo-of", "role")
        assert result == ("ceo_of", "role")

    # ── get_canonical_predicates_prompt delegation ──────────────────────────

    def test_prompt_delegation_returns_string(self):
        from app.predicate_normalization import get_canonical_predicates_prompt
        prompt = get_canonical_predicates_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_prompt_delegation_matches_ontology(self):
        from app.predicate_normalization import (
            get_canonical_predicates_prompt as shim_prompt,
        )
        from app.kg_ontology import (
            get_canonical_predicates_prompt as ontology_prompt,
        )
        assert shim_prompt() == ontology_prompt()

    def test_prompt_contains_key_predicates(self):
        from app.predicate_normalization import get_canonical_predicates_prompt
        prompt = get_canonical_predicates_prompt()
        for pred in ("owns", "invested_in", "ceo_of", "partnered_on_deal"):
            assert pred in prompt, f"Key predicate '{pred}' missing from prompt"

    def test_prompt_excludes_low_signal_predicates(self):
        from app.predicate_normalization import get_canonical_predicates_prompt
        prompt = get_canonical_predicates_prompt()
        assert "coaches" not in prompt

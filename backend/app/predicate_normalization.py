"""
Backward-compatible predicate normalization shim.

.. deprecated::
    This module is a thin wrapper kept for backward compatibility.
    All new code should import directly from :mod:`app.kg_ontology`, which
    is the single source of truth for the KG ontology, entity types,
    relationship families, normalization, and relevance filtering.

Old callers that do::

    from app.predicate_normalization import normalize_predicate
    from app.predicate_normalization import get_canonical_predicates_prompt

will continue to work without changes.  The only behavioral difference is
that ``normalize_predicate`` here **always** returns ``tuple[str, str]``
(never ``None``), matching the original contract.  When the new ontology
cannot resolve a predicate, a safe fallback is returned.
"""
from __future__ import annotations

from app import kg_ontology as _ontology

# ── Static backward-compatible alias ──────────────────────────────────────────
# Old code may reference ``CANONICAL_PREDICATES``.  We expose a simplified
# static dict derived from the new ontology so attribute access keeps working.

CANONICAL_PREDICATES: dict[str, dict[str, str]] = {}
for _fname, _fam in _ontology.RELATIONSHIP_FAMILIES.items():
    _family_map: dict[str, str] = {}
    # Canonical predicates map to themselves
    for _pname in _fam.predicates:
        _family_map[_pname] = _pname
    # Variants map to their canonical target
    for _variant, _target in _fam.variants.items():
        _family_map[_variant] = _target
    CANONICAL_PREDICATES[_fname] = _family_map


def normalize_predicate(
    predicate: str,
    predicate_family: str = "",
) -> tuple[str, str]:
    """
    Normalize a predicate to its canonical form.

    This is a backward-compatible wrapper around
    :func:`app.kg_ontology.normalize_predicate`.  Unlike the new ontology
    function (which returns ``None`` for unknown predicates), this function
    **always** returns a ``tuple[str, str]`` to preserve the original
    contract that callers depend on.

    Returns:
        ``(canonical_predicate, canonical_family)``.
        If the ontology cannot resolve the predicate, falls back to
        ``(predicate, predicate_family)`` — or ``"deal_network"`` when
        no family was provided.
    """
    result = _ontology.normalize_predicate(predicate, predicate_family)
    if result is not None:
        return result
    # Fallback: preserve old contract — always return a tuple, never None.
    return predicate, predicate_family or "deal_network"


def get_canonical_predicates_prompt() -> str:
    """
    Generate the canonical predicates section for the extraction prompt.

    Delegates entirely to :func:`app.kg_ontology.get_canonical_predicates_prompt`.
    """
    return _ontology.get_canonical_predicates_prompt()

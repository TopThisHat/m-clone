"""KG ontology definitions — entity types, predicate families, and prompt helpers."""
from __future__ import annotations

# Known entity types in the knowledge graph
ENTITY_TYPES: list[str] = [
    "person",
    "company",
    "sports_team",
    "location",
    "product",
    "deal",
    "fund",
    "institution",
    "other",
]

# Predicate families grouping relationship types
PREDICATE_FAMILIES: list[str] = [
    "ownership",
    "employment",
    "transaction",
    "location",
    "partnership",
    "investment",
]


def get_lm_prompt_section() -> str:
    """Return a schema-aware system prompt section describing the KG ontology."""
    entity_list = "\n".join(f"  - {t}" for t in ENTITY_TYPES)
    family_list = "\n".join(f"  - {f}" for f in PREDICATE_FAMILIES)
    return f"""## Knowledge Graph Schema

### Entity Types
{entity_list}

### Relationship Families
{family_list}

When searching or filtering, use these exact values for `entity_type` and `predicate_family` parameters.
"""

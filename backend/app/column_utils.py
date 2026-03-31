"""Shared column classification utilities.

Provides the exact-match ``_classify_columns`` function used as both the
primary classifier (when semantic classification is disabled) and the
fallback inside ``classify_columns_semantic``.
"""
from __future__ import annotations


def _classify_columns(headers: list[str]) -> dict[str, str]:
    """Map column names to their likely role via exact string matching.

    Returns a dict of {header: role} where role is one of:
      entity_label, entity_gwm_id, entity_description,
      attribute (anything else).
    """
    mapping: dict[str, str] = {}
    lower_headers = {h: h.lower().strip() for h in headers}

    for h, lo in lower_headers.items():
        if lo in ("entity", "entity_label", "entity name", "name", "label", "company"):
            mapping[h] = "entity_label"
        elif lo in ("gwm_id", "gwm id", "external_id", "external id"):
            mapping[h] = "entity_gwm_id"
        elif lo in ("entity_description", "description"):
            mapping[h] = "entity_description"
        else:
            mapping[h] = "attribute"
    return mapping

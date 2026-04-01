"""Schema analysis for the document intelligence package.

Implementation lives in ``app.document_intelligence``.  Symbols are re-exported
here so consumers can import from either location.
"""
from __future__ import annotations

from app.document_intelligence import (
    _LOCK_POLL_INTERVAL_SECONDS,
    _LOCK_POLL_TIMEOUT_SECONDS,
    _LOCK_TTL_SECONDS,
    _SCHEMA_CACHE_PREFIX,
    _SCHEMA_LOCK_PREFIX,
    _compute_schema,
    _enrich_sheets_with_llm,
    _extract_markdown_table_as_csv,
    _extract_sheets_from_doc,
    _generate_schema_summary,
    _load_schema,
    _parse_csv_schema,
    _parse_docx_schema,
    _parse_excel_schema,
    _parse_image_schema,
    _parse_pdf_schema,
    _parse_prose_schema,
    _poll_for_schema,
    analyze_schema,
    generate_query_suggestions,
    get_cached_schema,
)

__all__ = [
    "_SCHEMA_CACHE_PREFIX",
    "_SCHEMA_LOCK_PREFIX",
    "_LOCK_TTL_SECONDS",
    "_LOCK_POLL_INTERVAL_SECONDS",
    "_LOCK_POLL_TIMEOUT_SECONDS",
    "analyze_schema",
    "_poll_for_schema",
    "_compute_schema",
    "_extract_sheets_from_doc",
    "_parse_csv_schema",
    "_parse_excel_schema",
    "_parse_pdf_schema",
    "_parse_docx_schema",
    "_parse_image_schema",
    "_parse_prose_schema",
    "_extract_markdown_table_as_csv",
    "_enrich_sheets_with_llm",
    "_generate_schema_summary",
    "_load_schema",
    "get_cached_schema",
    "generate_query_suggestions",
]

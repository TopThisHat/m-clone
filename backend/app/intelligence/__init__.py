"""Document intelligence package.

``models.py`` and ``prompts.py`` own their definitions.
All logic lives in ``app.document_intelligence`` and is surfaced here via
lazy ``__getattr__`` to avoid the circular-import that would arise if
we imported the logic stubs eagerly (they import from document_intelligence,
which imports from this package).
"""
from __future__ import annotations

# ── eagerly-importable sub-modules (no circular deps) ────────────────────
from app.intelligence.models import (
    ColumnClassification,
    ColumnSchema,
    DocumentSchema,
    MatchEntry,
    QueryPlan,
    QueryResult,
    SemanticType,
    SheetSchema,
)
from app.intelligence.prompts import (
    _DEFAULT_PRICING,
    _MAX_COLUMN_NAME_CHARS,
    _MAX_INTENT_CHARS,
    _MAX_SAMPLE_VALUE_CHARS,
    _MODEL_PRICING,
    _SYSTEM_PROMPT_DATA_CONTEXT,
)

# ── lazy re-exports (loaded on first access to avoid circular import) ─────
# These all live in app.document_intelligence, which imports from this package.
# Eagerly importing them here would create a cycle.
_LAZY_SYMBOLS: frozenset[str] = frozenset({
    # classification
    "classify_columns_semantic",
    "_wrap_exact_match",
    "_llm_classify_columns",
    "_safe_semantic_type",
    # schema
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
    # query / cost
    "_DOC_COST_PREFIX",
    "_DOC_COST_TTL_SECONDS",
    "_QUERY_CACHE_PREFIX",
    "_QUERY_KEYS_PREFIX",
    "_QUERY_CACHE_TTL_SECONDS",
    "_TABULAR_SEMAPHORE_LIMIT",
    "_TABULAR_ROWS_PER_CHUNK",
    "_TABULAR_CHUNK_MAX_CHARS",
    "_PROSE_SEMAPHORE_LIMIT",
    "_PROSE_CHUNK_SIZE",
    "_MD_TABLE_ROW_RE",
    "query_document",
    "_query_document_impl",
    "_build_query_plan",
    "_extract_tabular",
    "_parse_markdown_table",
    "_extract_tabular_llm",
    "_chunk_tabular_text",
    "_extract_tabular_chunk",
    "_merge_chunk_results",
    "_extract_prose",
    "_extract_from_chunk",
    "_filter_columns",
    "_get_query_cache_key",
    "_load_query_cache",
    "_store_query_cache",
    "invalidate_query_cache",
    "_check_budget",
    "_log_query_cost",
    "_estimate_cost",
    "_accumulate_usage",
})


def __getattr__(name: str):  # noqa: ANN001, ANN201
    """Lazy-load logic symbols from app.document_intelligence on first access."""
    if name in _LAZY_SYMBOLS:
        import app.document_intelligence as _di  # noqa: PLC0415
        return getattr(_di, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # models
    "SemanticType",
    "ColumnClassification",
    "ColumnSchema",
    "SheetSchema",
    "DocumentSchema",
    "QueryPlan",
    "MatchEntry",
    "QueryResult",
    # prompts
    "_MAX_COLUMN_NAME_CHARS",
    "_MAX_SAMPLE_VALUE_CHARS",
    "_MAX_INTENT_CHARS",
    "_SYSTEM_PROMPT_DATA_CONTEXT",
    "_MODEL_PRICING",
    "_DEFAULT_PRICING",
    # logic (lazy)
    "classify_columns_semantic",
    "_wrap_exact_match",
    "_llm_classify_columns",
    "_safe_semantic_type",
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
    "_DOC_COST_PREFIX",
    "_DOC_COST_TTL_SECONDS",
    "_QUERY_CACHE_PREFIX",
    "_QUERY_KEYS_PREFIX",
    "_QUERY_CACHE_TTL_SECONDS",
    "_TABULAR_SEMAPHORE_LIMIT",
    "_TABULAR_ROWS_PER_CHUNK",
    "_TABULAR_CHUNK_MAX_CHARS",
    "_PROSE_SEMAPHORE_LIMIT",
    "_PROSE_CHUNK_SIZE",
    "_MD_TABLE_ROW_RE",
    "query_document",
    "_query_document_impl",
    "_build_query_plan",
    "_extract_tabular",
    "_parse_markdown_table",
    "_extract_tabular_llm",
    "_chunk_tabular_text",
    "_extract_tabular_chunk",
    "_merge_chunk_results",
    "_extract_prose",
    "_extract_from_chunk",
    "_filter_columns",
    "_get_query_cache_key",
    "_load_query_cache",
    "_store_query_cache",
    "invalidate_query_cache",
    "_check_budget",
    "_log_query_cost",
    "_estimate_cost",
    "_accumulate_usage",
]

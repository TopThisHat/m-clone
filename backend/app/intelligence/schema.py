"""Schema analysis for the document intelligence package."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from typing import Any

from app.config import settings
from app.document_chunking import split_excel_sheets
from app.intelligence.models import (
    ColumnSchema,
    DocumentSchema,
    SemanticType,
    SheetSchema,
)
from app.intelligence.prompts import (
    _MAX_COLUMN_NAME_CHARS,
    _MAX_SAMPLE_VALUE_CHARS,
    _SYSTEM_PROMPT_DATA_CONTEXT,
)
from app.openai_factory import get_openai_client
from app.redis_client import DocumentSession, get_redis

logger = logging.getLogger(__name__)

_SCHEMA_CACHE_PREFIX = "doc_schema:"
_SCHEMA_LOCK_PREFIX = "doc_schema_lock:"
_LOCK_TTL_SECONDS = 30
_LOCK_POLL_INTERVAL_SECONDS = 0.5
_LOCK_POLL_TIMEOUT_SECONDS = 15.0


def _safe_semantic_type(value: str) -> SemanticType:
    """Return SemanticType from string, defaulting to generic on invalid values."""
    try:
        return SemanticType(value)
    except ValueError:
        return SemanticType.generic


async def analyze_schema(
    session_key: str,
    session: DocumentSession,
) -> DocumentSchema | None:
    """Analyse the schema of a document session and cache the result in Redis.

    Returns the cached DocumentSchema if already computed, otherwise calls the
    LLM, caches the result, and returns it.  Returns None on any failure so
    that background-task callers do not propagate errors.

    Distributed lock prevents duplicate LLM calls for concurrent uploads of
    the same session key.
    """
    cache_key = f"{_SCHEMA_CACHE_PREFIX}{session_key}"
    lock_key = f"{_SCHEMA_LOCK_PREFIX}{session_key}"
    ttl = settings.redis_ttl_hours * 3600

    try:
        redis = await get_redis()
    except RuntimeError as exc:
        logger.warning("analyze_schema: Redis unavailable — skipping schema analysis: %s", exc)
        return None

    # --- Cache hit check ---
    try:
        cached_raw = await redis.get(cache_key)
        if cached_raw:
            await redis.expire(cache_key, ttl)
            return DocumentSchema.model_validate_json(cached_raw)
    except Exception as exc:
        logger.warning("analyze_schema: cache read failed: %s", exc)

    # --- Acquire distributed lock ---
    try:
        acquired = await redis.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception as exc:
        logger.warning("analyze_schema: lock acquisition failed: %s", exc)
        return None

    if not acquired:
        # Another worker holds the lock — poll for the cached result
        return await _poll_for_schema(redis, cache_key, ttl)

    # --- Compute schema ---
    try:
        schema = await _compute_schema(session)
        if schema is None:
            return None
        schema_json = schema.model_dump_json()
        try:
            await redis.setex(cache_key, ttl, schema_json)
        except Exception as exc:
            logger.warning("analyze_schema: cache write failed: %s", exc)
        return schema
    except Exception as exc:
        logger.warning("analyze_schema: schema computation failed: %s", exc)
        return None
    finally:
        try:
            await redis.delete(lock_key)
        except Exception:
            pass


async def _poll_for_schema(
    redis: Any,
    cache_key: str,
    ttl: int,
) -> DocumentSchema | None:
    """Poll Redis for a cached schema with backoff until timeout."""
    elapsed = 0.0
    while elapsed < _LOCK_POLL_TIMEOUT_SECONDS:
        await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        elapsed += _LOCK_POLL_INTERVAL_SECONDS
        try:
            raw = await redis.get(cache_key)
            if raw:
                await redis.expire(cache_key, ttl)
                return DocumentSchema.model_validate_json(raw)
        except Exception:
            pass
    logger.warning("analyze_schema: timed out waiting for concurrent schema computation")
    return None


async def _compute_schema(session: DocumentSession) -> DocumentSchema | None:
    """Build a DocumentSchema from the session's extracted texts."""
    if not session.texts or not any(session.texts):
        return None

    all_sheets: list[SheetSchema] = []
    overall_types: list[str] = []

    for i, text in enumerate(session.texts):
        if not text or not text.strip():
            continue
        meta = session.metadata[i] if i < len(session.metadata) else {}
        doc_type = meta.get("type", "unknown")

        doc_sheets, inferred_type = _extract_sheets_from_doc(text, doc_type)
        all_sheets.extend(doc_sheets)
        overall_types.append(inferred_type)

    if not all_sheets and not overall_types:
        return None

    # Determine aggregate document_type
    unique_types = set(overall_types)
    if unique_types == {"tabular"}:
        aggregate_type = "tabular"
    elif unique_types == {"prose"}:
        aggregate_type = "prose"
    else:
        aggregate_type = "mixed" if unique_types else "prose"

    # For tabular docs: refine column metadata via LLM
    if aggregate_type in ("tabular", "mixed") and all_sheets:
        all_sheets = await _enrich_sheets_with_llm(all_sheets, aggregate_type)

    summary = await _generate_schema_summary(all_sheets, aggregate_type, session)

    return DocumentSchema(
        document_type=aggregate_type,
        sheets=all_sheets,
        total_sheets=len(all_sheets),
        summary=summary,
    )


def _extract_sheets_from_doc(
    text: str,
    doc_type: str,
) -> tuple[list[SheetSchema], str]:
    """Extract SheetSchema entries and document type from a single document text."""
    if doc_type in ("csv", "tsv"):
        return _parse_csv_schema(text), "tabular"

    if doc_type in ("xlsx", "xls"):
        return _parse_excel_schema(text), "tabular"

    if doc_type == "pdf":
        return _parse_pdf_schema(text)

    if doc_type == "docx":
        return _parse_docx_schema(text)

    if doc_type == "image":
        return _parse_image_schema(text), "prose"

    # Fallback: treat as prose
    return _parse_prose_schema(text), "prose"


def _parse_csv_schema(text: str) -> list[SheetSchema]:
    """Parse CSV/TSV text to extract column headers and sample values."""
    try:
        sniffer = csv.Sniffer()
        sample = text[:4096]
        try:
            dialect = sniffer.sniff(sample)
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows: list[dict[str, str]] = []
        for i, row in enumerate(reader):
            if i >= 5:
                break
            rows.append(row)

        if not rows:
            return [SheetSchema(name="default", low_content=True)]

        headers = list(rows[0].keys())
        columns: list[ColumnSchema] = []
        for header in headers:
            safe_header = header[:_MAX_COLUMN_NAME_CHARS]
            sample_vals = [
                str(r.get(header, ""))[:_MAX_SAMPLE_VALUE_CHARS]
                for r in rows
                if r.get(header)
            ]
            columns.append(ColumnSchema(
                name=safe_header,
                sample_values=sample_vals,
            ))

        return [SheetSchema(
            name="default",
            columns=columns,
            low_content=len(rows) < 3,
        )]
    except Exception as exc:
        logger.warning("_parse_csv_schema failed: %s", exc)
        return [SheetSchema(name="default", low_content=True)]


def _parse_excel_schema(text: str) -> list[SheetSchema]:
    """Parse Excel text (split by sheet headers) to extract per-sheet schemas."""
    sheet_texts = split_excel_sheets(text)
    sheets: list[SheetSchema] = []
    for sheet_name, sheet_text in sheet_texts:
        if sheet_name == "_preamble":
            continue
        sub_sheets = _parse_csv_schema(sheet_text)
        for s in sub_sheets:
            sheets.append(SheetSchema(
                name=sheet_name,
                columns=s.columns,
                low_content=s.low_content,
            ))
    return sheets if sheets else [SheetSchema(name="Sheet1", low_content=True)]


def _parse_pdf_schema(text: str) -> tuple[list[SheetSchema], str]:
    """Detect if PDF contains markdown tables; route to tabular or prose."""
    table_lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(table_lines) >= 3:
        sheets = _parse_csv_schema(_extract_markdown_table_as_csv(text))
        return sheets, "tabular"
    return _parse_prose_schema(text), "prose"


def _parse_docx_schema(text: str) -> tuple[list[SheetSchema], str]:
    """Apply same hybrid tabular+prose logic as PDF for DOCX."""
    return _parse_pdf_schema(text)


def _parse_image_schema(text: str) -> list[SheetSchema]:
    """Return entity-based schema sheet for image (prose) documents."""
    return _parse_prose_schema(text)


def _parse_prose_schema(text: str) -> list[SheetSchema]:
    """Return empty sheets array for prose/unstructured documents per spec Decision 2."""
    return []


def _extract_markdown_table_as_csv(text: str) -> str:
    """Extract the first markdown table from text and convert to CSV-like string."""
    lines = text.splitlines()
    table_lines: list[str] = []
    in_table = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("|"):
            in_table = True
            if not re.match(r"^\|[\s\-:| ]+\|$", stripped):
                table_lines.append(stripped)
        elif in_table:
            break
    return "\n".join(table_lines)


async def _enrich_sheets_with_llm(
    sheets: list[SheetSchema],
    document_type: str,
) -> list[SheetSchema]:
    """Optionally enhance column semantic types via LLM for tabular documents."""
    sheets_data = [
        {
            "name": s.name,
            "columns": [
                {
                    "name": c.name[:_MAX_COLUMN_NAME_CHARS],
                    "sample_values": [v[:_MAX_SAMPLE_VALUE_CHARS] for v in c.sample_values[:3]],
                }
                for c in s.columns[:20]
            ],
        }
        for s in sheets[:10]
    ]
    truncated = len(sheets) > 10

    prompt = f"""Analyse the following document schema and return enriched column information.
For each column, determine:
- inferred_type: the data type (text, numeric, date, boolean, etc.)
- semantic_type: one of person, organization, location, date, financial_amount, generic

Document type: {document_type}

Schema:
{json.dumps(sheets_data, ensure_ascii=False)}

Return valid JSON with this shape:
{{
  "sheets": [
    {{
      "name": "...",
      "columns": [
        {{
          "name": "...",
          "inferred_type": "...",
          "semantic_type": "person | organization | location | date | financial_amount | generic"
        }}
      ]
    }}
  ],
  "summary": "one-sentence description of the document"
}}"""

    try:
        client = get_openai_client()
        response = await client.chat.completions.create(
            model=settings.classification_model,
            response_format={"type": "json_object"},
            temperature=0,
            max_completion_tokens=1000,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_DATA_CONTEXT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        enriched_sheets_raw = data.get("sheets", [])
        name_to_enriched = {s["name"]: s for s in enriched_sheets_raw}

        enriched: list[SheetSchema] = []
        for sheet in sheets:
            if sheet.name in name_to_enriched:
                col_data = {
                    c["name"]: c for c in name_to_enriched[sheet.name].get("columns", [])
                }
                new_cols: list[ColumnSchema] = []
                for col in sheet.columns:
                    if col.name in col_data:
                        cd = col_data[col.name]
                        new_cols.append(ColumnSchema(
                            name=col.name,
                            inferred_type=cd.get("inferred_type", col.inferred_type),
                            semantic_type=_safe_semantic_type(
                                cd.get("semantic_type", "generic")
                            ),
                            sample_values=col.sample_values,
                        ))
                    else:
                        new_cols.append(col)
                enriched.append(SheetSchema(
                    name=sheet.name,
                    columns=new_cols,
                    low_content=sheet.low_content,
                    truncated=sheet.truncated or truncated,
                ))
            else:
                enriched.append(sheet)
        return enriched
    except Exception as exc:
        logger.warning("_enrich_sheets_with_llm failed: %s", exc)
        return sheets


async def _generate_schema_summary(
    sheets: list[SheetSchema],
    document_type: str,
    session: DocumentSession,
) -> str:
    """Generate a brief summary of the document schema."""
    if sheets:
        col_names = [c.name for s in sheets for c in s.columns[:5]]
        return (
            f"{document_type.capitalize()} document with "
            f"{len(sheets)} sheet(s). "
            f"Columns include: {', '.join(col_names[:10])}."
        )
    return f"{document_type.capitalize()} document."


async def _load_schema(session_key: str) -> DocumentSchema | None:
    """Load a cached schema from Redis without triggering a new computation."""
    cache_key = f"{_SCHEMA_CACHE_PREFIX}{session_key}"
    ttl = settings.redis_ttl_hours * 3600
    try:
        redis = await get_redis()
        raw = await redis.get(cache_key)
        if raw:
            await redis.expire(cache_key, ttl)
            return DocumentSchema.model_validate_json(raw)
    except Exception as exc:
        logger.warning("_load_schema: failed to read cache: %s", exc)
    return None


async def get_cached_schema(session_key: str) -> DocumentSchema | None:
    """Return the cached DocumentSchema for a session if available, else None."""
    return await _load_schema(session_key)


def generate_query_suggestions(schema: DocumentSchema, filename: str = "") -> list[str]:
    """Generate up to 3 contextual query suggestions from document schema.

    Heuristic: prefer financial → person/org → date columns for targeted
    questions, then fall back to generic prompts.
    """
    suggestions: list[str] = []
    all_columns = [c for s in schema.sheets for c in s.columns]

    financial_cols = [c for c in all_columns if c.semantic_type == SemanticType.financial_amount]
    person_cols = [c for c in all_columns if c.semantic_type == SemanticType.person]
    date_cols = [c for c in all_columns if c.semantic_type == SemanticType.date]
    org_cols = [c for c in all_columns if c.semantic_type == SemanticType.organization]

    if financial_cols:
        suggestions.append(f"What is the total {financial_cols[0].name}?")
    if person_cols:
        suggestions.append(f"List all {person_cols[0].name}s")
    elif org_cols:
        suggestions.append(f"List all {org_cols[0].name}s")
    if date_cols and len(suggestions) < 3:
        suggestions.append(f"What is the date range in {date_cols[0].name}?")

    fallback = [
        f"Summarize the key data in {filename}" if filename else "Summarize the key data",
        "What are the most common values in this dataset?",
        "Show me the first 10 rows of data",
    ]
    for g in fallback:
        if len(suggestions) >= 3:
            break
        suggestions.append(g)

    return suggestions[:3]


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

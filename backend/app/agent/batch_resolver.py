"""Batch entity resolution for the Autonomous Bulk Entity Extraction & Client Lookup feature.

Provides four capabilities:

  1. batch_resolve_clients()         — resolve a list of names against the client directory
                                       with concurrency control, per-item error isolation,
                                       per-call timeout, and overall batch timeout.
  2. format_results_as_markdown()    — render batch results as a markdown table with summary.
  3. format_results_as_compact_json() — render batch results as a compact JSON string
                                        (preferred default; ~40 %+ smaller than markdown).
  4. extract_person_names()          — LLM-backed name extraction from arbitrary document
                                       text, with automatic chunking for large inputs.

Reference: openspec/changes/autonomous-bulk-entity-lookup/
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agent.client_resolver import resolve_client
from app.db.client_lookup import normalize_name
from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────

# Maximum number of resolve_client() calls running at the same time.
_BATCH_CONCURRENCY = 10

# Timeout (seconds) for a single resolve_client() call within a batch.
_PER_CALL_TIMEOUT = 10.0

# Timeout (seconds) for the entire batch_resolve_clients() operation.
_BATCH_TIMEOUT = 120.0

# Characters per chunk when splitting large documents for extraction.
# 8000 chars is ~2000 tokens, well within gpt-4o-mini's context window while
# leaving headroom for the system prompt and JSON response.
_CHUNK_SIZE = 8_000

# Overlap between adjacent chunks so names near chunk boundaries are not lost.
_CHUNK_OVERLAP = 200

# LLM model used for entity extraction (same family as client_resolver).
_EXTRACTION_MODEL = "gpt-4o-mini"

# Timeout per LLM extraction call, in seconds.
_EXTRACTION_TIMEOUT = 30.0

# ── Extraction prompt ─────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = """\
You are a named-entity extraction specialist focused exclusively on PERSON NAMES.

Your task is to extract every person name from the provided text. The text may be:
- CSV data (names in columns, possibly with headers like "Owner", "Contact", "Name")
- Prose paragraphs (biographical text, news articles, reports)
- Tables (aligned columns, pipe-separated, or space-padded)
- Mixed formats combining any of the above
- Text with footnotes, captions, parenthetical references, and headers

EXTRACTION RULES:
1. Extract ALL person names you can identify — err on the side of INCLUSION.
   A false positive (extracting a non-person) is preferable to missing a real person.
2. Return each name in its natural form as it appears in the text
   (e.g. "Robert Kraft", "Dr. Jane Smith", "J. Smith").
3. Treat name variations as SEPARATE entries:
   - "Robert Kraft" and "Bob Kraft" are two entries (the lookup layer handles nicknames).
4. Do NOT extract company names, place names, or other non-person entities.
5. Do NOT deduplicate — return every distinct surface form you encounter.
6. Do NOT include generic role words without a name ("the chairman", "his son").

RESPONSE FORMAT:
Respond with a JSON object containing a single key "names" whose value is an array of strings.
No markdown fences, no explanation.
Example: {"names": ["John Smith", "Jane Doe", "Robert Kraft"]}
If no person names are found, return: {"names": []}"""


# ── Chunking ──────────────────────────────────────────────────────────────────


def _split_into_chunks(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks for LLM extraction.

    Chunks are split on whitespace boundaries to avoid cutting mid-word.
    The overlap window allows names that span a boundary to appear in full
    in at least one chunk.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        if end >= text_len:
            chunks.append(text[start:])
            break

        # Walk back from `end` to the nearest whitespace so we don't cut mid-word.
        boundary = text.rfind(" ", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end  # no whitespace found; hard-cut

        chunks.append(text[start:boundary])
        # Next chunk starts `overlap` chars before the boundary so names near
        # the boundary are covered in the following chunk.
        start = max(start + 1, boundary - overlap)

    return [c for c in chunks if c.strip()]


# ── LLM extraction call ───────────────────────────────────────────────────────


async def _extract_names_from_chunk(chunk: str) -> list[str]:
    """Run one LLM call to extract person names from a single text chunk.

    Returns an empty list on timeout, API error, or unparseable JSON so the
    caller can safely continue with other chunks.
    """
    client = get_openai_client()

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=_EXTRACTION_MODEL,
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Extract all person names from the following text "
                            "and return them as a JSON object with key \"names\" "
                            "containing an array of strings.\n\n"
                            f"{chunk}"
                        ),
                    },
                ],
            ),
            timeout=_EXTRACTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("batch_resolver: extraction LLM call timed out after %.1fs", _EXTRACTION_TIMEOUT)
        return []
    except Exception as exc:
        logger.warning("batch_resolver: extraction LLM call failed: %s", exc)
        return []

    raw = (response.choices[0].message.content or "").strip()

    # Strip accidental markdown fences (defence-in-depth; json_object mode
    # should prevent them but malformed responses have been observed).
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`").strip()

    try:
        parsed: Any = json.loads(raw)
        # Handle both {"names": [...]} and a bare array [...].
        if isinstance(parsed, list):
            names = parsed
        elif isinstance(parsed, dict):
            # Accept any array-valued key; prefer "names" if present.
            names = parsed.get("names") or next(
                (v for v in parsed.values() if isinstance(v, list)), []
            )
        else:
            logger.warning("batch_resolver: unexpected extraction response type: %s", type(parsed))
            return []

        return [str(n).strip() for n in names if isinstance(n, str) and n.strip()]

    except Exception as exc:
        logger.warning(
            "batch_resolver: could not parse extraction response (%s). Raw: %.200s",
            exc,
            raw,
        )
        return []


# ── Public: extract_person_names ──────────────────────────────────────────────


async def extract_person_names(text: str | None) -> tuple[list[str], int]:
    """Extract all person names from document text using LLM-backed parsing.

    Handles arbitrary formats: CSV, prose, tables, mixed content.
    Large documents are automatically chunked; results are merged and
    deduplicated (case-insensitive, whitespace-normalized) across chunks.

    Name variations ("Robert Kraft" vs "Bob Kraft") are intentionally
    preserved as separate entries — nickname resolution happens at lookup time.

    Args:
        text: Raw document text to extract names from.  May be None.

    Returns:
        A tuple of (deduplicated_names, total_raw_count) where:
          - deduplicated_names is the list of unique person name strings
            (original surface forms).
          - total_raw_count is the number of name mentions before dedup.
        Returns ([], 0) if no names found or if the input is empty.
    """
    if not text or not text.strip():
        return [], 0

    chunks = _split_into_chunks(text)
    logger.debug("batch_resolver: extracting names from %d chunk(s)", len(chunks))

    # Run all chunk extractions concurrently (extraction calls are independent).
    chunk_results = await asyncio.gather(
        *[_extract_names_from_chunk(chunk) for chunk in chunks],
        return_exceptions=True,
    )

    # Merge all names, deduplicate by normalized form, preserve first-seen casing.
    seen_normalized: dict[str, str] = {}  # normalized_key -> original surface form
    total_raw_count = 0
    for result in chunk_results:
        if isinstance(result, BaseException):
            logger.warning("batch_resolver: chunk extraction raised: %s", result)
            continue
        total_raw_count += len(result)
        for name in result:
            key = normalize_name(name).lower()
            if key and key not in seen_normalized:
                seen_normalized[key] = name

    return list(seen_normalized.values()), total_raw_count


# ── Deduplication for batch input ─────────────────────────────────────────────


def _build_dedup_map(
    people: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate entries by normalized name (case-insensitive).

    When the same normalized name appears multiple times (possibly with
    different companies), the first occurrence wins for the lookup.

    Returns:
        List of deduplicated entries to look up.
    """
    unique_entries: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for entry in people:
        raw_name = (entry.get("name") or "").strip()
        normalized = normalize_name(raw_name)
        dedup_key = normalized.lower()

        if not dedup_key:
            continue

        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            unique_entries.append({
                "name": normalized,
                "company": entry.get("company"),
                "_original_name": raw_name,
                "_dedup_key": dedup_key,
            })

    return unique_entries


# ── Public: batch_resolve_clients ─────────────────────────────────────────────


async def batch_resolve_clients(
    people: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve a list of person entries against the client directory.

    Each entry should be a dict with:
      - "name" (str, required): the person's name.
      - "company" (str | None, optional): company for disambiguation.

    Processing guarantees:
      - At most _BATCH_CONCURRENCY (10) concurrent resolve_client() calls.
      - Per-item exceptions are caught; the batch continues for all other names.
      - Names are deduplicated (case-insensitive, whitespace-normalized) before
        lookup; each unique name is resolved exactly once.
      - An empty input list returns an empty list.

    Returns a list of result dicts, one per UNIQUE input name, each containing:
      - "name" (str): original name as provided.
      - "status" (str): "matched", "no_match", or "error".
      - "gwm_id" (str | None): GWM client ID when matched.
      - "confidence" (float | None): match confidence 0.0–1.0 when matched.
      - "error" (str | None): error description when status == "error".
      - "result" (LookupResult | None): full LookupResult for introspection.
    """
    if not people:
        return []

    unique_entries = _build_dedup_map(people)
    logger.info(
        "batch_resolver: resolving %d unique name(s) from %d input(s)",
        len(unique_entries),
        len(people),
    )

    semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)
    total_count = len(unique_entries)
    completed_count = 0
    progress_lock = asyncio.Lock()

    async def _resolve_one(entry: dict[str, Any]) -> dict[str, Any]:
        nonlocal completed_count
        name = entry["name"]
        company = entry.get("company")
        original_name = entry.get("_original_name", name)

        async with semaphore:
            try:
                lookup_result = await asyncio.wait_for(
                    resolve_client(name=name, company=company),
                    timeout=_PER_CALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "batch_resolver: resolve_client timed out for name=%r after %.1fs",
                    name,
                    _PER_CALL_TIMEOUT,
                )
                result = {
                    "name": original_name,
                    "status": "error",
                    "gwm_id": None,
                    "confidence": None,
                    "error": f"Client resolution timed out after {_PER_CALL_TIMEOUT}s",
                    "result": None,
                }
            except Exception as exc:
                logger.warning(
                    "batch_resolver: resolve_client raised for name=%r: %s",
                    name,
                    exc,
                )
                result = {
                    "name": original_name,
                    "status": "error",
                    "gwm_id": None,
                    "confidence": None,
                    "error": str(exc),
                    "result": None,
                }
            else:
                if lookup_result.match_found:
                    result = {
                        "name": original_name,
                        "status": "matched",
                        "gwm_id": lookup_result.gwm_id,
                        "confidence": lookup_result.confidence,
                        "error": None,
                        "result": lookup_result,
                    }
                else:
                    result = {
                        "name": original_name,
                        "status": "no_match",
                        "gwm_id": None,
                        "confidence": None,
                        "error": None,
                        "result": lookup_result,
                    }

        # Log progress every 50 completions for large batches.
        async with progress_lock:
            completed_count += 1
            if total_count >= 50 and completed_count % 50 == 0:
                logger.info(
                    "batch_resolver: progress %d/%d lookups completed",
                    completed_count,
                    total_count,
                )

        return result

    tasks = [asyncio.create_task(_resolve_one(entry)) for entry in unique_entries]
    done, pending = await asyncio.wait(tasks, timeout=_BATCH_TIMEOUT)

    # Cancel any tasks that didn't finish within the overall timeout.
    for t in pending:
        t.cancel()

    if pending:
        logger.warning(
            "batch_resolver: overall timeout (%.1fs) reached — %d/%d tasks still pending",
            _BATCH_TIMEOUT,
            len(pending),
            len(tasks),
        )

    # Build output preserving original order.
    output: list[dict[str, Any]] = []
    for i, task in enumerate(tasks):
        if task in done:
            try:
                result = task.result()
            except BaseException as exc:
                # Should not occur since _resolve_one catches internally, but guard anyway.
                original_name = unique_entries[i].get("_original_name", unique_entries[i]["name"])
                logger.error(
                    "batch_resolver: unexpected exception for entry %d (%r): %s",
                    i,
                    original_name,
                    exc,
                )
                output.append({
                    "name": original_name,
                    "status": "error",
                    "gwm_id": None,
                    "confidence": None,
                    "error": f"Unexpected error: {exc}",
                    "result": None,
                })
            else:
                output.append(result)
        else:
            # Task was still pending when the overall timeout fired.
            original_name = unique_entries[i].get("_original_name", unique_entries[i]["name"])
            output.append({
                "name": original_name,
                "status": "error",
                "gwm_id": None,
                "confidence": None,
                "error": f"Batch processing timed out after {_BATCH_TIMEOUT}s",
                "result": None,
            })

    return output


# ── Public: format_results_as_markdown ────────────────────────────────────────


def format_results_as_markdown(results: list[dict[str, Any]]) -> str:
    """Format batch lookup results as a markdown table with a summary line.

    Table columns: #, Entity Name, Client ID, Confidence, Status.

    Summary line (above the table):
      "Processed N names: X matched, Y no match, Z errors"

    Matched rows  — show GWM ID and confidence as a percentage.
    No-match rows — show "—" for ID and confidence, "No match" for status.
    Error rows    — show "—" for ID and confidence, error description for status.

    Args:
        results: List of result dicts as returned by batch_resolve_clients().

    Returns:
        Formatted markdown string.  Returns a plain-text message when the
        input list is empty.
    """
    if not results:
        return "No names provided."

    matched = sum(1 for r in results if r.get("status") == "matched")
    no_match = sum(1 for r in results if r.get("status") == "no_match")
    errors = sum(1 for r in results if r.get("status") == "error")
    total = len(results)

    summary = (
        f"Processed {total} name{'s' if total != 1 else ''}: "
        f"{matched} matched, {no_match} no match, {errors} error{'s' if errors != 1 else ''}"
    )

    header = "| # | Entity Name | Client ID | Confidence | Status |"
    separator = "|---|-------------|-----------|------------|--------|"

    rows: list[str] = []
    for i, r in enumerate(results, start=1):
        name = _escape_md(r.get("name") or "")
        status = r.get("status", "error")

        if status == "matched":
            gwm_id = _escape_md(r.get("gwm_id") or "—")
            confidence = r.get("confidence")
            conf_str = f"{confidence:.0%}" if confidence is not None else "—"
            status_str = "Matched"
        elif status == "no_match":
            gwm_id = "—"
            conf_str = "—"
            status_str = "No match"
        else:
            gwm_id = "—"
            conf_str = "—"
            error_detail = r.get("error") or "Unknown error"
            # Truncate long error messages so they don't break table alignment.
            if len(error_detail) > 80:
                error_detail = error_detail[:77] + "..."
            status_str = _escape_md(f"Error: {error_detail}")

        rows.append(f"| {i} | {name} | {gwm_id} | {conf_str} | {status_str} |")

    table = "\n".join([header, separator] + rows)
    return f"{summary}\n\n{table}"


def _escape_md(text: str) -> str:
    """Escape pipe characters in text so they don't break markdown table cells."""
    return text.replace("|", "\\|")


# ── Public: format_results_as_compact_json ───────────────────────────────────


def format_results_as_compact_json(results: list[dict[str, Any]]) -> str:
    """Format batch lookup results as a compact JSON string.

    Returns a JSON string with the structure::

        {
          "summary": {"total": N, "matched": M, "no_match": X, "errors": Y},
          "results": [
            {"name": "...", "gwm_id": "..." | null,
             "confidence": 0.94 | null,
             "status": "matched" | "no_match" | "error"}
          ]
        }

    All rows are included (no truncation).  Uses ``json.dumps`` with no
    indentation and compact separators for minimal token usage.

    Args:
        results: List of result dicts as returned by batch_resolve_clients().

    Returns:
        Compact JSON string.  Returns a plain-text message when the
        input list is empty.
    """
    if not results:
        return "No names provided."

    matched = sum(1 for r in results if r.get("status") == "matched")
    no_match = sum(1 for r in results if r.get("status") == "no_match")
    errors = sum(1 for r in results if r.get("status") == "error")

    payload = {
        "summary": {
            "total": len(results),
            "matched": matched,
            "no_match": no_match,
            "errors": errors,
        },
        "results": [
            {
                "name": r.get("name") or "",
                "gwm_id": r.get("gwm_id"),
                "confidence": r.get("confidence"),
                "status": r.get("status", "error"),
            }
            for r in results
        ],
    }

    return json.dumps(payload, separators=(",", ":"))

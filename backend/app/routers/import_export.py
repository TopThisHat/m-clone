"""Import / export router for Scout campaign data.

Endpoints:
  POST /{campaign_id}/import/upload   — parse CSV/XLSX, return validated preview
  POST /{campaign_id}/import/commit   — persist previewed rows
  GET  /{campaign_id}/export          — stream matrix data as CSV (task #7)
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_bulk_create_entities,
    db_bulk_create_attributes,
    db_bulk_upsert_cells,
    db_get_campaign,
    db_get_matrix_data,
    db_is_team_member,
    db_list_entities,
    db_list_attributes,
    db_recalculate_scores_from_matrix,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["import-export"])

# Characters that trigger formula execution in spreadsheet apps.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "|", "\t")

# Maximum rows accepted in a single upload to guard memory.
_MAX_UPLOAD_ROWS = 50_000


# ── Request / Response models ────────────────────────────────────────────────


class ImportCommitRequest(BaseModel):
    entities: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []


class ImportErrorDetail(BaseModel):
    """A single row-level validation error from the import upload."""

    row: int            # 1-based row number (row 1 is the header row)
    field: str = ""     # Column name, if applicable
    message: str        # Human-readable error reason


class ErrorReportRequest(BaseModel):
    """Request body for generating an import error report CSV.

    ``rows`` contains the original data rows as parsed from the uploaded file.
    ``errors`` contains the validation errors returned by the upload endpoint.
    Only rows referenced in ``errors`` appear in the output CSV; each gets an
    appended ``_error`` column with the error message.
    """

    rows: list[dict[str, str]]
    errors: list[ImportErrorDetail]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. "
        "Please configure DATABASE_URL.",
    )


async def _get_owned_campaign(campaign_id: str, user_sid: str) -> dict[str, Any]:
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("team_id"):
        if not await db_is_team_member(campaign["team_id"], user_sid):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif campaign["owner_sid"] != user_sid:
        raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


def _sanitize_csv_cell(value: object) -> str:
    """Prefix dangerous cells with a single-quote to prevent CSV formula injection."""
    s = str(value) if value is not None else ""
    if s and s[0] in _CSV_FORMULA_PREFIXES:
        return f"'{s}"
    return s


def _parse_csv_bytes(data: bytes) -> list[dict[str, str]]:
    """Parse CSV (or TSV) bytes into a list of row dicts."""
    text = data.decode("utf-8-sig")
    # Detect delimiter
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= _MAX_UPLOAD_ROWS:
            break
        rows.append(row)
    return rows


def _classify_columns(
    headers: list[str],
) -> dict[str, str]:
    """Map column names to their likely role.

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


def _validate_upload(
    rows: list[dict[str, str]],
    column_map: dict[str, str],
) -> dict[str, Any]:
    """Validate parsed rows and build a preview response.

    Returns:
        {
            "row_count": int,
            "entities": [{"label": ..., "gwm_id": ...}],
            "attributes": [{"label": ...}],
            "cells": [{"entity_label": ..., "attribute_label": ..., "value": ...}],
            "errors": [{"row": int, "message": str}],
        }
    """
    entity_label_col = next(
        (h for h, role in column_map.items() if role == "entity_label"), None
    )
    gwm_id_col = next(
        (h for h, role in column_map.items() if role == "entity_gwm_id"), None
    )
    desc_col = next(
        (h for h, role in column_map.items() if role == "entity_description"), None
    )
    attribute_cols = [h for h, role in column_map.items() if role == "attribute"]

    entities_seen: dict[str, dict[str, Any]] = {}
    attributes_seen: set[str] = set()
    cells: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        label = (row.get(entity_label_col, "") if entity_label_col else "").strip()
        if not label:
            errors.append({"row": i, "message": "Missing entity label"})
            continue

        gwm_id = (row.get(gwm_id_col, "") if gwm_id_col else "").strip() or None
        description = (row.get(desc_col, "") if desc_col else "").strip() or None

        if label not in entities_seen:
            entities_seen[label] = {
                "label": label,
                "gwm_id": gwm_id,
                "description": description,
            }

        for attr_col in attribute_cols:
            value = (row.get(attr_col) or "").strip()
            if value:
                attributes_seen.add(attr_col)
                cells.append({
                    "entity_label": label,
                    "attribute_label": attr_col,
                    "value": value,
                })

    return {
        "row_count": len(rows),
        "column_map": column_map,
        "entities": list(entities_seen.values()),
        "attributes": [{"label": a} for a in sorted(attributes_seen)],
        "cells": cells,
        "errors": errors,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/{campaign_id}/import/upload")
async def upload_import(
    campaign_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Parse an uploaded CSV/TSV file and return a validated preview.

    The response includes entities, attributes, and cell values extracted
    from the file, along with any validation errors.  The caller should
    inspect the preview and then POST to ``/import/commit`` to persist.
    """
    await _get_owned_campaign(campaign_id, user["sub"])

    if file.content_type and file.content_type not in (
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.ms-excel",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. "
            "Upload a CSV or TSV file.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    rows = _parse_csv_bytes(data)
    if not rows:
        raise HTTPException(status_code=400, detail="No data rows found")

    headers = list(rows[0].keys())
    column_map = _classify_columns(headers)

    # If no entity_label column was detected, fail early
    if "entity_label" not in column_map.values():
        raise HTTPException(
            status_code=400,
            detail="No entity label column found. Expected one of: "
            "'entity', 'label', 'name', 'company', 'entity_label'.",
        )

    preview = _validate_upload(rows, column_map)
    return preview


@router.post("/{campaign_id}/import/commit")
async def commit_import(
    campaign_id: str,
    body: ImportCommitRequest,
    user=Depends(get_current_user),
) -> dict[str, Any]:
    """Persist previously previewed import data.

    Accepts the entities, attributes, and cells from the upload preview
    (possibly after user edits) and commits them to the database.
    """
    await _get_owned_campaign(campaign_id, user["sub"])

    result: dict[str, Any] = {
        "entities_inserted": 0,
        "entities_skipped": 0,
        "attributes_inserted": 0,
        "attributes_skipped": 0,
        "cells_upserted": 0,
    }

    try:
        # 1. Create entities
        if body.entities:
            ent_result = await db_bulk_create_entities(campaign_id, body.entities)
            result["entities_inserted"] = len(ent_result["inserted"])
            result["entities_skipped"] = ent_result["skipped"]

        # 2. Create attributes
        if body.attributes:
            attr_result = await db_bulk_create_attributes(campaign_id, body.attributes)
            result["attributes_inserted"] = len(attr_result["inserted"])
            result["attributes_skipped"] = attr_result["skipped"]

        # 3. Upsert cell values — resolve labels to IDs first
        if body.cells:
            ent_data = await db_list_entities(campaign_id, limit=0)
            entities = ent_data.get("entities", ent_data) if isinstance(ent_data, dict) else ent_data
            label_to_eid: dict[str, str] = {}
            for e in entities:
                label_to_eid[e["label"].lower()] = e["id"]

            attr_data = await db_list_attributes(campaign_id)
            label_to_aid: dict[str, str] = {}
            attr_types: dict[str, str] = {}
            for a in attr_data:
                label_to_aid[a["label"].lower()] = a["id"]
                attr_types[a["id"]] = a.get("attribute_type", "text")

            resolved_cells: list[dict[str, Any]] = []
            for cell in body.cells:
                eid = label_to_eid.get(cell["entity_label"].lower())
                aid = label_to_aid.get(cell["attribute_label"].lower())
                if eid and aid:
                    resolved_cells.append({
                        "entity_id": eid,
                        "attribute_id": aid,
                        "value": cell["value"],
                        "attribute_type": attr_types.get(aid, "text"),
                    })

            if resolved_cells:
                upserted = await db_bulk_upsert_cells(
                    campaign_id, resolved_cells, updated_by=user["sub"],
                )
                result["cells_upserted"] = len(upserted)

        # 4. Recalculate scores
        try:
            await db_recalculate_scores_from_matrix(campaign_id)
        except Exception:
            logger.exception("Score recalculation failed after import commit")

    except DatabaseNotConfigured:
        raise _no_db()

    return result


@router.post("/{campaign_id}/import/error-report")
async def download_error_report(
    campaign_id: str,
    body: ErrorReportRequest,
    user=Depends(get_current_user),
) -> StreamingResponse:
    """Generate a CSV error report for failed import rows.

    Returns a CSV containing only the rows that had validation errors, with
    an appended ``_error`` column describing the failure reason.  Column order
    matches the original upload file.  All cell values are sanitized against
    CSV formula injection.
    """
    await _get_owned_campaign(campaign_id, user["sub"])

    if not body.errors:
        raise HTTPException(status_code=400, detail="No errors to report")

    # Build a mapping from 1-based row number → error messages (a row can have
    # multiple errors; they are joined with "; " in the _error column).
    error_by_row: dict[int, list[str]] = {}
    for err in body.errors:
        msgs = error_by_row.setdefault(err.row, [])
        if err.field:
            msgs.append(f"{err.field}: {err.message}")
        else:
            msgs.append(err.message)

    # Determine column headers from the first data row (or body rows list)
    if not body.rows:
        raise HTTPException(status_code=400, detail="No row data provided")

    original_headers = list(body.rows[0].keys())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(original_headers + ["_error"])

    # Rows are 1-indexed where row 1 is the header; data starts at row 2.
    for i, row in enumerate(body.rows, start=2):
        if i not in error_by_row:
            continue
        data_cells = [_sanitize_csv_cell(row.get(h, "")) for h in original_headers]
        error_cell = "; ".join(error_by_row[i])
        writer.writerow(data_cells + [error_cell])

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="import-errors-{campaign_id}.csv"'
            ),
        },
    )


@router.get("/{campaign_id}/export")
async def export_matrix_csv(
    campaign_id: str,
    user=Depends(get_current_user),
) -> StreamingResponse:
    """Export the campaign matrix as a CSV file.

    Columns: Entity, GWM ID, then one column per attribute.
    Cell values are sanitized against formula injection.
    """
    await _get_owned_campaign(campaign_id, user["sub"])

    try:
        matrix = await db_get_matrix_data(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()

    entities: list[dict[str, Any]] = matrix.get("entities", [])
    attributes: list[dict[str, Any]] = matrix.get("attributes", [])
    cells: list[dict[str, Any]] = matrix.get("cells", [])

    # Build lookup: (entity_id, attribute_id) -> display value
    cell_map: dict[tuple[str, str], str] = {}
    for c in cells:
        eid = str(c.get("entity_id", ""))
        aid = str(c.get("attribute_id", ""))
        val = (
            c.get("value_select")
            or (str(c["value_numeric"]) if c.get("value_numeric") is not None else None)
            or (str(c["value_boolean"]) if c.get("value_boolean") is not None else None)
            or c.get("value_text")
            or ""
        )
        cell_map[(eid, aid)] = str(val)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row
    header = ["Entity", "GWM ID"] + [a["label"] for a in attributes]
    writer.writerow(header)

    # Data rows
    for ent in entities:
        eid = str(ent["id"])
        row = [
            _sanitize_csv_cell(ent.get("label", "")),
            _sanitize_csv_cell(ent.get("gwm_id", "")),
        ]
        for attr in attributes:
            aid = str(attr["id"])
            row.append(_sanitize_csv_cell(cell_map.get((eid, aid), "")))
        writer.writerow(row)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="campaign-{campaign_id}-matrix.csv"',
        },
    )

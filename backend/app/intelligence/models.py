"""Pydantic models for the document intelligence package."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SemanticType(str, Enum):
    person = "person"
    organization = "organization"
    location = "location"
    date = "date"
    financial_amount = "financial_amount"
    generic = "generic"


class ColumnClassification(BaseModel):
    role: str  # entity_label | entity_gwm_id | entity_description | attribute
    semantic_type: SemanticType = SemanticType.generic
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class ColumnSchema(BaseModel):
    name: str
    inferred_type: str = ""
    semantic_type: SemanticType = SemanticType.generic
    sample_values: list[str] = []


class SheetSchema(BaseModel):
    name: str
    columns: list[ColumnSchema] = []
    low_content: bool = False
    truncated: bool = False


class DocumentSchema(BaseModel):
    document_type: str  # tabular | prose | mixed
    sheets: list[SheetSchema] = []
    total_sheets: int = 0
    summary: str = ""


class QueryPlan(BaseModel):
    relevant_columns: list[str] = []
    extraction_instruction: str = ""
    document_type: str = "tabular"
    complexity: Literal["simple", "complex"] = "simple"


class MatchEntry(BaseModel):
    value: str | dict[str, str] = ""
    source_column: str | list[str] = ""
    row_numbers: list[int] = []
    confidence: float = 0.0
    text_positions: list[dict[str, int]] = []  # [{"start": int, "end": int}]


class QueryResult(BaseModel):
    matches: list[MatchEntry] = []
    query_interpretation: str = ""
    total_matches: int = 0
    error: str | None = None
    partial: bool = False
    chunks_processed: int = 0
    chunks_total: int = 0


__all__ = [
    "SemanticType",
    "ColumnClassification",
    "ColumnSchema",
    "SheetSchema",
    "DocumentSchema",
    "QueryPlan",
    "MatchEntry",
    "QueryResult",
]

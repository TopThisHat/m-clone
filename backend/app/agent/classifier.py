"""Query classification system for multi-mode agent execution.

Routes user queries to the appropriate ExecutionMode by combining fast
heuristic rules with an LLM fallback for ambiguous cases. The heuristic
layer handles clear-cut patterns (format requests, simple factual questions,
CSV batch operations) while the LLM classifier handles nuanced multi-step
or research queries.

Usage:
    result = await classify_query(query, has_documents=True, doc_metadata=[...])
    config = RUNNER_CONFIGS[result.mode]
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.agent.runner_config import ExecutionMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ClassificationError(Exception):
    """Raised when query classification fails or confidence is too low.

    This is intentionally *not* a fallback to RESEARCH -- callers must
    handle the error explicitly so that misrouted queries are surfaced
    rather than silently degraded.
    """


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    """Immutable result of classifying a user query.

    Attributes:
        mode: The execution mode the query should be routed to.
        confidence: Classifier confidence in the range [0.0, 1.0].
        reasoning: Human-readable explanation of the classification decision.
        estimated_steps: Rough estimate of agent turns needed.
        requires_iteration: Whether the query needs evaluation/refinement loops.
        batch_size: Expected batch size for DATA_PROCESSING, None otherwise.
        source: Origin of the classification -- ``"heuristic"`` or ``"llm"``.
    """

    mode: ExecutionMode
    confidence: float
    reasoning: str
    estimated_steps: int
    requires_iteration: bool
    batch_size: int | None
    source: str  # "heuristic" | "llm"


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD: float = 0.5


# ---------------------------------------------------------------------------
# Heuristic patterns (compiled once at import time for speed)
# ---------------------------------------------------------------------------

# FORMAT_ONLY triggers
_FORMAT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\breformat\b", re.IGNORECASE),
    re.compile(r"\bas\s+a\s+table\b", re.IGNORECASE),
    re.compile(r"\bas\s+bullet\s*points?\b", re.IGNORECASE),
    re.compile(r"\bconvert\s+to\b", re.IGNORECASE),
    re.compile(r"\bsummariz(?:e|ing)\s+(?:this|the\s+above)\b", re.IGNORECASE),
    re.compile(r"\breorganiz(?:e|ing)\b", re.IGNORECASE),
    re.compile(r"\btranslate\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:a\s+)?(?:bullet\s+)?list\b", re.IGNORECASE),
    re.compile(r"\brephrase\b", re.IGNORECASE),
    re.compile(r"\brewrite\b", re.IGNORECASE),
]

# QUICK_ANSWER question starters
_QUICK_ANSWER_STARTS: list[re.Pattern[str]] = [
    re.compile(r"^what\s+is\b", re.IGNORECASE),
    re.compile(r"^who\s+is\b", re.IGNORECASE),
    re.compile(r"^when\s+did\b", re.IGNORECASE),
    re.compile(r"^how\s+much\b", re.IGNORECASE),
    re.compile(r"^what'?s\b", re.IGNORECASE),
]

# Sequential indicators that disqualify QUICK_ANSWER
_SEQUENTIAL_INDICATORS: re.Pattern[str] = re.compile(
    r"\b(?:then|after\s+that|next|subsequently|followed\s+by)\b",
    re.IGNORECASE,
)

# DATA_PROCESSING action verbs
_DATA_ACTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\blook\s*up\b", re.IGNORECASE),
    re.compile(r"\bprocess\b", re.IGNORECASE),
    re.compile(r"\benrich\b", re.IGNORECASE),
    re.compile(r"\bextract\b", re.IGNORECASE),
    re.compile(r"\bcheck\s+which\b", re.IGNORECASE),
    re.compile(r"\bcross[- ]?reference\b", re.IGNORECASE),
    re.compile(r"\bparse\b", re.IGNORECASE),
    re.compile(r"\bbatch\b", re.IGNORECASE),
    re.compile(r"\bfor\s+each\b", re.IGNORECASE),
    re.compile(r"\bevery\s+row\b", re.IGNORECASE),
    re.compile(r"\ball\s+(?:the\s+)?names\b", re.IGNORECASE),
]

# Token count helper (simple whitespace split -- good enough for classification)
_MAX_QUICK_ANSWER_TOKENS: int = 25


def _token_count(text: str) -> int:
    """Approximate token count via whitespace splitting."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Heuristic classifier
# ---------------------------------------------------------------------------


def _heuristic_classify(
    query: str,
    has_documents: bool = False,
    doc_metadata: list[dict[str, Any]] | None = None,
) -> ClassificationResult | None:
    """Fast, deterministic classification for clear-cut query patterns.

    Returns a ClassificationResult when the query unambiguously matches a
    known pattern, or None when the query is ambiguous and should be
    delegated to the LLM classifier.

    Args:
        query: The user's input query text.
        has_documents: Whether uploaded documents are present in the session.
        doc_metadata: Metadata dicts for uploaded documents. A dict with a
            ``"rows"`` key indicates tabular (CSV/spreadsheet) data.

    Returns:
        ClassificationResult with source="heuristic" and confidence=0.9,
        or None if no heuristic rule matches.
    """
    if not query or not query.strip():
        return None

    stripped = query.strip()

    # --- FORMAT_ONLY ---
    for pat in _FORMAT_PATTERNS:
        if pat.search(stripped):
            return ClassificationResult(
                mode=ExecutionMode.FORMAT_ONLY,
                confidence=0.9,
                reasoning=f"Heuristic: query matches format pattern '{pat.pattern}'",
                estimated_steps=1,
                requires_iteration=False,
                batch_size=None,
                source="heuristic",
            )

    # --- DATA_PROCESSING ---
    # Requires documents with tabular data AND an action verb
    if has_documents and doc_metadata:
        has_tabular = any(
            isinstance(meta, dict) and "rows" in meta
            for meta in doc_metadata
        )
        if has_tabular:
            for pat in _DATA_ACTION_PATTERNS:
                if pat.search(stripped):
                    # Estimate batch size from row counts in metadata
                    total_rows = sum(
                        meta.get("rows", 0)
                        for meta in doc_metadata
                        if isinstance(meta, dict) and isinstance(meta.get("rows"), (int, float))
                    )
                    return ClassificationResult(
                        mode=ExecutionMode.DATA_PROCESSING,
                        confidence=0.9,
                        reasoning=f"Heuristic: tabular data present + action verb '{pat.pattern}'",
                        estimated_steps=max(5, total_rows // 10),
                        requires_iteration=False,
                        batch_size=int(total_rows) if total_rows > 0 else None,
                        source="heuristic",
                    )

    # --- QUICK_ANSWER ---
    tokens = _token_count(stripped)
    if tokens < _MAX_QUICK_ANSWER_TOKENS and not _SEQUENTIAL_INDICATORS.search(stripped):
        for pat in _QUICK_ANSWER_STARTS:
            if pat.search(stripped):
                return ClassificationResult(
                    mode=ExecutionMode.QUICK_ANSWER,
                    confidence=0.9,
                    reasoning=f"Heuristic: short query matching question start '{pat.pattern}'",
                    estimated_steps=2,
                    requires_iteration=False,
                    batch_size=None,
                    source="heuristic",
                )

    # --- Ambiguous: fall through to LLM ---
    return None


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT: str = """\
You are a query classification system. Given a user query and context about \
uploaded documents, classify the query into exactly one execution mode.

## Modes

1. **FORMAT_ONLY** - Pure reformatting of existing content. No data lookup needed.
   Signals: "reformat", "as a table", "bullet points", "summarize this", "translate"
   Estimated steps: 1

2. **QUICK_ANSWER** - Simple factual question answerable in 1-3 tool calls.
   Signals: short query, starts with "what is", "who is", "how much", no sequential steps
   Estimated steps: 1-3

3. **RESEARCH** - Deep, multi-angle investigation requiring plan creation and \
evaluation cycles. Multiple sources, synthesis, and quality assessment.
   Signals: "analyze", "compare", "competitive landscape", "market trends", \
"deep dive", open-ended questions, multi-faceted topics
   Estimated steps: 8-20

4. **DATA_PROCESSING** - Batch operations on uploaded tabular data. Entity \
resolution, enrichment, cross-referencing across rows.
   Signals: uploaded CSV/spreadsheet, "for each row", "look up all", "batch", \
"enrich", "process", action verbs + tabular data
   Estimated steps: varies by row count

5. **TASK_EXECUTION** - Complex multi-step workflows combining research AND \
data processing. Requires an execution plan with ordered phases.
   Signals: multiple distinct phases ("research X, then look up Y, then create Z"), \
combines research with batch operations, sequential dependencies
   Estimated steps: 15-50

## Context
- has_documents: {has_documents}
- doc_metadata: {doc_metadata}

## Output
Respond with a JSON object (no markdown fences):
{{
  "mode": "<one of: format_only, quick_answer, research, data_processing, task_execution>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "estimated_steps": <int>,
  "requires_iteration": <bool>,
  "batch_size": <int or null>
}}
"""

_LLM_CLASSIFY_TIMEOUT: float = 5.0
_LLM_MODEL: str = "gpt-4.1"


async def _llm_classify(
    query: str,
    has_documents: bool = False,
    doc_metadata: list[dict[str, Any]] | None = None,
) -> ClassificationResult | None:
    """Classify a query using GPT-4.1 structured JSON output.

    Falls back to None on timeout, API errors, or malformed responses.
    Callers should treat None as "classification failed".

    Args:
        query: The user's input query text.
        has_documents: Whether uploaded documents are present in the session.
        doc_metadata: Metadata dicts for uploaded documents.

    Returns:
        ClassificationResult with source="llm", or None on failure.
    """
    from app.openai_factory import get_openai_client

    client = get_openai_client()

    system_msg = _LLM_SYSTEM_PROMPT.format(
        has_documents=has_documents,
        doc_metadata=json.dumps(doc_metadata or [], default=str),
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=256,
            ),
            timeout=_LLM_CLASSIFY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "LLM classifier timed out after %.1fs for query: %.80s",
            _LLM_CLASSIFY_TIMEOUT,
            query,
        )
        return None
    except Exception:
        logger.warning(
            "LLM classifier API error for query: %.80s",
            query,
            exc_info=True,
        )
        return None

    # Parse response
    try:
        raw = response.choices[0].message.content
        if raw is None:
            logger.warning("LLM classifier returned empty content")
            return None

        data = json.loads(raw)

        mode_str = data.get("mode", "")
        try:
            mode = ExecutionMode(mode_str)
        except ValueError:
            logger.warning("LLM classifier returned invalid mode: %s", mode_str)
            return None

        confidence = float(data.get("confidence", 0.0))
        reasoning = str(data.get("reasoning", ""))
        estimated_steps = int(data.get("estimated_steps", 1))
        requires_iteration = bool(data.get("requires_iteration", False))
        batch_size_raw = data.get("batch_size")
        batch_size = int(batch_size_raw) if batch_size_raw is not None else None

        return ClassificationResult(
            mode=mode,
            confidence=confidence,
            reasoning=f"LLM: {reasoning}",
            estimated_steps=estimated_steps,
            requires_iteration=requires_iteration,
            batch_size=batch_size,
            source="llm",
        )

    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        logger.warning(
            "LLM classifier returned malformed response for query: %.80s",
            query,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Main classify function
# ---------------------------------------------------------------------------


async def classify_query(
    query: str,
    has_documents: bool = False,
    doc_metadata: list[dict[str, Any]] | None = None,
    is_followup: bool = False,
    execution_mode_override: str | None = None,
) -> ClassificationResult:
    """Classify a user query into an ExecutionMode.

    Applies classification in this order:

    1. **Mode override** -- if ``execution_mode_override`` is provided, the
       classifier is bypassed entirely and the specified mode is returned.
    2. **Heuristic** -- fast regex-based rules for clear-cut patterns.
    3. **LLM fallback** -- GPT-4.1 structured output for ambiguous queries.

    Raises ClassificationError if both heuristic and LLM fail, or if the
    resulting confidence is below the threshold (0.5). This is intentional:
    we do NOT silently default to RESEARCH on failure.

    Args:
        query: The user's input query text.
        has_documents: Whether uploaded documents are present in the session.
        doc_metadata: Metadata dicts for uploaded documents.
        is_followup: Whether this query is a follow-up in an ongoing conversation.
        execution_mode_override: Explicit mode string to bypass classification.

    Returns:
        ClassificationResult describing the selected mode and metadata.

    Raises:
        ClassificationError: If classification fails or confidence is too low.
    """
    # --- Mode override ---
    if execution_mode_override is not None:
        try:
            mode = ExecutionMode(execution_mode_override)
        except ValueError:
            raise ClassificationError(
                f"Invalid execution mode override: {execution_mode_override!r}. "
                f"Valid modes: {[m.value for m in ExecutionMode]}"
            )
        result = ClassificationResult(
            mode=mode,
            confidence=1.0,
            reasoning=f"Explicit override to {mode.value}",
            estimated_steps=1,
            requires_iteration=False,
            batch_size=None,
            source="override",
        )
        logger.info(
            "Classification override: mode=%s query=%.80s",
            result.mode.value,
            query,
        )
        return result

    # --- Empty / invalid query ---
    if not query or not query.strip():
        raise ClassificationError("Cannot classify an empty query")

    # --- Heuristic ---
    heuristic_result = _heuristic_classify(query, has_documents, doc_metadata)
    if heuristic_result is not None:
        logger.info(
            "Classification (heuristic): mode=%s confidence=%.2f query=%.80s reason=%s",
            heuristic_result.mode.value,
            heuristic_result.confidence,
            query,
            heuristic_result.reasoning,
        )
        return heuristic_result

    # --- LLM fallback ---
    llm_result = await _llm_classify(query, has_documents, doc_metadata)
    if llm_result is None:
        raise ClassificationError(
            f"Both heuristic and LLM classifiers failed for query: {query[:100]!r}"
        )

    # --- Confidence check ---
    if llm_result.confidence < CONFIDENCE_THRESHOLD:
        raise ClassificationError(
            f"LLM classifier confidence {llm_result.confidence:.2f} is below "
            f"threshold {CONFIDENCE_THRESHOLD:.2f} for query: {query[:100]!r}. "
            f"Mode was {llm_result.mode.value}, reasoning: {llm_result.reasoning}"
        )

    logger.info(
        "Classification (llm): mode=%s confidence=%.2f query=%.80s reason=%s",
        llm_result.mode.value,
        llm_result.confidence,
        query,
        llm_result.reasoning,
    )
    return llm_result

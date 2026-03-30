"""DB query layer for client ID lookup.

Two independent queries against separate schemas:
  - galileo.fuzzy_client           — clean name list, similarity() scoring
  - galileo.high_priority_queue_client — bio-text labels, word_similarity() scoring

SET LOCAL is used inside a transaction so threshold changes are scoped to
the current query and do not leak to other queries on the same pooled
connection.
"""
from __future__ import annotations

import logging
import re

from app.db._pool import _acquire
from app.models.client_lookup import CandidateResult

logger = logging.getLogger(__name__)

# ── Honorific / suffix patterns stripped by normalize_name() ─────────────────
#
# Each token is matched as a whole word (preceded by start-of-string or
# whitespace) followed by an optional dot and optional trailing whitespace so
# that "Mr. John" and "Mr John" both reduce cleanly.

_HONORIFIC_RE = re.compile(
    r"""
    (?<![A-Za-z])           # not preceded by a letter (word boundary)
    (?:
      Mr    | Mrs   | Ms    | Miss  | Dr    | Prof  |
      Rev   | Sr    | Jr    | Esq   |
      II    | III   | IV    | V\b   |        # roman numerals (V needs \b)
      MD    | PhD   | DDS   | DVM   | JD    | CPA
    )
    \.?                     # optional trailing dot
    (?=\s|$)                # must be followed by whitespace or end-of-string
    \s*                     # consume any following whitespace
    """,
    re.VERBOSE | re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Strip honorifics and suffixes, collapse whitespace.

    Examples:
      "Mr. John Smith Jr." -> "John Smith"
      "Dr.  Jane  Doe  III" -> "Jane Doe"
      "  Alice   " -> "Alice"
    """
    cleaned = _HONORIFIC_RE.sub(" ", name)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


# ── fuzzy_client query ────────────────────────────────────────────────────────


async def search_fuzzy_client(
    name: str,
    company: str | None = None,  # noqa: ARG001 — reserved for future company boost
    limit: int = 10,
) -> list[CandidateResult]:
    """Search galileo.fuzzy_client using pg_trgm similarity().

    Uses SET LOCAL inside a transaction to scope the threshold to this
    connection acquire only, preventing leakage on pooled connections.

    The company parameter is accepted for API symmetry but the actual
    company-boost logic is deferred to the LLM layer (design.md Decision 3).
    Returns an empty list on any DB error so a partial failure does not
    abort the full resolve flow.
    """
    try:
        async with _acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SET LOCAL pg_trgm.similarity_threshold = 0.3"
                )
                rows = await conn.fetch(
                    """
                    SELECT
                        gwm_id,
                        name,
                        companies,
                        similarity(LOWER(name), LOWER($1)) AS score
                    FROM galileo.fuzzy_client
                    WHERE LOWER(name) % LOWER($1)
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    name,
                    limit,
                )
        return [
            CandidateResult(
                gwm_id=row["gwm_id"],
                name=row["name"],
                source="fuzzy_client",
                db_score=float(row["score"]),
                companies=row["companies"] if row["companies"] else None,
            )
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "search_fuzzy_client failed for name=%r: %s", name, exc
        )
        return []


# ── high_priority_queue_client query ─────────────────────────────────────────


async def search_queue_client(
    name: str,
    limit: int = 10,
) -> list[CandidateResult]:
    """Search galileo.high_priority_queue_client using pg_trgm word_similarity().

    word_similarity() measures how well the query appears as a contiguous
    substring within the label text, which suits the bio-text format of that
    table's label column.

    The galileo schema is not in the connection's search_path so the table
    reference must be fully qualified.  Permission errors are caught and
    returned as an empty list with a warning, as per the foundation agent's
    notes on galileo permission uncertainty.
    """
    try:
        async with _acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SET LOCAL pg_trgm.word_similarity_threshold = 0.3"
                )
                rows = await conn.fetch(
                    """
                    SELECT
                        entity_id,
                        label,
                        word_similarity(LOWER($1), LOWER(label)) AS score
                    FROM galileo.high_priority_queue_client
                    WHERE entity_id_type = 'Client'
                      AND LOWER(label) %> LOWER($1)
                    ORDER BY score DESC
                    LIMIT $2
                    """,
                    name,
                    limit,
                )
        return [
            CandidateResult(
                gwm_id=row["entity_id"],
                name=row["label"][:100],
                source="high_priority_queue_client",
                db_score=float(row["score"]),
                label_excerpt=row["label"][:200],
            )
            for row in rows
        ]
    except Exception as exc:
        logger.warning(
            "search_queue_client failed for name=%r: %s", name, exc
        )
        return []

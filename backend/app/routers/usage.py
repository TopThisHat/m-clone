"""
Usage dashboard endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import DatabaseNotConfigured, get_pool

router = APIRouter(prefix="/api/usage", tags=["usage"])

# Blended GPT-5.1 cost estimate (input + output average)
_COST_PER_TOKEN = 0.0000025


@router.get("/summary")
async def usage_summary():
    """Return aggregated usage statistics for the dashboard."""
    try:
        pool = await get_pool()
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="A database connection is required for this action. Please configure DATABASE_URL.")

    async with pool.acquire() as conn:
        total_sessions = await conn.fetchval("SELECT COUNT(*) FROM sessions")
        total_tokens = await conn.fetchval("SELECT COALESCE(SUM(usage_tokens), 0) FROM sessions") or 0

        sessions_by_day = await conn.fetch(
            """
            SELECT
                DATE(created_at) AS date,
                COUNT(*) AS count,
                COALESCE(SUM(usage_tokens), 0) AS tokens
            FROM sessions
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
            """
        )

        top_queries = await conn.fetch(
            """
            SELECT query, usage_tokens AS tokens
            FROM sessions
            ORDER BY usage_tokens DESC
            LIMIT 10
            """
        )

    return {
        "total_sessions": total_sessions,
        "total_tokens": int(total_tokens),
        "estimated_cost_usd": round(int(total_tokens) * _COST_PER_TOKEN, 4),
        "sessions_by_day": [
            {
                "date": str(r["date"]),
                "count": int(r["count"]),
                "tokens": int(r["tokens"]),
            }
            for r in sessions_by_day
        ],
        "top_queries": [
            {"query": r["query"], "tokens": int(r["tokens"])}
            for r in top_queries
        ],
    }

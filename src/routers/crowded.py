"""Multi-signal crowded trades scanner (crowdedness_score composite)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import crowded as qry

router = APIRouter()


@router.get("/api/ct/meta")
def ct_meta():
    """Metadata: latest scan date, ticker count, signal severity counts, last ingestion."""
    return qry.get_crowded_trades_meta()


@router.get("/api/ct/latest")
def ct_latest(
    limit: int = Query(100, ge=1, le=200, description="Max tickers to return"),
    signal: str | None = Query(None, pattern="^(HIGH|MEDIUM|NEUTRAL)$",
                               description="Filter by signal severity"),
):
    """Latest multi-signal crowded trades scan results.

    Aggregates 6 signal sources: short interest, put/call ratio, unusual
    options, IV percentile, momentum, and market correlation. Each ticker
    gets a 0–100 total score with HIGH/MEDIUM/NEUTRAL severity and
    bilateral/directional crowd classification.
    """
    return qry.get_crowded_trades_latest(limit=limit, signal=signal)

"""Economic calendar."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import econ as qry

router = APIRouter()


@router.get("/api/econ/events")
def econ_events(
    days_ahead: int = Query(30, ge=1, le=180, description="Lookahead window in days"),
    impact: str | None = Query(None, pattern="^(high|medium|low)$", description="Filter by impact level"),
    category: str | None = Query(None, description="Filter by category (e.g. 'FOMC', 'ECB', 'US Economics')"),
    limit: int = Query(200, ge=1, le=500, description="Max events to return"),
):
    """Upcoming high-impact economic calendar events (FOMC, US econ releases, ECB, BOE, BOJ)."""
    return {"events": qry.get_econ_events(
        days_ahead=days_ahead,
        impact=impact,
        category=category,
        limit=limit,
    )}


@router.get("/api/econ/meta")
def econ_meta():
    """Metadata for the economic calendar tab: last refresh, categories, count."""
    return qry.get_econ_meta()

"""Earnings revision momentum."""
from __future__ import annotations

from fastapi import APIRouter

from ..queries import earnings as qry

router = APIRouter()


@router.get("/api/earnings-revisions")
def earnings_revision_momentum():
    """Earnings revision momentum across the watchlist universe."""
    return qry.get_earnings_revision_momentum()


@router.get("/api/earnings-revisions/meta")
def earnings_revision_meta():
    """Metadata for the earnings revision page."""
    return qry.get_earnings_revision_meta()


@router.get("/api/earnings-revisions/history/{ticker}")
def earnings_revision_history(ticker: str):
    """Historical momentum snapshots for a single ticker."""
    return qry.get_earnings_revision_history(ticker)

"""Factor exposure (style drift) + 13F crowded positions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..queries import factors as qry

router = APIRouter()


@router.get("/api/factors/meta")
def factor_meta():
    """Metadata for the Factor Exposure tab: latest quarter, coverage."""
    return qry.get_factor_meta()


@router.get("/api/factors/exposure")
def factor_exposure(quarter: str | None = Query(None, description="YYYY-MM-DD")):
    """Portfolio-value-weighted factor exposure (overall + per strategy).

    Three dimensions: Size (market cap), Value/Growth (book-to-market),
    Momentum (20-day ROC).  Each returns overall buckets and a per-strategy
    breakout.  Coverage is honest — only tickers with a `ticker_factors`
    row contribute; the rest of AUM is reported as Unclassified.
    """
    return qry.get_factor_exposure(quarter=quarter)


@router.get("/api/factors/tickers/{ticker}")
def factor_ticker(ticker: str):
    """Single-ticker factor classification + fund holder list."""
    r = qry.get_factor_ticker(ticker)
    if not r:
        raise HTTPException(404, f"No factor data for {ticker.upper()}")
    return r


@router.get("/api/factors/crowded")
def crowded_trades(
    limit: int = Query(25, ge=5, le=100, description="Max tickers to return"),
):
    """Most-crowded positions: most-fund holders + largest value +
    directional bias (net funds adding vs removing this quarter)."""
    return qry.get_crowded_trades(limit=limit)

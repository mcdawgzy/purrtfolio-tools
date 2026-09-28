"""Customizable stock screener."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import screener as qry

router = APIRouter()


@router.get("/api/screener/meta")
def screener_meta():
    """Screener metadata: available sectors, latest price date, ticker count."""
    return qry.get_screener_meta()


@router.get("/api/screener")
def screener(
    sector: str = Query("", description="GICS sector filter (empty = all)"),
    min_price: float = Query(0, ge=0, description="Minimum current price"),
    max_price: float = Query(0, ge=0, description="Maximum current price (0 = no cap)"),
    min_volume: int = Query(0, ge=0, description="Minimum daily volume"),
    min_market_cap: float = Query(0, ge=0, description="Minimum market cap in USD (0 = no floor)"),
    etf_only: bool = Query(False, description="Only ETFs"),
    stocks_only: bool = Query(False, description="Only stocks (excludes ETFs)"),
    sort_col: str = Query("market_cap", description="Sort column"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$", description="Sort direction"),
    limit: int = Query(100, ge=10, le=500, description="Max results"),
):
    """Screen the tickers universe by fundamental + price/volume criteria.

    Joins the latest price_history row per ticker to the tickers dimension.
    Market cap is computed as close × shares_outstanding. Returns pct_change
    (5-day price return) where available."""
    return qry.get_screener_results(
        sector=sector,
        min_price=min_price,
        max_price=max_price if max_price else None,
        min_volume=min_volume,
        min_market_cap=min_market_cap,
        etf_only=etf_only,
        stocks_only=stocks_only,
        sort_col=sort_col,
        sort_dir=sort_dir,
        limit=limit,
    )

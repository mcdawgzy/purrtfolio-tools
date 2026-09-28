"""Correlation matrix — scanner DB when populated, yfinance on-demand otherwise."""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import scanner_data as scanners
from ..scanner_data import compute_corr_on_demand, corr_db_ready, corr_pivots, mom_watchlist

router = APIRouter()

_WINDOW = "^(1_month|3_month|6_month|12_month)$"


@router.get("/api/correlation/meta")
def correlation_meta():
    """Metadata for the correlation matrix tab."""
    if scanners.SCANNERS_OK:
        return scanners.cm_db.get_meta()
    return {"latest_date": None, "total_rows": 0}


@router.get("/api/correlation/matrix")
def correlation_matrix(
    window: str = Query("3_month", pattern=_WINDOW),
    date_str: str | None = Query(None),
    tickers: str | None = Query(None, description="Comma-separated ticker list"),
    min_corr_abs: float = Query(0.0, ge=0, le=1),
):
    """Full correlation matrix for a window."""
    ticker_list = tickers.split(",") if tickers else None
    # Try DB first (cron-populated)
    if corr_db_ready():
        result = scanners.cm_db.get_corr_matrix(window=window, date_str=date_str, tickers=ticker_list,
                                                min_corr_abs=min_corr_abs)
        if result.get("matrix") or result.get("tickers"):
            return result
    # Fallback: on-demand computation (targets default to the momentum watchlist)
    targets = ticker_list or mom_watchlist()
    pivots = corr_pivots()
    corr_data = compute_corr_on_demand(targets, pivots, window)
    if not corr_data:
        return {"date": None, "window": window, "tickers": [], "pivots": [], "matrix": {}}
    return {
        "date": None,
        "window": window,
        "tickers": list(corr_data),
        "pivots": [p for p in pivots if any(p in row for row in corr_data.values())],
        "matrix": corr_data,
    }


@router.get("/api/correlation/ticker/{ticker}")
def correlation_ticker(
    ticker: str,
    window: str = Query("3_month", pattern=_WINDOW),
):
    """Correlations of *ticker* vs all pivot tickers."""
    if scanners.SCANNERS_OK:
        corr_db_ready()  # downloads the slim DB if it's empty
        result = scanners.cm_db.get_corr_for_ticker(ticker, window=window)
        if result:
            return result
    # Fallback: on-demand
    corr = compute_corr_on_demand([ticker.upper()], corr_pivots(), window)
    return corr.get(ticker.upper(), {})


@router.get("/api/correlation/pivot/{pivot}")
def correlation_pivot(
    pivot: str,
    window: str = Query("3_month", pattern=_WINDOW),
    limit: int = Query(50, ge=1, le=200),
    min_abs: float = Query(0.2, ge=0, le=1),
):
    """All tickers' correlation to a pivot ticker, sorted by abs value."""
    if scanners.SCANNERS_OK:
        corr_db_ready()  # downloads the slim DB if it's empty
        result = scanners.cm_db.get_corr_to_pivot(pivot, window=window, limit=limit, min_abs=min_abs)
        if result:
            return result
    # Fallback: on-demand
    corr = compute_corr_on_demand(mom_watchlist(), [pivot.upper()], window)
    # Same row shape as cm_db.get_corr_to_pivot so the frontend renders both
    rows = [
        {"ticker": tk, "name": None, "category": None, "corr": v}
        for tk, pdict in corr.items()
        for v in pdict.values()
        if abs(v) >= min_abs and tk != pivot.upper()
    ]
    rows.sort(key=lambda r: abs(r["corr"]), reverse=True)
    return rows[:limit]

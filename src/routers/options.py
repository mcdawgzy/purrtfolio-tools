"""Options-derived signals: put/call ratio, IV rank, unusual activity."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import options as qry

router = APIRouter()


# ---------------------------------------------------------------------------
# Put/Call Ratio (CBOE)
# ---------------------------------------------------------------------------
@router.get("/api/pcr/meta")
def pcr_meta():
    """Metadata: latest date, covered series, last ingestion."""
    return qry.get_pcr_meta()


@router.get("/api/pcr/latest")
def pcr_latest():
    """Latest daily put/call ratios for all series (TOTAL, INDEX, EQUITY, ETP, VIX, etc.)."""
    result = qry.get_pcr_latest()
    if not result["rows"]:
        return {
            "latest_date": None,
            "rows": [],
            "note": "No data yet — scanner ingests daily at 6 AM ET",
        }
    return result


@router.get("/api/pcr/history/{series}")
def pcr_history(
    series: str,
    days: int = Query(60, ge=5, le=365, description="Number of days to return"),
):
    """Historical put/call ratio for a single series (oldest → newest)."""
    return qry.get_pcr_history(series, days=days)


@router.get("/api/pcr/signals")
def pcr_signals():
    """Extreme readings: where total/index/equity PCR is elevated or suppressed."""
    return qry.get_pcr_signals()


# ---------------------------------------------------------------------------
# IV Rank & IV Percentile
# ---------------------------------------------------------------------------
@router.get("/api/iv/meta")
def iv_meta():
    """Metadata: latest date, ticker count, signal counts."""
    return qry.get_iv_meta()


@router.get("/api/iv/latest")
def iv_latest():
    """Latest IV Rank data for all tickers, sorted by IV Rank descending."""
    return qry.get_iv_latest()


@router.get("/api/iv/history/{ticker}")
def iv_history(
    ticker: str,
    days: int = Query(300, ge=10, le=500),
):
    """Historical IV + IV Rank for a single ticker (oldest → newest)."""
    return qry.get_iv_history(ticker, days=days)


# ---------------------------------------------------------------------------
# Unusual Activity / Dark Pool
# ---------------------------------------------------------------------------
@router.get("/api/ua/meta")
def ua_meta():
    """Metadata: latest date, ticker count, signal counts."""
    return qry.get_ua_meta()


@router.get("/api/ua/latest")
def ua_latest():
    """Latest unusual activity for all tickers, sorted by severity."""
    return qry.get_ua_latest()


@router.get("/api/ua/signals")
def ua_signals():
    """HIGH / EXTREME signals only."""
    return qry.get_ua_signals()


@router.get("/api/ua/history/{ticker}")
def ua_history(
    ticker: str,
    limit: int = Query(100, ge=10, le=200),
):
    """Recent unusual activity for a single ticker (oldest → newest)."""
    return qry.get_ua_history(ticker, limit=limit)

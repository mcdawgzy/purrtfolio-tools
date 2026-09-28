"""FINRA short interest."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..queries import short_interest as qry

router = APIRouter()


@router.get("/api/si/meta")
def si_meta():
    return qry.get_si_meta()


@router.get("/api/si/latest")
def si_latest(
    min_short: int | None = Query(None, ge=0, description="Min short interest position"),
    limit: int = Query(100, ge=1, le=500),
):
    return {"rows": qry.get_si_latest(min_short=min_short or 1_000_000, limit=limit)}


@router.get("/api/si/tickers/{symbol}")
def si_ticker(symbol: str):
    r = qry.get_si_ticker(symbol)
    if not r:
        raise HTTPException(404, f"No short interest data for {symbol.upper()}")
    return r


@router.get("/api/si/signals")
def si_signals():
    return qry.get_si_signals()


@router.get("/api/si/search")
def si_search(q: str = Query(..., min_length=1)):
    return {"results": qry.search_si_tickers(q)}

"""13F funds, holdings, changes, cross-fund ticker view, consensus, sectors."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..queries import funds as qry

router = APIRouter()


def _validate_quarter(quarter: str | None) -> None:
    """Validate YYYY-MM-DD quarter format. Raise 422 on bad input."""
    if quarter is None:
        return
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", quarter):
        raise HTTPException(422, f"quarter must be YYYY-MM-DD, got {quarter!r}")
    try:
        date.fromisoformat(quarter)
    except ValueError:
        raise HTTPException(422, f"quarter is not a valid date: {quarter!r}")


@router.get("/api/funds")
def funds():
    return {"funds": qry.list_funds()}


@router.get("/api/funds/{cik}")
def fund_detail(cik: str):
    f = qry.get_fund(cik)
    if not f:
        raise HTTPException(404, f"Fund {cik} not found")
    return f


@router.get("/api/funds/{cik}/holdings")
def fund_holdings(
    cik: str,
    quarter: str | None = Query(None, description="YYYY-MM-DD; defaults to latest"),
    sort_by: str = Query("value", pattern="^(value|shares|ticker|cusip)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    min_value: int | None = Query(None, ge=0, description="Min position USD"),
    ticker: str | None = Query(None, description="Filter by ticker/issuer substring"),
):
    _validate_quarter(quarter)
    return qry.get_fund_holdings(
        cik,
        quarter=quarter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        min_value=min_value,
        ticker_filter=ticker,
    )


@router.get("/api/funds/{cik}/changes")
def fund_changes(
    cik: str,
    quarter: str | None = Query(None),
    status: str | None = Query(
        None, pattern="^(NEW|CLOSED|INCREASED|DECREASED|UNCHANGED)$"
    ),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    min_abs_value: int | None = Query(None, ge=0),
):
    _validate_quarter(quarter)
    return qry.get_fund_changes(
        cik,
        quarter=quarter,
        status=status,
        limit=limit,
        offset=offset,
        min_abs_value=min_abs_value,
    )


@router.get("/api/tickers/{ticker}")
def ticker_detail(ticker: str):
    return qry.get_ticker_holders(ticker)


@router.get("/api/consensus")
def consensus(
    quarter: str | None = Query(None),
    min_funds: int = Query(2, ge=1, le=27),
    limit: int = Query(50, ge=1, le=500),
):
    return qry.get_consensus(quarter=quarter, min_funds=min_funds, limit=limit)


@router.get("/api/sectors")
def sectors():
    return {"sectors": qry.list_sectors(), "periods": qry.get_sector_periods()}

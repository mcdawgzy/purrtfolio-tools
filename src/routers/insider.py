"""Form 4 insider trading."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..queries import insider as qry

router = APIRouter()


def _transform_latest_row(row: dict) -> dict:
    """Map raw DB columns to frontend-friendly field names."""
    trans_cd = row.get("trans_acquired_disp_cd", "")
    is_buy = trans_cd == "A"
    return {
        "accession_number": row.get("accession_number"),
        "ticker": row.get("ticker"),
        "company_name": row.get("issuername"),
        "trade_date": row.get("trans_date"),
        "filing_date": row.get("filing_date"),
        "insider_cik": row.get("rptownercik"),
        "insider_name": row.get("rptownername"),
        "relationship": row.get("rptowner_relationship"),
        "title": row.get("rptowner_title"),
        "transaction_type": row.get("trans_code"),  # P, S, M, A, etc.
        "quantity": row.get("trans_shares"),
        "price": row.get("trans_pricepershare"),
        "value": row.get("transaction_value_usd"),
        "ownership_type": row.get("direct_indirect_ownership"),
        "nature_of_ownership": row.get("nature_of_ownership"),
        "shares_post": row.get("shrs_ownfollowingtrans"),
        "value_post": row.get("val_ownfollowingtrans"),
        "is_buy": is_buy,
    }


@router.get("/api/insider/meta")
def insider_meta():
    """Metadata for the insider trading tab: latest filing, coverage stats, quarters."""
    return qry.get_insider_meta()


@router.get("/api/insider/latest")
def insider_latest(
    ticker: str | None = Query(None, description="Filter to a single ticker"),
    min_value: int | None = Query(None, ge=0, description="Min transaction value USD"),
    limit: int = Query(100, ge=1, le=500),
):
    """Latest insider transactions (Form 4), optionally filtered by ticker."""
    rows = qry.get_insider_latest(
        ticker=ticker,
        limit=limit,
        min_value=min_value,
    )
    return {"rows": [_transform_latest_row(r) for r in rows], "total": len(rows)}


@router.get("/api/insider/tickers/{ticker}")
def insider_ticker_detail(ticker: str):
    """Full insider trading history for a single ticker."""
    r = qry.get_insider_ticker(ticker)
    if not r:
        raise HTTPException(404, f"No insider data for {ticker.upper()}")
    # Transform transactions to frontend-friendly names
    if "transactions" in r:
        r["trades"] = [_transform_latest_row(t) for t in r["transactions"]]
    return r


@router.get("/api/insider/signals")
def insider_signals(
    limit: int = Query(100, ge=1, le=500),
):
    """Signal sets: top buys, top sells, officer trades."""
    raw = qry.get_insider_signals(limit=limit)
    # Transform signal rows and rename keys to match frontend expectations
    raw["officer_buys"] = [_transform_latest_row(r) for r in raw.get("officer_trades", [])]
    raw["top_buys"] = [_transform_latest_row(r) for r in raw.get("top_buys", [])]
    raw["top_sells"] = [_transform_latest_row(r) for r in raw.get("top_sells", [])]
    raw["recent_activity"] = raw["top_buys"][:10] + raw["top_sells"][:10]
    return raw


@router.get("/api/insider/search")
def insider_search(q: str = Query(..., min_length=1)):
    """Search insider trading tickers."""
    return {"results": qry.search_insider_tickers(q)}

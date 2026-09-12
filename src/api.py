"""
13F Web Dashboard — FastAPI backend.

Read-only API over purrtfolio.db. Single-page drill-down frontend served
from /static/. CORS open for local dev + GitHub Pages (configurable).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("13f-web")

ROOT = Path(__file__).parent.parent
STATIC_DIR = ROOT / "static"

app = FastAPI(
    title="Trading Tools by Purrtfolio",
    description="Free institutional-ownership + macro market dashboard (SEC EDGAR + FINRA data)",
    version="0.1.0",
)

# CORS: open by default for development; tighten via env vars in production
_allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exc_handler(_, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": exc.status_code},
    )


@app.exception_handler(FileNotFoundError)
async def db_missing_handler(_, exc: FileNotFoundError):
    return JSONResponse(
        status_code=503,
        content={
            "error": "Database unavailable",
            "detail": str(exc),
            "status": 503,
        },
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return db.health()


@app.get("/api/meta")
def meta():
    return db.get_meta()


@app.get("/api/funds")
def funds():
    return {"funds": db.list_funds()}


@app.get("/api/funds/{cik}")
def fund_detail(cik: str):
    f = db.get_fund(cik)
    if not f:
        raise HTTPException(404, f"Fund {cik} not found")
    return f


@app.get("/api/funds/{cik}/holdings")
def fund_holdings(
    cik: str,
    quarter: str | None = Query(None, description="YYYY-MM-DD; defaults to latest"),
    sort_by: str = Query("value", pattern="^(value|shares|ticker|change|cusip)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    min_value: int | None = Query(None, ge=0, description="Min position USD"),
    ticker: str | None = Query(None, description="Filter by ticker/issuer substring"),
):
    _validate_quarter(quarter)
    return db.get_fund_holdings(
        cik,
        quarter=quarter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        min_value=min_value,
        ticker_filter=ticker,
    )


@app.get("/api/funds/{cik}/changes")
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
    return db.get_fund_changes(
        cik,
        quarter=quarter,
        status=status,
        limit=limit,
        offset=offset,
        min_abs_value=min_abs_value,
    )


def _validate_quarter(q: str | None) -> None:
    """Validate YYYY-MM-DD quarter format. Raise 422 on bad input."""
    if q is None:
        return
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", q):
        raise HTTPException(422, f"quarter must be YYYY-MM-DD, got {q!r}")
    try:
        from datetime import date
        date.fromisoformat(q)
    except ValueError:
        raise HTTPException(422, f"quarter is not a valid date: {q!r}")


@app.get("/api/tickers/{ticker}")
def ticker_detail(ticker: str):
    return db.get_ticker_holders(ticker)


@app.get("/api/consensus")
def consensus(
    quarter: str | None = Query(None),
    min_funds: int = Query(2, ge=1, le=27),
    limit: int = Query(50, ge=1, le=500),
):
    return db.get_consensus(quarter=quarter, min_funds=min_funds, limit=limit)


@app.get("/api/sectors")
def sectors():
    return {"sectors": db.list_sectors(), "periods": db.get_sector_periods()}


@app.get("/api/si/meta")
def si_meta():
    return db.get_si_meta()


@app.get("/api/si/latest")
def si_latest(
    min_short: int | None = Query(None, ge=0, description="Min short interest position"),
    limit: int = Query(100, ge=1, le=500),
):
    return {"rows": db.get_si_latest(min_short=min_short or 1_000_000, limit=limit)}


@app.get("/api/si/tickers/{symbol}")
def si_ticker(symbol: str):
    r = db.get_si_ticker(symbol)
    if not r:
        raise HTTPException(404, f"No short interest data for {symbol.upper()}")
    return r


@app.get("/api/si/signals")
def si_signals():
    return db.get_si_signals()


@app.get("/api/si/search")
def si_search(q: str = Query(..., min_length=1)):
    return {"results": db.search_si_tickers(q)}


# ---------------------------------------------------------------------------
# Form 4 Insider Trading
# ---------------------------------------------------------------------------
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


@app.get("/api/insider/meta")
def insider_meta():
    """Metadata for the insider trading tab: latest filing, coverage stats, quarters."""
    return db.get_insider_meta()


@app.get("/api/insider/latest")
def insider_latest(
    ticker: str | None = Query(None, description="Filter to a single ticker"),
    min_value: int | None = Query(None, ge=0, description="Min transaction value USD"),
    limit: int = Query(100, ge=1, le=500),
):
    """Latest insider transactions (Form 4), optionally filtered by ticker."""
    rows = db.get_insider_latest(
        ticker=ticker,
        limit=limit,
        min_value=min_value,
    )
    return {"rows": [_transform_latest_row(r) for r in rows], "total": len(rows)}


@app.get("/api/insider/tickers/{ticker}")
def insider_ticker_detail(ticker: str):
    """Full insider trading history for a single ticker."""
    r = db.get_insider_ticker(ticker)
    if not r:
        raise HTTPException(404, f"No insider data for {ticker.upper()}")
    # Transform transactions to frontend-friendly names
    if "transactions" in r:
        r["trades"] = [_transform_latest_row(t) for t in r["transactions"]]
    return r


@app.get("/api/insider/signals")
def insider_signals(
    limit: int = Query(100, ge=1, le=500),
):
    """Signal sets: top buys, top sells, officer trades."""
    raw = db.get_insider_signals(limit=limit)
    # Transform signal rows and rename keys to match frontend expectations
    raw["officer_buys"] = [_transform_latest_row(r) for r in raw.get("officer_trades", [])]
    raw["top_buys"] = [_transform_latest_row(r) for r in raw.get("top_buys", [])]
    raw["top_sells"] = [_transform_latest_row(r) for r in raw.get("top_sells", [])]
    raw["recent_activity"] = raw["top_buys"][:10] + raw["top_sells"][:10]
    return raw


@app.get("/api/insider/search")
def insider_search(q: str = Query(..., min_length=1)):
    """Search insider trading tickers."""
    results = db.search_insider_tickers(q)
    return {"results": results}


# ---------------------------------------------------------------------------
# Economic Calendar
# ---------------------------------------------------------------------------
@app.get("/api/econ/events")
def econ_events(
    days_ahead: int = Query(30, ge=1, le=180, description="Lookahead window in days"),
    impact: str | None = Query(None, pattern="^(high|medium|low)$", description="Filter by impact level"),
    category: str | None = Query(None, description="Filter by category (e.g. 'FOMC', 'ECB', 'US Economics')"),
    limit: int = Query(200, ge=1, le=500, description="Max events to return"),
):
    """Upcoming high-impact economic calendar events (FOMC, US econ releases, ECB, BOE, BOJ)."""
    return {"events": db.get_econ_events(
        days_ahead=days_ahead,
        impact=impact,
        category=category,
        limit=limit,
    )}


@app.get("/api/econ/meta")
def econ_meta():
    """Metadata for the economic calendar tab: last refresh, categories, count."""
    return db.get_econ_meta()


# ---------------------------------------------------------------------------
# Market Snapshot
# ---------------------------------------------------------------------------
@app.get("/api/snapshot/latest")
def snapshot_latest():
    """Latest macro market snapshot (PNG + top-3 mover narratives).

    Returns metadata + the PNG filename so the frontend can render the image
    from the static-mounted snapshots directory.
    """
    return db.get_latest_snapshot() or {
        "date_str": None,
        "png_filename": None,
        "caption": None,
        "top_movers": [],
        "timestamp": None,
    }


@app.get("/api/snapshot/{date_str}")
def snapshot_detail(date_str: str):
    """Specific snapshot by date (YYYYMMDD)."""
    return db.get_snapshot_by_date(date_str) or {
        "date_str": date_str,
        "png_filename": None,
        "caption": None,
        "top_movers": [],
        "timestamp": None,
    }


# ---------------------------------------------------------------------------
# Frontend (single page, served at /)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>Trading Tools by Purrtfolio</h1><p>Frontend not built yet. See <code>static/index.html</code>.</p>",
            status_code=200,
        )
    return FileResponse(idx)


# Serve static assets (CSS, JS) — mounted at /static/ for API compatibility
# and at / for GitHub Pages-style relative URLs (./app.js, ./styles.css)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    # Root-level static mount for relative paths (./app.js etc.)
    # Placed after /static to avoid shadowing any API routes
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static_root")

# Serve macro market snapshot PNGs
SNAPSHOT_OUT = db.get_snapshot_dir()
if SNAPSHOT_OUT.exists():
    app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOT_OUT)), name="snapshots")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
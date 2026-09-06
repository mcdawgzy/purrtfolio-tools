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
    title="13F Tracker",
    description="Free 13F institutional ownership dashboard (SEC EDGAR data)",
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
    return {"sectors": db.list_sectors()}


# ---------------------------------------------------------------------------
# Frontend (single page, served at /)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>13F Tracker</h1><p>Frontend not built yet. See <code>static/index.html</code>.</p>",
            status_code=200,
        )
    return FileResponse(idx)


# Serve static assets (CSS, JS) — must be last so it doesn't shadow API routes
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
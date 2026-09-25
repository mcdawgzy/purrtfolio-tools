"""
13F Web Dashboard — FastAPI backend.

Read-only API over purrtfolio.db. Single-page drill-down frontend served
from /static/. CORS open for local dev + GitHub Pages (configurable).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import time as _time
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("13f-web")

# Server-side cache for /api/meta (changes only on quarterly ingestion)
_meta_cache: dict | None = None
_meta_cache_time: float = 0.0
_META_CACHE_TTL = 300  # 5 minutes

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


@app.on_event("startup")
async def _ensure_db():
    """Ensure the slim momentum DB is ready on startup.

    On Render free tier, each cold-start runs this once. We download the
    slim momentum DB (price_history + corr_matrices, ~0.3MB compressed)
    from the GitHub Release. This is fast (<5s) and doesn't block the
    cold-start window.

    Note: yfinance on-demand fallback is NOT used on Render — data comes
    from the cron-populated DB which is refreshed daily.
    """
    _slim_db_path = os.environ.get("MOMENTUM_DB", "/opt/render/momentum_data.db")
    _slim_db = Path(_slim_db_path)
    _slim_gz = Path(str(_slim_db) + ".gz")
    if not _slim_db.exists() or _slim_db.stat().st_size < 100_000:
        log.info("Downloading slim momentum DB...")
        _url = "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-26/momentum_data.db.gz"
        try:
            db._download_with_redirect(_url, str(_slim_gz))
            import gzip, shutil
            with gzip.open(str(_slim_gz), "rb") as f_in, open(str(_slim_db), "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.remove(str(_slim_gz))
            log.info(f"Slim momentum DB ready ({_slim_db.stat().st_size / 1e6:.1f}MB)")
        except Exception as e:
            log.error(f"Slim momentum DB download failed: {e}")


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
    """Site metadata (counts, quarters, last update). Cached for 5 min since
    this only changes on quarterly ingestion runs."""
    global _meta_cache, _meta_cache_time
    now = _time.time()
    if _meta_cache is not None and (now - _meta_cache_time) < _META_CACHE_TTL:
        return _meta_cache
    result = db.get_meta()
    _meta_cache = result
    _meta_cache_time = now
    return result


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
# Put/Call Ratio (CBOE)
# ---------------------------------------------------------------------------
@app.get("/api/pcr/meta")
def pcr_meta():
    """Metadata: latest date, covered series, last ingestion."""
    return db.get_pcr_meta()


@app.get("/api/pcr/latest")
def pcr_latest():
    """Latest daily put/call ratios for all series (TOTAL, INDEX, EQUITY, ETP, VIX, etc.)."""
    result = db.get_pcr_latest()
    if not result["rows"]:
        return {
            "latest_date": None,
            "rows": [],
            "note": "No data yet — scanner ingests daily at 6 AM ET",
        }
    return result


@app.get("/api/pcr/history/{series}")
def pcr_history(
    series: str,
    days: int = Query(60, ge=5, le=365, description="Number of days to return"),
):
    """Historical put/call ratio for a single series (oldest → newest)."""
    return db.get_pcr_history(series, days=days)


@app.get("/api/pcr/signals")
def pcr_signals():
    """Extreme readings: where total/index/equity PCR is elevated or suppressed."""
    return db.get_pcr_signals()


# ---------------------------------------------------------------------------
# IV Rank & IV Percentile
# ---------------------------------------------------------------------------
@app.get("/api/iv/meta")
def iv_meta():
    """Metadata: latest date, ticker count, signal counts."""
    return db.get_iv_meta()


@app.get("/api/iv/latest")
def iv_latest():
    """Latest IV Rank data for all tickers, sorted by IV Rank descending."""
    return db.get_iv_latest()


@app.get("/api/iv/history/{ticker}")
def iv_history(
    ticker: str,
    days: int = Query(300, ge=10, le=500),
):
    """Historical IV + IV Rank for a single ticker (oldest → newest)."""
    return db.get_iv_history(ticker, days=days)


# ---------------------------------------------------------------------------
# Unusual Activity / Dark Pool
# ---------------------------------------------------------------------------
@app.get("/api/ua/meta")
def ua_meta():
    """Metadata: latest date, ticker count, signal counts."""
    return db.get_ua_meta()

@app.get("/api/ua/latest")
def ua_latest():
    """Latest unusual activity for all tickers, sorted by severity."""
    return db.get_ua_latest()

@app.get("/api/ua/signals")
def ua_signals():
    """HIGH / EXTREME signals only."""
    return db.get_ua_signals()

@app.get("/api/ua/history/{ticker}")
def ua_history(
    ticker: str,
    limit: int = Query(100, ge=10, le=200),
):
    """Recent unusual activity for a single ticker (oldest → newest)."""
    return db.get_ua_history(ticker, limit=limit)


# ---------------------------------------------------------------------------
# Customizable Stock Screener
# ---------------------------------------------------------------------------
@app.get("/api/screener/meta")
def screener_meta():
    """Screener metadata: available sectors, latest price date, ticker count."""
    return db.get_screener_meta()


@app.get("/api/screener")
def screener(
    sector: str = Query("", description="GICS sector filter (empty = all)"),
    min_price: float = Query(0, ge=0, description="Minimum current price"),
    max_price: float = Query(0, ge=0, description="Maximum current price (0 = no cap)"),
    min_volume: int = Query(0, ge=0, description="Minimum daily volume"),
    min_market_cap: float = Query(0, ge=0, description="Minimum market cap in USD (0 = no floor)"),
    etf_only: bool = Query(False, description="Only ETFs"),
    stocks_only: bool = Query(False, description="Only stocks (excludes ETFs)"),
    sort_col: str = Query("market_cap", description="Sort column"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$", description="Sort direction"),
    limit: int = Query(100, ge=10, le=500, description="Max results"),
):
    """Screen the tickers universe by fundamental + price/volume criteria.

    Joins the latest price_history row per ticker to the tickers dimension.
    Market cap is computed as close × shares_outstanding. Returns pct_change
    (5-day price return) where available."""
    return db.get_screener_results(
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


@app.get("/api/quotes")
def trader_quotes(
    category: str = Query("", description="Category filter (empty = all)"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
):
    """Famous trader quotes. Optionally filter by category."""
    return db.get_trader_quotes(category=category, limit=limit)


@app.get("/api/quotes/meta")
def trader_quote_meta():
    """Available quote categories."""
    return {"categories": db.get_trader_quote_categories()}


@app.get("/api/quotes/random")
def random_quote():
    """A single random trader quote."""
    return db.get_random_trader_quote()


@app.get("/api/earnings-revisions")
def earnings_revision_momentum():
    """Earnings revision momentum across the watchlist universe."""
    return db.get_earnings_revision_momentum()


@app.get("/api/earnings-revisions/meta")
def earnings_revision_meta():
    """Metadata for the earnings revision page."""
    return db.get_earnings_revision_meta()


@app.get("/api/earnings-revisions/history/{ticker}")
def earnings_revision_history(ticker: str):
    """Historical momentum snapshots for a single ticker."""
    return db.get_earnings_revision_history(ticker)


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
# News Sentiment
# ---------------------------------------------------------------------------
@app.get("/api/news/meta")
def news_meta():
    """Metadata: latest date, sources, headline count, signal counts, ingestion log."""
    return db.get_news_meta()


@app.get("/api/news/headlines")
def news_headlines(limit: int = Query(100, ge=1, le=500, description="Max headlines to return")):
    """Latest headlines with sentiment scores (newest first)."""
    rows = db.get_news_headlines(limit=limit)
    if not rows:
        return {"latest_date": None, "headlines": [],
                "note": "No data yet — scanner ingests daily at 6 AM ET"}
    latest = rows[0].get("retrieved_at") or rows[0].get("published_at")
    if latest:
        with db.db_conn() as c:
            latest = c.execute("SELECT date(datetime(?, 'localtime'))", (latest,)).fetchone()[0]
    return {"latest_date": latest, "headlines": rows}


@app.get("/api/news/tickers/{ticker}")
def news_ticker(ticker: str):
    """News sentiment detail for a single ticker: historical aggregates + headlines."""
    return db.get_news_ticker(ticker) or {
        "ticker": ticker.upper(), "history": [], "headlines": [],
        "note": "No news sentiment data for this ticker yet",
    }


@app.get("/api/news/signals")
def news_signals():
    """Current bullish / bearish ticker signals from aggregated sentiment."""
    return db.get_news_signals()


# ---------------------------------------------------------------------------
# Price Momentum Scanner — on-demand via yfinance (DB cached if writable)
# ---------------------------------------------------------------------------
import sys as _sys, os as _os
_scanners = str(STATIC_DIR.parent / "scanners")
if _scanners not in _sys.path:
    _sys.path.insert(0, _scanners)

try:
    from price_momentum import db as pm_db
    from correlation_matrix import db as cm_db
    _SCANNERS_OK = True
except Exception as e:
    log.warning(f"Scanner modules not importable in API: {e}")
    pm_db, cm_db, _SCANNERS_OK = None, None, False

# yfinance is installed via buildCommand — used for on-demand fallback
try:
    import yfinance as _yf
    import pandas as _pd
    _YF_OK = True
except Exception:
    _YF_OK = False
    _pd = None
# yfinance is installed via buildCommand — used for on-demand fallback
try:
    import yfinance as _yf
    import pandas as _pd
    _YF_OK = True
except Exception:
    _YF_OK = False


def _mom_watchlist():
    """Return the curated momentum watchlist tickers.

    Order of preference:
      1. DB-stored watchlist (from price_momentum DB module)
      2. Hardcoded curated list (always available, ~54 tickers)
    """
    if _SCANNERS_OK:
        tickers = pm_db.get_watchlist_tickers()
        if tickers:
            return tickers
    # Hardcoded curated list — mirrors scanners/price_momentum/config.py
    return [
        "^GSPC", "^NDX", "^DJI", "^RUT",
        "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
        "AVGO", "ASML", "AMD", "INTC", "CRM", "ADBE", "NFLX", "ORCL",
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW",
        "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY",
        "XOM", "CVX", "COP", "EOG", "SLB", "OXY",
        "WMT", "HD", "PG", "KO", "PEP", "COST", "NKE", "MCD",
        "^N225", "^GDAXI", "^FTSE", "^STOXX", "^HSI",
        "DX-Y.NYB", "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X",
        "^IRX", "^FVX", "^TNX", "^TYX",
        "GC=F", "SI=F", "CL=F", "BZ=F", "HG=F",
        "HYG", "LQD", "TIP", "^VIX",
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO",
        "BTC-USD", "ETH-USD",
    ]


def _fetch_ohlcv(tickers: list[str], days: int = 25) -> dict:
    """Fetch recent daily OHLCV for a list of tickers via yfinance.

    Downloads in batches of 20 to avoid yfinance timeouts with large lists.
    """
    if not _YF_OK or not tickers:
        return {}
    result: dict[str, dict] = {}
    batch_size = 20
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            period = f"{max(days + 5, 30)}d"
            df = _yf.download(
                tickers=" ".join(batch),
                period=period,
                interval="1d",
                group_actions=False,
                auto_adjust=False,
                progress=False,
            )
            if df.empty:
                continue
            cols = df.columns
            if isinstance(cols, _pd.MultiIndex):
                for ticker in batch:
                    if ticker not in cols.get_level_values(1):
                        continue
                    sub = df[ticker].dropna(how="all")
                    if sub.empty:
                        continue
                    series = {}
                    for field in ("Open", "High", "Low", "Close", "Volume"):
                        if field in sub.columns:
                            s = sub[field].dropna()
                            series[field] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
                    result[ticker] = series
            else:
                # Single-column DataFrame (single ticker in batch)
                for field in ("Open", "High", "Low", "Close", "Volume"):
                    if field in df.columns:
                        s = df[field].dropna()
                        result.setdefault("_single", {})[field] = {
                            d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()
                        }
        except Exception as e:
            log.warning(f"yfinance batch fetch failed for {batch}: {e}")
            continue
    return result


def _ensure_momentum_db():
    """Lazily download the slim momentum DB if it's missing or stale.

    Called from endpoints when bar_count() returns 0 (DB not yet downloaded).
    Downloads the 0.3MB compressed DB from GitHub Release — fast enough
    for a single cold-start request.
    """
    _slim_db_path = os.environ.get("MOMENTUM_DB")
    if not _slim_db_path:
        _slim_db_path = "/opt/render/momentum_data.db"
    _slim_db = Path(_slim_db_path)
    if _slim_db.exists() and _slim_db.stat().st_size > 100_000:
        return  # Already present
    log.info("Momentum DB missing — downloading...")
    _url = "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-26/momentum_data.db.gz"
    _gz = Path(str(_slim_db_path) + ".gz")
    try:
        db._download_with_redirect(_url, str(_gz))
        import gzip, shutil
        _slim_db.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(str(_gz), "rb") as f_in, open(str(_slim_db), "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(str(_gz))
        log.info(f"Momentum DB downloaded ({_slim_db.stat().st_size / 1e6:.1f}MB)")
    except Exception as e:
        log.error(f"Momentum DB download failed: {e}")


# ── Price Momentum ──────────────────────────────────────────────

@app.get("/api/momentum/meta")
def momentum_meta():
    """Metadata for the momentum tab."""
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK:
        return pm_db.get_meta()
    return {"latest_signal_date": None, "bar_count": 0, "ticker_count": 0}


@app.get("/api/momentum/rankings")
def momentum_rankings(
    min_price: float = Query(5.0, description="Min SMA-20d price to filter micro-caps"),
    limit: int = Query(50, ge=1, le=200),
):
    """Top momentum movers by 20-day ROC."""
    # Ensure DB is downloaded
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    # Try DB first (cron-populated)
    if _SCANNERS_OK and pm_db.bar_count() > 0:
        return pm_db.get_momentum_rankings(min_price=min_price, limit=limit)
    # Fallback: on-demand fetch
    tickers = _mom_watchlist()
    data = _fetch_ohlcv(tickers, days=25)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        closes = sorted(fields.get("Close", {}).items())
        if len(closes) < 22:
            continue
        prices = [c[1] for c in closes]
        sma20 = sum(prices[-20:]) / 20
        if sma20 < min_price:
            continue
        roc20 = (prices[-1] / prices[-21] - 1) if len(prices) >= 21 else 0
        vol = fields.get("Volume", {})
        vol_vals = sorted(vol.values())[-10:]
        vol_ema10 = sum(vol_vals) / max(len(vol_vals), 1)
        rows.append({
            "ticker": tkr,
            "close": round(prices[-1], 2),
            "sma20": round(sma20, 2),
            "roc20": round(roc20 * 100, 2),
            "vol_vs_ema10": round(vol_vals[-1] / vol_ema10 * 100, 0) if vol_ema10 else 100,
            "signal": "strong_momentum" if roc20 > 0.1 else ("weak_momentum" if roc20 > 0 else "weak_momentum"),
        })
    rows.sort(key=lambda r: r["roc20"], reverse=True)
    return rows[:limit]


@app.get("/api/momentum/volume-spikes")
def momentum_volume_spikes(limit: int = Query(30, ge=1, le=100)):
    """Tickers with volume > 2x the 10-day volume EMA."""
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK and pm_db.bar_count() > 0:
        return pm_db.get_volume_spike_alerts(limit=limit)
    tickers = _mom_watchlist()
    data = _fetch_ohlcv(tickers, days=15)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        vol = fields.get("Volume", {})
        if len(vol) < 11:
            continue
        vol_vals = sorted(vol.values())
        vol_ema10 = sum(vol_vals[-10:]) / 10
        latest_vol = vol_vals[-1]
        if vol_ema10 > 0 and latest_vol / vol_ema10 > 2:
            rows.append({
                "ticker": tkr,
                "latest_volume": int(latest_vol),
                "volume_ratio": round(latest_vol / vol_ema10, 2),
            })
    rows.sort(key=lambda r: r["volume_ratio"], reverse=True)
    return rows[:limit]


@app.get("/api/momentum/consolidation")
def momentum_consolidation(limit: int = Query(30, ge=1, le=100)):
    """Tickers in consolidation (ATR < 3% of price, inside-day range)."""
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK and pm_db.bar_count() > 0:
        return pm_db.get_consolidation_scan(limit=limit)
    tickers = _mom_watchlist()
    data = _fetch_ohlcv(tickers, days=15)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        hi = fields.get("High", {})
        lo = fields.get("Low", {})
        cl = fields.get("Close", {})
        common_dates = sorted(set(hi.keys()) & set(lo.keys()) & set(cl.keys()))
        if len(common_dates) < 10:
            continue
        recent = common_dates[-10:]
        atr = sum((hi[d] - lo[d]) for d in recent) / 10
        prices = [cl[d] for d in recent]
        avg_price = sum(prices) / len(prices)
        if avg_price == 0:
            continue
        atr_pct = atr / avg_price * 100
        if atr_pct < 3:
            rows.append({
                "ticker": tkr,
                "atr_pct": round(atr_pct, 2),
                "price": round(prices[-1], 2),
                "range_10d_pct": round((max(prices) - min(prices)) / avg_price * 100, 2),
            })
    rows.sort(key=lambda r: r["range_10d_pct"])
    return rows[:limit]


@app.get("/api/momentum/earnings-gaps")
def momentum_earnings_gaps(limit: int = Query(30, ge=1, le=100)):
    """Detect overnight gaps (>1%) in recent price action."""
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK and pm_db.bar_count() > 0:
        return pm_db.get_earnings_gaps(limit=limit)
    tickers = _mom_watchlist()
    data = _fetch_ohlcv(tickers, days=10)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        opens = sorted(fields.get("Open", {}).items())
        closes = sorted(fields.get("Close", {}).items())
        # Match by date
        close_map = dict(closes)
        gaps = []
        for d, o in opens:
            if d in close_map and close_map[d] > 0:
                gap_pct = (o - close_map[d]) / close_map[d] * 100
                gaps.append({"date": d, "gap_pct": round(gap_pct, 2)})
        big_gaps = [g for g in gaps if abs(g["gap_pct"]) > 1]
        if big_gaps:
            rows.append({
                "ticker": tkr,
                "gap": big_gaps[-1],
            })
    rows.sort(key=lambda r: abs(r["gap"]["gap_pct"]), reverse=True)
    return rows[:limit]


@app.get("/api/momentum/tickers/{ticker}")
def momentum_ticker(ticker: str, limit: int = Query(60, ge=1, le=200)):
    """Daily OHLCV history for a single ticker."""
    if _SCANNERS_OK and pm_db.bar_count() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK and pm_db.bar_count() > 0:
        bars = pm_db.price_history_for_ticker(ticker, limit=limit)
        return {"ticker": ticker.upper(), "bars": bars}
    # Fallback: yfinance
    data = _fetch_ohlcv([ticker.upper()], days=limit)
    if not data:
        return {"ticker": ticker.upper(), "bars": []}
    fields = next(iter(data.values()))
    bars = sorted(fields.get("Close", {}).items(), reverse=True)[:limit]
    result = []
    for d, v in bars:
        result.append({
            "date": d,
            "open": fields.get("Open", {}).get(d, v),
            "high": fields.get("High", {}).get(d, v),
            "low": fields.get("Low", {}).get(d, v),
            "close": v,
            "volume": int(fields.get("Volume", {}).get(d, 0)),
        })
    return {"ticker": ticker.upper(), "bars": result}


@app.get("/api/momentum/search")
def momentum_search(q: str = Query(..., min_length=1)):
    """Search the momentum watchlist."""
    tickers = _mom_watchlist()
    ql = q.upper().lower()
    results = [{"ticker": t, "name": t} for t in tickers if ql in t.lower()]
    return {"results": results}


# ── Correlation Matrix ──────────────────────────────────────────

def _corr_watchlist():
    """Tickers to compute correlations for (same as momentum watchlist)."""
    return _mom_watchlist()


def _corr_pivots():
    """Pivot/asset-class tickers for correlation."""
    if _SCANNERS_OK:
        pivots = cm_db.get_pivot_tickers()
        if pivots:
            return pivots
    return ["^GSPC", "^NDX", "^RUT", "^TNX", "^IRX", "^VIX", "SPY", "QQQ"]


def _compute_corr_on_demand(
    target_tickers: list[str],
    pivots: list[str],
    window: str,
) -> dict:
    """Compute correlation of each target vs each pivot, on-demand via yfinance."""
    if not _YF_OK:
        return {}
    import pandas as _pd2
    day_map = {"1_month": 21, "3_month": 63, "6_month": 126, "12_month": 252}
    days = day_map.get(window, 63)
    all_tickers = list(dict.fromkeys(pivots + target_tickers))
    try:
        df = _yf.download(
            tickers=" ".join(all_tickers),
            period=f"{days + 10}d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        log.warning(f"yfinance corr fetch failed: {e}")
        return {}
    if df.empty:
        return {}
    cols = df.columns
    # Get close prices aligned by date
    if isinstance(cols, _pd2.MultiIndex):
        closes = {}
        for tk in all_tickers:
            if tk in cols.get_level_values(1):
                closes[tk] = df[tk]["Close"].dropna()
        price_df = _pd2.DataFrame(closes).dropna()
    else:
        price_df = df["Close"].dropna().to_frame("price")
        # Single ticker — can't compute matrix
        if len(all_tickers) == 1:
            return {}
    if price_df.shape[0] < days:
        price_df = price_df.tail(days)
    returns = price_df.pct_change().dropna()
    if returns.empty:
        return {}
    result: dict[str, dict] = {}
    for tk in target_tickers:
        if tk not in returns.columns:
            continue
        tk_ret = returns[tk]
        corr = {}
        for p in pivots:
            if p not in returns.columns:
                continue
            c = tk_ret.corr(returns[p])
            if c is not None and not (c != c):  # not NaN
                corr[p] = round(float(c), 4)
        if corr:
            result[tk] = corr
    return result


@app.get("/api/correlation/meta")
def correlation_meta():
    """Metadata for the correlation matrix tab."""
    if _SCANNERS_OK:
        return cm_db.get_meta()
    return {"latest_date": None, "total_rows": 0}


@app.get("/api/correlation/matrix")
def correlation_matrix(
    window: str = Query("3_month", pattern="^(1_month|3_month|6_month|12_month)$"),
    date_str: str | None = Query(None),
    tickers: str | None = Query(None, description="Comma-separated ticker list"),
    min_corr_abs: float = Query(0.0, ge=0, le=1),
):
    """Full correlation matrix for a window."""
    if _SCANNERS_OK and cm_db.total_rows() == 0:
        _ensure_momentum_db()
    ticker_list = tickers.split(",") if tickers else None
    # Try DB first (cron-populated)
    if _SCANNERS_OK and cm_db.total_rows() > 0:
        result = cm_db.get_corr_matrix(window=window, date_str=date_str, tickers=ticker_list,
                                     min_corr_abs=min_corr_abs)
        if result.get("matrix") or result.get("tickers"):
            return result
    # Fallback: on-demand computation
    targets = ticker_list or _corr_watchlist()
    pivots = _corr_pivots()
    corr_data = _compute_corr_on_demand(targets, pivots, window)
    if not corr_data:
        return {"date": None, "window": window, "tickers": [], "pivots": [], "matrix": {}}


@app.get("/api/correlation/ticker/{ticker}")
def correlation_ticker(
    ticker: str,
    window: str = Query("3_month", pattern="^(1_month|3_month|6_month|12_month)$"),
):
    """Correlations of *ticker* vs all pivot tickers."""
    if _SCANNERS_OK and cm_db.total_rows() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK:
        result = cm_db.get_corr_for_ticker(ticker, window=window)
        if result:
            return result
    # Fallback: on-demand
    pivots = _corr_pivots()
    corr = _compute_corr_on_demand([ticker.upper()], pivots, window)
    return corr.get(ticker.upper(), {})


@app.get("/api/correlation/pivot/{pivot}")
def correlation_pivot(
    pivot: str,
    window: str = Query("3_month", pattern="^(1_month|3_month|6_month|12_month)$"),
    limit: int = Query(50, ge=1, le=200),
    min_abs: float = Query(0.2, ge=0, le=1),
):
    """All tickers' correlation to a pivot ticker, sorted by abs value."""
    if _SCANNERS_OK and cm_db.total_rows() == 0:
        _ensure_momentum_db()
    if _SCANNERS_OK:
        result = cm_db.get_corr_to_pivot(pivot, window=window, limit=limit, min_abs=min_abs)
        if result:
            return result
    # Fallback: on-demand
    targets = _corr_watchlist()
    corr = _compute_corr_on_demand(targets, [pivot.upper()], window)
    rows = []
    for tk, pdict in corr.items():
        for p, v in pdict.items():
            if abs(v) >= min_abs:
                rows.append({"target": tk, "pivot": p, "correlation": v})
    rows.sort(key=lambda r: abs(r["correlation"]), reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------
# Factor Exposure (Style Drift) + Crowded Trades
# ---------------------------------------------------------------------------
@app.get("/api/factors/meta")
def factor_meta():
    """Metadata for the Factor Exposure tab: latest quarter, coverage."""
    return db.get_factor_meta()


@app.get("/api/factors/exposure")
def factor_exposure(quarter: str | None = Query(None, description="YYYY-MM-DD")):
    """Portfolio-value-weighted factor exposure (overall + per strategy).

    Three dimensions: Size (market cap), Value/Growth (book-to-market),
    Momentum (20-day ROC).  Each returns overall buckets and a per-strategy
    breakout.  Coverage is honest — only tickers with a `ticker_factors`
    row contribute; the rest of AUM is reported as Unclassified.
    """
    return db.get_factor_exposure(quarter=quarter)


@app.get("/api/factors/tickers/{ticker}")
def factor_ticker(ticker: str):
    """Single-ticker factor classification + fund holder list."""
    r = db.get_factor_ticker(ticker)
    if not r:
        raise HTTPException(404, f"No factor data for {ticker.upper()}")
    return r


@app.get("/api/factors/crowded")
def crowded_trades(
    limit: int = Query(25, ge=5, le=100, description="Max tickers to return"),
):
    """Most-crowded positions: most-fund holders + largest value +
    directional bias (net funds adding vs removing this quarter)."""
    return db.get_crowded_trades(limit=limit)


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
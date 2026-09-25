"""Database layer for Crowded Trades Scanner — Unified Schema (purrtfolio.db).

Tables created:
  crowded_trades       — daily per-ticker crowdedness snapshot
  ingestion_log_crowded — audit trail

The scanner also *reads* from all upstream scanner tables (short_interest,
put_call_latest, unusual_activity, iv_rank, price_momentum_signals,
corr_matrices, tickers) via read helpers in this module.
"""
import sqlite3
import json
import logging
from pathlib import Path
from contextlib import contextmanager
from datetime import date
from typing import Optional, List, Dict, Any

from .config import DB_PATH

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    """Write-capable connection (same pattern as short_interest_scanner.db)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_db_readonly():
    """Read-only connection (web API side)."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


SCHEMA_SQL = """
-- Daily per-ticker crowdedness snapshot
CREATE TABLE IF NOT EXISTS crowded_trades (
    ticker              TEXT     NOT NULL,
    date                DATE     NOT NULL,
    crowdedness_score   REAL,                  -- 0-100 composite
    short_crowd         REAL,                  -- 0-100, short-side component
    long_crowd          REAL,                  -- 0-100, long-side component
    iv_crowd            REAL,                  -- 0-100, volatility component
    options_crowd       REAL,                  -- 0-100, options-flow component
    momentum_crowd      REAL,                  -- 0-100, momentum component
    pcr_crowd           REAL,                  -- 0-100, PCR backdrop
    corr_crowd          REAL,                  -- 0-100, herding/correlation
    crowd_direction     TEXT,                 -- 'long' | 'short' | 'bilateral' | 'neutral'
    signal              TEXT,                 -- 'EXTREME' | 'HIGH' | 'MEDIUM' | 'NEUTRAL'
    signal_details      JSON,                 -- breakdown of contributing signals
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_ct_date    ON crowded_trades(date);
CREATE INDEX IF NOT EXISTS idx_ct_signal  ON crowded_trades(signal);
CREATE INDEX IF NOT EXISTS idx_ct_score   ON crowded_trades(crowdedness_score DESC);

-- Ingestion audit log
CREATE TABLE IF NOT EXISTS ingestion_log_crowded (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL,
    status          TEXT NOT NULL,         -- 'completed', 'no_data', 'error'
    tickers_scanned INTEGER DEFAULT 0,
    signals_found   INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP
);
"""


def init_db():
    """Create crowded_trades tables if they don't already exist."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("crowded_trades schema ready at %s", DB_PATH)


# ─── Read helpers for upstream source tables ──────────────────────────

def get_watchlist_tickers() -> List[Dict[str, Any]]:
    """All tickers in the curated Crowded Trades watchlist.

    Uses the SI scanner's ``ticker_watchlist.json`` (via config) to get
    the ~120 large/important tickers, then enriches with name/exchange/
    free_float_shares from the unified ``tickers`` table.
    """
    from .config import CURATED_TICKERS, TICKER_CATEGORY
    with get_db_readonly() as conn:
        placeholders = ", ".join("?" for _ in CURATED_TICKERS)
        rows = conn.execute(f"""
            SELECT ticker, COALESCE(name, ticker) as name,
                   category, exchange, free_float_shares
            FROM tickers
            WHERE ticker IN ({placeholders})
        """, CURATED_TICKERS).fetchall()
    # Build a lookup so we don't lose tickers missing from the DB
    db_map = {r["ticker"]: dict(r) for r in rows}
    results = []
    for t in CURATED_TICKERS:
        t_upper = t.upper()
        info = db_map.get(t_upper) or db_map.get(t)
        if info:
            # Ensure category is set from the watchlist if DB has NULL
            if info.get("category") is None:
                info["category"] = TICKER_CATEGORY.get(t_upper, "uncategorized")
            results.append(info)
        else:
            results.append({
                "ticker": t_upper,
                "name": t_upper,
                "category": TICKER_CATEGORY.get(t_upper, "uncategorized"),
                "exchange": None,
                "free_float_shares": None,
            })
    return results


def get_short_interest_meta() -> Dict[str, Dict]:
    """Latest short-interest metadata per ticker (from ticker_short_meta)."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT symbol, latest_settlement, latest_short, latest_dtc,
                   latest_change_pct, peak_short, peak_short_date, peak_dtc,
                   avg_short_12m
            FROM ticker_short_meta
            WHERE latest_short IS NOT NULL
        """).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def get_unusual_activity_latest() -> Dict[str, List[Dict]]:
    """Latest unusual-activity records grouped by ticker."""
    with get_db_readonly() as conn:
        latest = conn.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        if not latest:
            return {"_date": None, "data": {}}
        rows = conn.execute("""
            SELECT ticker, call_put, activity_type, severity_score,
                   notional_usd, volume, iv_pct, price, vol_ratio
            FROM unusual_activity
            WHERE date = ?
            ORDER BY severity_score DESC
        """, (latest,)).fetchall()
    by_ticker: Dict[str, List[Dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(dict(r))
    return {"_date": latest, "data": by_ticker}


def get_iv_rank_latest() -> Dict[str, Dict]:
    """Latest IV Rank data per ticker."""
    with get_db_readonly() as conn:
        latest = conn.execute("SELECT MAX(date) FROM iv_rank").fetchone()[0]
        if not latest:
            return {"_date": None, "data": {}}
        rows = conn.execute("""
            SELECT ticker, iv, iv_rank, iv_pctile, days_52w,
                   iv_min_52w, iv_max_52w, iv_mean_52w, iv_median_52w,
                   iv_std_52w, signal
            FROM iv_rank
            WHERE date = ? AND iv IS NOT NULL
        """, (latest,)).fetchall()
    return {"_date": latest, "data": {r["ticker"]: dict(r) for r in rows}}


def get_momentum_latest() -> Dict[str, Dict]:
    """Latest price-momentum signals per ticker."""
    with get_db_readonly() as conn:
        latest = conn.execute("SELECT MAX(date) FROM price_momentum_signals").fetchone()[0]
        if not latest:
            return {"_date": None, "data": {}}
        rows = conn.execute("""
            SELECT ticker, roc_10d, roc_20d, roc_50d, sma_20d,
                   volume_ratio, is_volume_spike, is_consolidating,
                   gapped_open, gap_pct
            FROM price_momentum_signals
            WHERE date = ?
        """, (latest,)).fetchall()
    return {"_date": latest, "data": {r["ticker"]: dict(r) for r in rows}}


def get_put_call_latest() -> Dict[str, Dict]:
    """Latest put/call ratio data by series."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT series, date, ratio, call_volume, put_volume,
                   total_volume, call_oi, put_oi, total_oi,
                   ma5, ma20, ma50, z_score, signal
            FROM put_call_latest
        """).fetchall()
    return {r["series"]: dict(r) for r in rows}


def get_correlation_latest() -> Dict[str, Dict]:
    """Latest 3-month correlation to the market pivot per ticker."""
    with get_db_readonly() as conn:
        latest = conn.execute("SELECT MAX(date) FROM corr_matrices").fetchone()[0]
        if not latest:
            return {"_date": None, "data": {}}
        rows = conn.execute("""
            SELECT ticker, corr_json
            FROM corr_matrices
            WHERE date = ? AND window = '3_month'
        """, (latest,)).fetchall()
    data: Dict[str, Dict] = {}
    for r in rows:
        if r["corr_json"]:
            corr = json.loads(r["corr_json"])
            data[r["ticker"]] = {"corr": corr}
    return {"_date": latest, "data": data}


# ─── Write helpers ────────────────────────────────────────────────────

def upsert_crowded_trade(row: Dict[str, Any]) -> None:
    """Upsert a per-ticker crowded-trades result."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO crowded_trades (
                ticker, date, crowdedness_score, short_crowd, long_crowd,
                iv_crowd, options_crowd, momentum_crowd, pcr_crowd,
                corr_crowd, crowd_direction, signal, signal_details
            ) VALUES (
                :ticker, :date, :crowdedness_score, :short_crowd, :long_crowd,
                :iv_crowd, :options_crowd, :momentum_crowd, :pcr_crowd,
                :corr_crowd, :crowd_direction, :signal, :signal_details
            )
            ON CONFLICT(ticker, date) DO UPDATE SET
                crowdedness_score = excluded.crowdedness_score,
                short_crowd       = excluded.short_crowd,
                long_crowd        = excluded.long_crowd,
                iv_crowd          = excluded.iv_crowd,
                options_crowd     = excluded.options_crowd,
                momentum_crowd    = excluded.momentum_crowd,
                pcr_crowd         = excluded.pcr_crowd,
                corr_crowd        = excluded.corr_crowd,
                crowd_direction   = excluded.crowd_direction,
                signal            = excluded.signal,
                signal_details    = excluded.signal_details
        """, row)


# ─── Read helpers for analysis / web API ──────────────────────────────

def get_latest_ct_date() -> Optional[str]:
    """Most recent analysis date."""
    try:
        with get_db_readonly() as conn:
            r = conn.execute("SELECT MAX(date) FROM crowded_trades").fetchone()
        return r[0] if r and r[0] else None
    except sqlite3.OperationalError:
        return None


def get_top_crowded(limit: int = 30, min_score: float = 30.0) -> List[Dict]:
    """Top crowded trades by composite score."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT ct.ticker, t.name, t.category,
                   ct.crowdedness_score, ct.short_crowd, ct.long_crowd,
                   ct.options_crowd, ct.iv_crowd, ct.momentum_crowd,
                   ct.pcr_crowd, ct.corr_crowd, ct.crowd_direction,
                   ct.signal, ct.date
            FROM crowded_trades ct
            JOIN tickers t ON ct.ticker = t.ticker
            WHERE ct.date = (SELECT MAX(date) FROM crowded_trades)
              AND ct.crowdedness_score >= ?
            ORDER BY ct.crowdedness_score DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
    return [dict(r) for r in rows]


def get_by_direction(direction: str, limit: int = 30) -> List[Dict]:
    """Crowded trades filtered by direction."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT ct.ticker, t.name, t.category,
                   ct.crowdedness_score, ct.short_crowd, ct.long_crowd,
                   ct.crowd_direction, ct.signal, ct.date
            FROM crowded_trades ct
            JOIN tickers t ON ct.ticker = t.ticker
            WHERE ct.date = (SELECT MAX(date) FROM crowded_trades)
              AND ct.crowd_direction = ?
            ORDER BY ct.crowdedness_score DESC
            LIMIT ?
        """, (direction, limit)).fetchall()
    return [dict(r) for r in rows]


def get_ticker_history(ticker: str, limit: int = 10) -> List[Dict]:
    """Historical crowdedness for a single ticker."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT ticker, date, crowdedness_score, short_crowd, long_crowd,
                   options_crowd, iv_crowd, momentum_crowd, pcr_crowd,
                   corr_crowd, crowd_direction, signal
            FROM crowded_trades
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker.upper(), limit)).fetchall()
    return [dict(r) for r in rows]


def get_signal_summary() -> Dict[str, Any]:
    """Aggregate signal counts for the latest run."""
    with get_db_readonly() as conn:
        latest = conn.execute("SELECT MAX(date) FROM crowded_trades").fetchone()[0]
        if not latest:
            return {}
        counts = conn.execute("""
            SELECT signal, COUNT(*) as cnt,
                   SUM(CASE WHEN crowd_direction = 'short' THEN 1 ELSE 0 END) as shorts,
                   SUM(CASE WHEN crowd_direction = 'long' THEN 1 ELSE 0 END) as longs,
                   SUM(CASE WHEN crowd_direction = 'bilateral' THEN 1 ELSE 0 END) as bilateral
            FROM crowded_trades
            WHERE date = ?
            GROUP BY signal
        """, (latest,)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM crowded_trades WHERE date = ?", (latest,)
        ).fetchone()[0]
    return {
        "date": latest,
        "total": total,
        "by_signal": {r["signal"]: r["cnt"] for r in counts},
        "shorts": sum(r["shorts"] or 0 for r in counts),
        "longs": sum(r["longs"] or 0 for r in counts),
        "bilateral": sum(r["bilateral"] or 0 for r in counts),
    }


def get_ingestion_log(limit: int = 20) -> List[Dict]:
    """Get ingestion/analysis log."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT date, status, tickers_scanned, signals_found,
                   error_message, started_at, completed_at
            FROM ingestion_log_crowded
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

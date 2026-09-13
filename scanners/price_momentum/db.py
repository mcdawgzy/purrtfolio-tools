"""Database layer for Price Momentum Scanner.

Adds a **price_history** table to the unified purrtfolio.db and
provides read/write helpers for daily OHLCV bars, momentum metrics,
and earnings-gaps (first-print vs prior close).

The table is append-only at the cron level: each daily run upserts the
previous trading day's bar. The web frontend reads via SQLAlchemy-style
queries in db.py.
"""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta

from .config import DB_PATH, HISTORY_RETENTION_YEARS

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    """Write-capable connection (cron side)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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


# ─── Schema ─────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Daily OHLCV bars for the momentum watchlist
CREATE TABLE IF NOT EXISTS price_history (
    ticker  TEXT    NOT NULL,
    date    DATE    NOT NULL,
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL,
    adj_close REAL,
    volume  INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_price_ticker ON price_history(ticker);
CREATE INDEX IF NOT EXISTS idx_price_date   ON price_history(date);

-- Pre-computed momentum signals (refreshed daily after bars landed)
CREATE TABLE IF NOT EXISTS price_momentum_signals (
    ticker      TEXT    NOT NULL,
    date        DATE    NOT NULL,           -- signal-date (latest bar)
    roc_10d     REAL,    -- % change over 10 trading days
    roc_20d     REAL,    -- % change over 20 trading days
    roc_50d     REAL,    -- % change over 50 trading days
    sma_10d     REAL,
    sma_20d     REAL,
    sma_50d     REAL,
    volume_ema_10d REAL,
    volume_ratio REAL,    -- today vol / 10-day volume EMA
    is_volume_spike INTEGER DEFAULT 0,
    is_consolidating INTEGER DEFAULT 0,     -- inside-day, low vol
    -- Earnings-gap flag (set by gap scanner)
    gapped_open INTEGER DEFAULT 0,
    gap_pct REAL,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_signal_date ON price_momentum_signals(date);
"""

def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("price_history + price_momentum_signals tables ready at %s", DB_PATH)


# ─── Write ──────────────────────────────────────────────────────────

def upsert_daily_bars(bars: List[Dict[str, Any]]) -> int:
    """Upsert a batch of daily OHLCV bars into price_history.

    Each dict: {ticker, date(str YYYY-MM-DD), open, high, low, close,
                adj_close, volume}
    Returns count of rows inserted/updated.
    """
    if not bars:
        return 0
    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO price_history (ticker, date, open, high, low, close, adj_close, volume)
            VALUES (:ticker, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT(ticker, date) DO UPDATE SET
              open        = excluded.open,
              high        = excluded.high,
              low         = excluded.low,
              close       = excluded.close,
              adj_close   = excluded.adj_close,
              volume      = excluded.volume
            """,
            bars,
        )
        conn.execute(
            "DELETE FROM price_history WHERE date < date('now', ?)",
            (f"-{HISTORY_RETENTION_YEARS} years",),
        )
    return len(bars)


def upsert_signal(ticker: str, signal_date: date, **cols: Any) -> None:
    """Upsert one row in price_momentum_signals."""
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    with get_db() as conn:
        conn.execute(
            f"""
            INSERT INTO price_momentum_signals
              (ticker, date, {', '.join(cols)})
            VALUES
              (:ticker, :date, {', '.join(':' + k for k in cols)})
            ON CONFLICT(ticker, date) DO UPDATE SET {sets}
            """,
            {"ticker": ticker, "date": str(signal_date), **cols},
        )


# ─── Read (web API) ─────────────────────────────────────────────────

def get_latest_bars(tickers: List[str], limit: int = 30) -> List[Dict]:
    """Latest N trading days of OHLCV for each ticker in the list."""
    placeholders = ", ".join("?" for _ in tickers)
    with get_db_readonly() as conn:
        rows = conn.execute(f"""
            SELECT ticker, date, open, high, low, close, adj_close, volume
            FROM price_history
            WHERE ticker IN ({placeholders})
            ORDER BY ticker, date DESC
            LIMIT ?
        """, (*[t.upper() for t in tickers], limit)).fetchall()
        # Re-chunk by ticker (SQLite LIMIT applies globally)
    # Re-sort client-side into per-ticker lists
    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        by_ticker.setdefault(d["ticker"], []).append(d)
    # Flatten back
    flat = []
    for t in tickers:
        tkey = t.upper()
        flat.extend(by_ticker.get(tkey, []))
    return flat


def get_latest_signal_date() -> Optional[str]:
    """Most recent date for which signals exist."""
    with get_db_readonly() as conn:
        r = conn.execute(
            "SELECT MAX(date) FROM price_momentum_signals"
        ).fetchone()
    return r[0] if r and r[0] else None


def get_momentum_rankings(
    min_price: float = 5.0,
    limit: int = 50,
) -> List[Dict]:
    """Top movers by 20-day ROC, latest signal date."""
    latest = get_latest_signal_date()
    if not latest:
        return []
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT s.ticker, t.name, t.category,
                   s.roc_20d, s.roc_10d, s.roc_50d,
                   s.sma_20d, s.volume_ratio,
                   s.is_volume_spike, s.is_consolidating,
                   s.gapped_open, s.gap_pct
            FROM price_momentum_signals s
            JOIN tickers t ON s.ticker = t.ticker
            WHERE s.date = ?
              AND (s.sma_20d >= ? OR s.sma_20d IS NULL)
            ORDER BY ABS(s.roc_20d) DESC NULLS LAST
            LIMIT ?
        """, (latest, min_price, limit)).fetchall()
    return [dict(r) for r in rows]


def get_volume_spike_alerts(limit: int = 30) -> List[Dict]:
    """Tickers with volume > 2x the 10-day volume EMA."""
    latest = get_latest_signal_date()
    if not latest:
        return []
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT s.ticker, t.name, t.category,
                   s.roc_20d, s.volume_ratio, s.sma_20d,
                   s.is_consolidating
            FROM price_momentum_signals s
            JOIN tickers t ON s.ticker = t.ticker
            WHERE s.date = ? AND s.is_volume_spike = 1
            ORDER BY s.volume_ratio DESC
            LIMIT ?
        """, (latest, limit)).fetchall()
    return [dict(r) for r in rows]


def get_consolidation_scan(limit: int = 30) -> List[Dict]:
    """Tickers currently in a consolidation pattern (low vol, inside range)."""
    latest = get_latest_signal_date()
    if not latest:
        return []
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT s.ticker, t.name, t.category,
                   s.roc_20d, s.roc_10d, s.sma_20d,
                   s.volume_ratio, s.is_consolidating
            FROM price_momentum_signals s
            JOIN tickers t ON s.ticker = t.ticker
            WHERE s.date = ? AND s.is_consolidating = 1
            ORDER BY s.volume_ratio ASC
            LIMIT ?
        """, (latest, limit)).fetchall()
    return [dict(r) for r in rows]


def get_earnings_gaps(limit: int = 30) -> List[Dict]:
    """Top earnings-gaps (overnight gaps) on the latest signal date."""
    latest = get_latest_signal_date()
    if not latest:
        return []
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT s.ticker, t.name, t.category,
                   s.gap_pct, s.roc_20d, s.sma_20d
            FROM price_momentum_signals s
            JOIN tickers t ON s.ticker = t.ticker
            WHERE s.date = ? AND s.gapped_open = 1
            ORDER BY ABS(s.gap_pct) DESC
            LIMIT ?
        """, (latest, limit)).fetchall()
    return [dict(r) for r in rows]


def search_tickers(query: str, limit: int = 20) -> List[Dict]:
    """Search the momentum watchlist."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT ticker, name, category, exchange, latest_short, latest_dtc
            FROM tickers
            WHERE ticker LIKE ? OR name LIKE ?
            ORDER BY CASE WHEN ticker LIKE ? THEN 0 ELSE 1 END,
                     latest_short DESC NULLS LAST
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"{query.upper()}%", limit)).fetchall()
    return [dict(r) for r in rows]


def get_meta() -> dict:
    """Metadata for the momentum tab."""
    latest_date = get_latest_signal_date()
    with get_db_readonly() as conn:
        counts = {
            "bars": conn.execute(
                "SELECT COUNT(*) FROM price_history"
            ).fetchone()[0],
            "tickers": conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM price_history"
            ).fetchone()[0],
        }
    return {
        "latest_signal_date": latest_date,
        "bar_count": counts["bars"],
        "ticker_count": counts["tickers"],
    }


def price_history_for_ticker(ticker: str, limit: int = 60) -> List[Dict]:
    """Daily OHLCV for a single ticker (most recent first)."""
    with get_db_readonly() as conn:
        rows = conn.execute("""
            SELECT date, open, high, low, close, adj_close, volume
            FROM price_history
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker.upper(), limit)).fetchall()
    return [dict(r) for r in rows]

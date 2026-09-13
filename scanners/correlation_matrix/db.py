"""Database layer for Correlation Matrix Scanner.

Stores correlation matrices as compact JSON in the unified DB,
so the web frontend can fetch them without recomputing.
"""
from __future__ import annotations

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
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


SCHEMA_SQL = """
-- Correlation matrices (one row per ticker-date-window)
-- Stored as a compact dict-to-dict JSON: {target_ticker: {pivot_ticker: corr}}
CREATE TABLE IF NOT EXISTS corr_matrices (
    ticker      TEXT    NOT NULL,
    date        DATE    NOT NULL,   -- signal date (latest bar used)
    window      TEXT    NOT NULL,   -- '1_month', '3_month', etc.
    corr_json   JSON,               -- {pivot: correlation}
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date, window)
);

CREATE INDEX IF NOT EXISTS idx_corr_ticker  ON corr_matrices(ticker);
CREATE INDEX IF NOT EXISTS idx_corr_date    ON corr_matrices(date);
CREATE INDEX IF NOT EXISTS idx_corr_window  ON corr_matrices(window);
"""

def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("corr_matrices table ready at %s", DB_PATH)


# ─── Write ──────────────────────────────────────────────────────────

def upsert_corr_row(ticker: str, date_str: str, window: str, corr_dict: dict) -> None:
    """Upsert a single ticker's correlation row for a window."""
    with get_db() as conn:
        conn.execute("""
            INSERT INTO corr_matrices (ticker, date, window, corr_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ticker, date, window) DO UPDATE SET
              corr_json = excluded.corr_json,
              updated_at = CURRENT_TIMESTAMP
        """, (ticker, date_str, window, json.dumps(corr_dict)))


# ─── Read (web API) ─────────────────────────────────────────────────

def get_latest_corr_date() -> Optional[str]:
    """Most recent date for which any correlation data exists."""
    with get_db_readonly() as conn:
        r = conn.execute("SELECT MAX(date) FROM corr_matrices").fetchone()
    return r[0] if r and r[0] else None


def get_corr_for_ticker(
    ticker: str,
    window: str = "3_month",
    date_str: Optional[str] = None,
) -> Optional[dict]:
    """Return {pivot_ticker: correlation} for *ticker* at *window*."""
    with get_db_readonly() as conn:
        if date_str:
            row = conn.execute(
                "SELECT corr_json FROM corr_matrices WHERE ticker=? AND window=? AND date=?",
                (ticker.upper(), window, date_str),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT corr_json FROM corr_matrices WHERE ticker=? AND window=? ORDER BY date DESC LIMIT 1",
                (ticker.upper(), window),
            ).fetchone()
    if not row or not row["corr_json"]:
        return None
    return json.loads(row["corr_json"])


def get_corr_matrix(
    window: str = "3_month",
    date_str: Optional[str] = None,
    tickers: Optional[List[str]] = None,
    min_corr_abs: float = 0.0,
) -> dict:
    """Full correlation matrix for a window.

    Returns:
      {
        "date": "YYYY-MM-DD",
        "window": "3_month",
        "tickers": [...],           # row tickers
        "pivots": [...],             # pivot tickers
        "matrix": { "TICKER": { "PIVOT": 0.82, ... }, ... }
      }
    """
    with get_db_readonly() as conn:
        if date_str:
            db_date = date_str
        else:
            row = conn.execute(
                "SELECT MAX(date) FROM corr_matrices WHERE window=?", (window,)
            ).fetchone()
            db_date = row[0] if row else None
        if not db_date:
            return {"date": None, "window": window, "tickers": [], "pivots": [], "matrix": {}}

        # Get all tickers for this window+date
        ticker_rows = conn.execute(
            "SELECT DISTINCT ticker FROM corr_matrices WHERE window=? AND date=?",
            (window, db_date),
        ).fetchall()
        all_tickers = [r["ticker"] for r in ticker_rows]
        if tickers:
            wanted = set(t.upper() for t in tickers)
            all_tickers = [t for t in all_tickers if t in wanted]

        if not all_tickers:
            return {"date": db_date, "window": window, "tickers": [], "pivots": [], "matrix": {}}

        placeholders = ", ".join("?" for _ in all_tickers)
        rows = conn.execute(f"""
            SELECT ticker, corr_json FROM corr_matrices
            WHERE window=? AND date=? AND ticker IN ({placeholders})
        """, (window, db_date, *all_tickers)).fetchall()

    # Infer pivot set from the first row
    pivots: list[str] = []
    matrix: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["corr_json"]:
            cj = json.loads(r["corr_json"])
            if not pivots:
                pivots = list(cj.keys())
            matrix[r["ticker"]] = {
                p: round(v, 4) for p, v in cj.items()
                if min_corr_abs == 0.0 or abs(v) >= min_corr_abs
            }

    return {
        "date": db_date,
        "window": window,
        "tickers": all_tickers,
        "pivots": pivots,
        "matrix": matrix,
    }


def get_corr_to_pivot(
    pivot: str,
    window: str = "3_month",
    date_str: Optional[str] = None,
    limit: int = 50,
    min_abs: float = 0.2,
) -> List[Dict]:
    """All tickers' correlation to a specific pivot ticker, sorted by abs value."""
    if date_str is None:
        date_str = get_latest_corr_date()
    if not date_str:
        return []

    # Build the JSON path safely — only allow alphanumeric ticker chars.
    pivot_clean = pivot.upper().replace("-", "_").replace(".", "_")
    json_path = f"$.{pivot_clean}"

    with get_db_readonly() as conn:
        rows = conn.execute(f"""
            SELECT cm.ticker, t.name, t.category,
                   json_extract(cm.corr_json, '{json_path}') AS corr
            FROM corr_matrices cm
            JOIN tickers t ON cm.ticker = t.ticker
            WHERE cm.window = ? AND cm.date = ?
              AND json_extract(cm.corr_json, '{json_path}') IS NOT NULL
              AND ABS(json_extract(cm.corr_json, '{json_path}')) >= ?
            ORDER BY ABS(json_extract(cm.corr_json, '{json_path}')) DESC
            LIMIT ?
        """, (window, date_str, min_abs, limit)).fetchall()
    return [dict(r) for r in rows]


def get_meta() -> dict:
    latest_date = get_latest_corr_date()
    with get_db_readonly() as conn:
        count = conn.execute("SELECT COUNT(*) FROM corr_matrices").fetchone()[0]
    return {
        "latest_date": latest_date,
        "total_rows": count,
    }

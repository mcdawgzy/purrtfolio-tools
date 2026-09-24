"""
Database layer for IV Rank Scanner — Unified Schema (purrtfolio.db)

Tables:
  iv_rank           — daily IV Rank / Percentile snapshots
  ingestion_log_iv  — audit trail
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict

from .config import DB_PATH


@contextmanager
def get_db():
    """Context manager for database connections."""
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


def init_db():
    """Create IV Rank tables if they don't already exist."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Daily IV Rank data (one row per date+ticker)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS iv_rank (
                date          DATE NOT NULL,
                ticker        TEXT NOT NULL,
                iv            REAL,                  -- implied volatility (%)
                iv_rank       REAL,                  -- 0-100
                iv_pctile     REAL,                  -- 0-100
                days_52w      INTEGER,               -- data points in lookback
                iv_min_52w    REAL,
                iv_max_52w    REAL,
                iv_mean_52w   REAL,
                iv_median_52w REAL,
                iv_std_52w    REAL,
                signal        TEXT,                  -- HIGH_IV / LOW_IV / NEUTRAL
                ingested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, ticker)
            )
        """)

        # Ingestion audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_log_iv (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          DATE NOT NULL,
                status        TEXT NOT NULL,
                rows_inserted INTEGER DEFAULT 0,
                error_message TEXT,
                started_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at  TIMESTAMP
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_iv_date ON iv_rank(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_iv_ticker ON iv_rank(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_iv_signal ON iv_rank(signal)")
        conn.commit()
    print(f"IV Rank database schema ready at {DB_PATH}")


def get_latest_date() -> Optional[str]:
    """Most recent date in iv_rank."""
    with get_db() as conn:
        row = conn.execute("SELECT MAX(date) FROM iv_rank").fetchone()
        return row[0] if row and row[0] else None


def get_latest_iv() -> List[Dict]:
    """Latest IV Rank data for all tickers (sorted by IV Rank descending)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, ticker, iv, iv_rank, iv_pctile, days_52w,
                   iv_min_52w, iv_max_52w, iv_mean_52w, signal
            FROM iv_rank
            WHERE date = (SELECT MAX(date) FROM iv_rank)
            ORDER BY iv_rank DESC NULLS LAST, ticker
        """).fetchall()
        return [dict(r) for r in rows]


def get_history(ticker: str, days: int = 300) -> List[Dict]:
    """Historical IV / IV Rank for a single ticker (oldest-first)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, ticker, iv, iv_rank, iv_pctile, signal
            FROM iv_rank
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker.upper(), days)).fetchall()
        # Reverse to oldest-first for charting
        return list(reversed([dict(r) for r in rows]))


def get_signals() -> List[Dict]:
    """Current HIGH_IV / LOW_IV signals."""
    with get_db() as conn:
        latest_date = conn.execute("SELECT MAX(date) FROM iv_rank").fetchone()[0]
        if not latest_date:
            return []
        rows = conn.execute("""
            SELECT ticker, date, iv, iv_rank, iv_pctile, days_52w,
                   iv_min_52w, iv_max_52w, signal
            FROM iv_rank
            WHERE date = ? AND signal != 'NEUTRAL'
            ORDER BY iv_pctile DESC
        """, (latest_date,)).fetchall()
        return [dict(r) for r in rows]


def get_ingestion_log(limit: int = 20) -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, status, rows_inserted, error_message, started_at, completed_at
            FROM ingestion_log_iv
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

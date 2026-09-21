"""
Database layer for Put/Call Ratio Scanner — Unified Schema (purrtfolio.db)
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import date

from .config import DB_PATH


@contextmanager
def get_db():
    """Context manager for database connections (same pattern as short_interest_scanner)."""
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
    """Create put_call_ratio tables if they don't already exist."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Verify the unified schema's tickers table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickers'")
        if not cursor.fetchone():
            print("WARNING: 'tickers' table not found in unified schema — run the schema migration first")

        # Daily put/call ratio series (one row per date+series)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS put_call_ratio (
                date            DATE NOT NULL,
                series          TEXT NOT NULL,         -- TOTAL, INDEX, EQUITY, ETP, VIX, SPX_SPXW, OEX, MRUT
                ratio           REAL,                  -- put/call ratio
                call_volume     BIGINT,
                put_volume      BIGINT,
                total_volume    BIGINT,
                call_oi         BIGINT,
                put_oi          BIGINT,
                total_oi        BIGINT,
                ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, series)
            )
        """)

        # Ingestion audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_log_pcr (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                date            DATE NOT NULL,
                status          TEXT NOT NULL,         -- 'completed', 'failed', 'no_data'
                rows_inserted   INTEGER DEFAULT 0,
                error_message   TEXT,
                started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at    TIMESTAMP
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pcr_date ON put_call_ratio(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pcr_series ON put_call_ratio(series)")

        # Latest-series summary table (materialized, updated on each ingest)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS put_call_latest (
                series          TEXT PRIMARY KEY,
                date            DATE,
                ratio           REAL,
                call_volume     BIGINT,
                put_volume      BIGINT,
                total_volume    BIGINT,
                call_oi         BIGINT,
                put_oi          BIGINT,
                total_oi        BIGINT,
                ma5             REAL,
                ma20            REAL,
                ma50            REAL,
                z_score         REAL,
                signal          TEXT,                  -- EXTREME_HIGH, HIGH, NEUTRAL, LOW, EXTREME_LOW
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
    print(f"Put/Call Ratio database schema ready at {DB_PATH}")


def get_latest_date() -> Optional[str]:
    """Get the most recent date in the put_call_ratio table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM put_call_ratio")
        row = cursor.fetchone()
        return row[0] if row and row[0] else None


def get_latest_series() -> List[Dict]:
    """Get the latest data for all series (from materialized put_call_latest)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT series, date, ratio, call_volume, put_volume, total_volume,
                   call_oi, put_oi, total_oi, ma5, ma20, ma50, z_score, signal
            FROM put_call_latest
            ORDER BY series
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_history(series: str, days: int = 60) -> List[Dict]:
    """Get historical put/call ratio data for a single series."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, ratio, call_volume, put_volume, total_volume,
                   call_oi, put_oi, total_oi,
                   ma5, ma20, ma50, z_score, signal
            FROM put_call_ratio pc
            LEFT JOIN (
                SELECT date,
                       AVG(ratio) OVER (PARTITION BY series ORDER BY date
                                        ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as ma5,
                       AVG(ratio) OVER (PARTITION BY series ORDER BY date
                                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as ma20,
                       AVG(ratio) OVER (PARTITION BY series ORDER BY date
                                        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) as ma50
                FROM put_call_ratio WHERE series = ?
            ) ma ON pc.date = ma.date
            WHERE pc.series = ?
            ORDER BY pc.date DESC
            LIMIT ?
        """, (series, series, days))
        return [dict(row) for row in cursor.fetchall()]


def get_signals() -> List[Dict]:
    """Get current extreme readings (signals) for all series."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT series, date, ratio, ma5, ma20, z_score, signal
            FROM put_call_latest
            WHERE signal IN ('EXTREME_HIGH', 'EXTREME_LOW', 'HIGH', 'LOW')
            ORDER BY 
                CASE signal
                    WHEN 'EXTREME_HIGH' THEN 0
                    WHEN 'EXTREME_LOW' THEN 1
                    WHEN 'HIGH' THEN 2
                    WHEN 'LOW' THEN 3
                END,
                z_score DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_ingestion_log(limit: int = 20) -> List[Dict]:
    """Get ingestion log."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, status, rows_inserted, error_message, started_at, completed_at
            FROM ingestion_log_pcr
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

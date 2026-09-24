"""Database layer for Unusual Activity scanner.

Tables:
  unusual_activity    — daily unusual options + volume-spike snapshots
  ingestion_log_ua    — audit trail
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict

from .config import DB_PATH


@contextmanager
def get_db():
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
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS unusual_activity (
                date          DATE NOT NULL,
                ticker        TEXT NOT NULL,
                activity_type TEXT NOT NULL,   -- 'options' | 'volume'
                call_put      TEXT,            -- 'call' | 'put' | 'underlying'
                expiry        TEXT,            -- options expiry (NULL for volume)
                strike        REAL,            -- strike price (NULL for volume)
                volume        INTEGER,         -- contracts traded (options) / shares (volume)
                open_interest INTEGER,         -- open interest (options) / NULL
                voi_ratio     REAL,            -- volume / open_interest
                notional_usd  REAL,            -- dollar value
                iv_pct        REAL,            -- implied volatility (%)
                price         REAL,            -- underlying price
                avg_vol_20d   REAL,            -- 20-day avg volume (volume type)
                vol_ratio     REAL,            -- current vol / avg vol (volume type)
                severity_score REAL,            -- 0-100 composite
                signal        TEXT,            -- EXTREME / HIGH / MEDIUM / LOW
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, ticker, activity_type, expiry, strike, call_put)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_log_ua (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                date          DATE NOT NULL,
                status        TEXT NOT NULL,
                rows_inserted INTEGER DEFAULT 0,
                error_message TEXT,
                started_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at  TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ua_date ON unusual_activity(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ua_ticker ON unusual_activity(ticker)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ua_signal ON unusual_activity(signal)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ua_severity ON unusual_activity(severity_score DESC)")
        conn.commit()


def get_latest_date() -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT MAX(date) FROM unusual_activity").fetchone()
        return row[0] if row and row[0] else None


def get_latest_activity() -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, ticker, activity_type, call_put, expiry, strike,
                   volume, open_interest, voi_ratio, notional_usd, iv_pct,
                   price, avg_vol_20d, vol_ratio, severity_score, signal
            FROM unusual_activity
            WHERE date = (SELECT MAX(date) FROM unusual_activity)
            ORDER BY severity_score DESC, ticker
        """).fetchall()
        return [dict(r) for r in rows]


def get_signals() -> List[Dict]:
    with get_db() as conn:
        latest = conn.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        if not latest:
            return []
        rows = conn.execute("""
            SELECT ticker, activity_type, call_put, expiry, strike,
                   volume, notional_usd, iv_pct, price, severity_score, signal
            FROM unusual_activity
            WHERE date = ? AND signal IN ('EXTREME', 'HIGH')
            ORDER BY severity_score DESC
        """, (latest,)).fetchall()
        return [dict(r) for r in rows]


def get_history(ticker: str, limit: int = 100) -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, activity_type, call_put, expiry, strike,
                   volume, voi_ratio, notional_usd, iv_pct, price,
                   vol_ratio, severity_score, signal
            FROM unusual_activity
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker.upper(), limit)).fetchall()
        return list(reversed([dict(r) for r in rows]))


def get_ingestion_log(limit: int = 20) -> List[Dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, status, rows_inserted, error_message, started_at, completed_at
            FROM ingestion_log_ua
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

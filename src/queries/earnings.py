"""Earnings revision momentum."""
from __future__ import annotations

import sqlite3

from ..database import db_conn, writable_conn


# ---------------------------------------------------------------------------
# Earnings Revision Momentum
# ---------------------------------------------------------------------------
def init_earnings_revisions() -> None:
    """Create earnings revision tables if they don't exist (writable)."""
    conn = writable_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_revision_momentum (
            ticker              TEXT PRIMARY KEY,
            latest_report_date  DATE,
            avg_revision_4q     REAL,    -- average pct revision over last 4 quarters
            pct_positive        REAL,    -- % of positive surprises (0-1)
            avg_surprise_pct    REAL,    -- average earnings surprise %
            trend               TEXT,    -- 'improving' | 'deteriorating' | 'stable'
            zscore              REAL,    -- standardized momentum score
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS earnings_revision_history (
            ticker              TEXT NOT NULL,
            date                DATE NOT NULL,
            avg_revision_4q     REAL,
            pct_positive        REAL,
            avg_surprise_pct    REAL,
            trend               TEXT,
            zscore              REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_erm_date ON earnings_revision_momentum(created_at)
    """)
    conn.commit()
    conn.close()


def get_earnings_revision_momentum() -> list[dict]:
    """Return all tickers with earnings revision momentum, sorted by zscore desc."""
    try:
        with db_conn() as c:
            rows = c.execute("""
                SELECT ticker, latest_report_date, avg_revision_4q, pct_positive,
                       avg_surprise_pct, trend, zscore, created_at
                FROM earnings_revision_momentum
                ORDER BY zscore DESC, pct_positive DESC
            """).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_earnings_revision_history(ticker: str) -> list[dict]:
    """Return historical momentum snapshots for a single ticker."""
    try:
        with db_conn() as c:
            rows = c.execute("""
                SELECT date, avg_revision_4q, pct_positive, avg_surprise_pct,
                       trend, zscore
                FROM earnings_revision_history
                WHERE ticker = ?
                ORDER BY date DESC
            """, (ticker.upper(),)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_earnings_revision_meta() -> dict:
    """Metadata for the earnings revision page."""
    try:
        with db_conn() as c:
            latest = c.execute(
                "SELECT MAX(created_at) FROM earnings_revision_momentum"
            ).fetchone()[0]
            total = c.execute(
                "SELECT COUNT(*) FROM earnings_revision_momentum"
            ).fetchone()[0]
            improving = c.execute(
                "SELECT COUNT(*) FROM earnings_revision_momentum WHERE trend = 'improving'"
            ).fetchone()[0]
            deteriorating = c.execute(
                "SELECT COUNT(*) FROM earnings_revision_momentum WHERE trend = 'deteriorating'"
            ).fetchone()[0]
    except sqlite3.OperationalError:
        latest, total, improving, deteriorating = None, 0, 0, 0
    return {
        "latest_date": latest,
        "ticker_count": total,
        "improving": improving,
        "deteriorating": deteriorating,
    }

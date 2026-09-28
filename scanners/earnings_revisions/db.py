"""Schema for the earnings revision momentum scanner (writes purrtfolio.db)."""
from __future__ import annotations

from ..common import connect
from .config import DB_PATH


def init_earnings_revisions() -> None:
    """Create earnings revision tables if they don't exist."""
    conn = connect(DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS earnings_revision_momentum (
                ticker              TEXT PRIMARY KEY,
                latest_report_date  DATE,
                avg_revision_4q     REAL,    -- average pct revision over last 4 quarters
                pct_positive        REAL,    -- % of positive surprises (0-1)
                avg_surprise_pct    REAL,    -- average earnings surprise %
                trend               TEXT,    -- 'improving' | 'deteriorating' | 'stable'
                zscore              REAL,    -- standardized momentum score
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS earnings_revision_history (
                ticker              TEXT NOT NULL,
                date                DATE NOT NULL,
                avg_revision_4q     REAL,
                pct_positive        REAL,
                avg_surprise_pct    REAL,
                trend               TEXT,
                zscore              REAL,
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_erm_date ON earnings_revision_momentum(created_at);
        """)
    finally:
        conn.close()

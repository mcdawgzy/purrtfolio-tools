"""Earnings revision momentum."""
from __future__ import annotations

import sqlite3

from ..database import db_conn


# ---------------------------------------------------------------------------
# Earnings Revision Momentum
# ---------------------------------------------------------------------------
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

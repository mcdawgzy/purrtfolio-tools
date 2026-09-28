"""Multi-signal crowded trades scanner (crowded_trades table)."""
from __future__ import annotations

import json

from ..database import db_conn, row_dicts, table_exists


# ---------------------------------------------------------------------------
# Multi-Signal Crowded Trades Scanner
# ---------------------------------------------------------------------------
def get_crowded_trades_latest(limit: int = 100, min_score: float | None = None,
                              signal: str | None = None) -> dict:
    """Latest multi-signal crowded trades scan from scanners/crowded_trades.

    Reads from the `crowded_trades` table (written by the daily cron job).
    Returns the latest date, signal severity counts, and ranked rows with
    parsed component scores from the JSON signal_details column.
    """
    with db_conn() as c:
        if not table_exists(c, "crowded_trades"):
            return {"latest_date": None, "rows": [], "signal_counts": {}}
        latest = c.execute("SELECT MAX(date) FROM crowded_trades").fetchone()[0]
        if not latest:
            return {"latest_date": None, "rows": [], "signal_counts": {}}
        where, params = ["date = ?"], [latest]
        if min_score is not None:
            where.append("crowdedness_score >= ?")
            params.append(min_score)
        if signal:
            where.append("signal = ?")
            params.append(signal)
        rows = row_dicts(c.execute(f"""
            SELECT ticker, crowdedness_score AS total_score, crowd_direction AS direction, signal,
                   short_crowd, options_crowd, iv_crowd, momentum_crowd,
                   pcr_crowd, corr_crowd, signal_details
            FROM crowded_trades
            WHERE {" AND ".join(where)}
            ORDER BY crowdedness_score DESC, ticker
            LIMIT ?
        """, [*params, limit]).fetchall())
        for r in rows:
            try:
                details = json.loads(r.pop("signal_details")) if r.get("signal_details") else {}
            except (json.JSONDecodeError, TypeError):
                details = {}
            r["details"] = details
        # Counts cover the whole scan, not just the returned page
        counts = {"HIGH": 0, "MEDIUM": 0, "NEUTRAL": 0}
        for sig, cnt in c.execute(
            "SELECT signal, COUNT(*) FROM crowded_trades WHERE date = ? GROUP BY signal",
            (latest,)
        ).fetchall():
            if sig in counts:
                counts[sig] = cnt
        return {
            "latest_date": latest,
            "signal_counts": counts,
            "rows": rows,
        }


def get_crowded_trades_meta() -> dict:
    """Metadata for the multi-signal crowded trades page."""
    with db_conn() as c:
        if not table_exists(c, "crowded_trades"):
            return {"latest_date": None, "total_tickers": 0,
                    "signal_counts": {}, "last_ingestion": None}
        latest = c.execute("SELECT MAX(date) FROM crowded_trades").fetchone()[0]
        ticker_count = 0
        if latest:
            ticker_count = c.execute(
                "SELECT COUNT(DISTINCT ticker) FROM crowded_trades WHERE date = ?",
                (latest,)
            ).fetchone()[0]
            counts = {"HIGH": 0, "MEDIUM": 0, "NEUTRAL": 0}
            for sig, cnt in c.execute(
                "SELECT signal, COUNT(*) FROM crowded_trades WHERE date = ? GROUP BY signal",
                (latest,)
            ).fetchall():
                if sig in counts:
                    counts[sig] = cnt
        else:
            counts = {"HIGH": 0, "MEDIUM": 0, "NEUTRAL": 0}
        last_log = c.execute(
            "SELECT started_at, completed_at, status, tickers_scanned, signals_found"
            " FROM ingestion_log_crowded ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "latest_date": latest,
            "total_tickers": ticker_count,
            "signal_counts": counts,
            "last_ingestion": row_dicts([last_log])[0] if last_log else None,
        }

"""Options-derived signals: CBOE put/call ratio, IV rank, unusual activity."""
from __future__ import annotations

from ..database import db_conn, row_dicts, table_exists


# ---------------------------------------------------------------------------
# Put/Call Ratio (CBOE)
# ---------------------------------------------------------------------------
def get_pcr_meta() -> dict:
    """Top-level PCR info: latest date, series coverage, ingestion log."""
    with db_conn() as c:
        if not table_exists(c, "put_call_ratio"):
            return {"latest_date": None, "periods": [], "series": [], "last_update": None}

        latest = c.execute("SELECT MAX(date) FROM put_call_ratio").fetchone()[0]
        periods = row_dicts(c.execute(
            "SELECT DISTINCT date FROM put_call_ratio ORDER BY date DESC LIMIT 30"
        ))
        series = [r[0] for r in c.execute(
            "SELECT DISTINCT series FROM put_call_ratio ORDER BY series"
        ).fetchall()]
        last_log = c.execute(
            "SELECT date, status, rows_inserted, started_at FROM ingestion_log_pcr "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "latest_date": latest,
            "periods": [p["date"] for p in periods],
            "series": series,
            "last_update": dict(last_log) if last_log else None,
        }


def get_pcr_latest() -> dict:
    """Latest daily put/call ratio data for all series (from materialized table)."""
    with db_conn() as c:
        if not table_exists(c, "put_call_ratio"):
            return {"latest_date": None, "rows": []}
        rows = row_dicts(c.execute("""
            SELECT series, date, ratio,
                   call_volume, put_volume, total_volume,
                   call_oi, put_oi, total_oi,
                   ma5, ma20, ma50, z_score, signal
            FROM put_call_latest
            ORDER BY series
        """))
        latest_date = c.execute("SELECT MAX(date) FROM put_call_ratio").fetchone()[0]
        return {"latest_date": latest_date, "rows": rows}


def get_pcr_history(series: str, days: int = 60) -> dict:
    """Historical put/call ratio for a single series.

    MA5 is computed client-side from the raw daily ratios so the chart
    can render a smoothed line without an extra materialized column.
    """
    with db_conn() as c:
        if not table_exists(c, "put_call_ratio"):
            return {"series": series, "rows": []}
        rows = row_dicts(c.execute("""
            SELECT date, ratio, call_volume, put_volume, total_volume,
                   call_oi, put_oi, total_oi
            FROM put_call_ratio
            WHERE series = ?
            ORDER BY date DESC
            LIMIT ?
        """, (series.upper(), days)))
        rows.reverse()  # oldest first for charting

        # Compute 5-day simple moving average on the fly
        for i, r in enumerate(rows):
            window = [rows[j]["ratio"] for j in range(max(0, i - 4), i + 1) if rows[j]["ratio"] is not None]
            r["ma5"] = round(sum(window) / len(window), 3) if window else None

        return {"series": series.upper(), "rows": rows}


def get_pcr_signals() -> dict:
    """Current extreme readings for all series."""
    with db_conn() as c:
        if not table_exists(c, "put_call_ratio"):
            return {"latest_date": None, "signals": []}
        latest = c.execute("SELECT MAX(date) FROM put_call_ratio").fetchone()[0]
        signals = row_dicts(c.execute("""
            SELECT series, date, ratio, ma5, ma20, ma50, z_score, signal
            FROM put_call_latest
            WHERE signal IN ('EXTREME_HIGH', 'EXTREME_LOW', 'HIGH', 'LOW')
            ORDER BY
                CASE signal
                    WHEN 'EXTREME_HIGH' THEN 0
                    WHEN 'EXTREME_LOW'   THEN 1
                    WHEN 'HIGH'          THEN 2
                    WHEN 'LOW'           THEN 3
                END,
                z_score DESC
        """))
        return {"latest_date": latest, "signals": signals}


# ---------------------------------------------------------------------------
# IV Rank & IV Percentile
# ---------------------------------------------------------------------------
def get_iv_meta() -> dict:
    """Metadata: latest date, ticker count, signal counts, last ingestion."""
    with db_conn() as c:
        if not table_exists(c, "iv_rank"):
            return {"latest_date": None, "ticker_count": 0,
                    "high_iv_count": 0, "low_iv_count": 0,
                    "last_ingestion": None}
        latest = c.execute("SELECT MAX(date) FROM iv_rank").fetchone()[0]
        ticker_count = c.execute(
            "SELECT COUNT(DISTINCT ticker) FROM iv_rank WHERE date = ?", (latest,)
        ).fetchone()[0]
        high_iv = c.execute(
            "SELECT COUNT(*) FROM iv_rank WHERE date = ? AND signal = 'HIGH_IV'", (latest,)
        ).fetchone()[0]
        low_iv = c.execute(
            "SELECT COUNT(*) FROM iv_rank WHERE date = ? AND signal = 'LOW_IV'", (latest,)
        ).fetchone()[0]
        last_log = c.execute(
            "SELECT date, status, rows_inserted, started_at, completed_at "
            "FROM ingestion_log_iv ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "latest_date": latest,
            "ticker_count": ticker_count,
            "high_iv_count": high_iv,
            "low_iv_count": low_iv,
            "last_ingestion": row_dicts([last_log])[0] if last_log else None,
        }


def get_iv_latest() -> dict:
    with db_conn() as c:
        if not table_exists(c, "iv_rank"):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM iv_rank").fetchone()[0]
        rows = row_dicts(c.execute("""
            SELECT ticker, date, iv, iv_rank, iv_pctile, days_52w,
                   iv_min_52w, iv_max_52w, iv_mean_52w, signal
            FROM iv_rank
            WHERE date = ?
            ORDER BY iv_rank DESC NULLS LAST, ticker
        """, (latest,)))
        return {"latest_date": latest, "rows": rows}


def get_iv_history(ticker: str, days: int = 300) -> dict:
    with db_conn() as c:
        if not table_exists(c, "iv_rank"):
            return {"ticker": ticker.upper(), "rows": []}
        rows = row_dicts(c.execute("""
            SELECT date, ticker, iv, iv_rank, iv_pctile, signal
            FROM (SELECT * FROM iv_rank WHERE ticker = ?
                  ORDER BY date DESC LIMIT ?)
            ORDER BY date ASC
        """, (ticker.upper(), days)))
        return {"ticker": ticker.upper(), "rows": rows}


# ---------------------------------------------------------------------------
# Unusual Activity / Dark Pool
# ---------------------------------------------------------------------------
def get_ua_meta() -> dict:
    """Metadata: latest date, ticker count, signal counts, last ingestion."""
    with db_conn() as c:
        if not table_exists(c, "unusual_activity"):
            return {"latest_date": None, "ticker_count": 0,
                    "extreme_count": 0, "high_count": 0,
                    "last_ingestion": None}
        latest = c.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        ticker_count = c.execute(
            "SELECT COUNT(DISTINCT ticker) FROM unusual_activity WHERE date = ?", (latest,)
        ).fetchone()[0]
        ext = c.execute(
            "SELECT COUNT(*) FROM unusual_activity WHERE date = ? AND signal = 'EXTREME'", (latest,)
        ).fetchone()[0]
        high = c.execute(
            "SELECT COUNT(*) FROM unusual_activity WHERE date = ? AND signal IN ('EXTREME','HIGH')", (latest,)
        ).fetchone()[0]
        last_log = c.execute(
            "SELECT date, status, rows_inserted, started_at, completed_at "
            "FROM ingestion_log_ua ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return {
            "latest_date": latest,
            "ticker_count": ticker_count,
            "extreme_count": ext,
            "high_count": high,
            "last_ingestion": row_dicts([last_log])[0] if last_log else None,
        }


def get_ua_latest() -> dict:
    with db_conn() as c:
        if not table_exists(c, "unusual_activity"):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        rows = row_dicts(c.execute("""
            SELECT date, ticker, activity_type, call_put, expiry, strike,
                   volume, open_interest, voi_ratio, notional_usd, iv_pct,
                   price, avg_vol_20d, vol_ratio, severity_score, signal
            FROM unusual_activity
            WHERE date = ?
            ORDER BY severity_score DESC, ticker
        """, (latest,)))
        return {"latest_date": latest, "rows": rows}


def get_ua_signals() -> dict:
    with db_conn() as c:
        if not table_exists(c, "unusual_activity"):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        rows = row_dicts(c.execute("""
            SELECT ticker, activity_type, call_put, expiry, strike,
                   notional_usd, severity_score, signal
            FROM unusual_activity
            WHERE date = ? AND signal IN ('EXTREME', 'HIGH')
            ORDER BY severity_score DESC
        """, (latest,)))
        return {"latest_date": latest, "rows": rows}


def get_ua_history(ticker: str, limit: int = 100) -> dict:
    with db_conn() as c:
        if not table_exists(c, "unusual_activity"):
            return {"ticker": ticker.upper(), "rows": []}
        rows = row_dicts(c.execute("""
            SELECT date, activity_type, call_put, expiry, strike,
                   volume, voi_ratio, notional_usd, iv_pct, price,
                   vol_ratio, severity_score, signal
            FROM (SELECT * FROM unusual_activity WHERE ticker = ?
                  ORDER BY date DESC LIMIT ?)
            ORDER BY date ASC
        """, (ticker.upper(), limit)))
        return {"ticker": ticker.upper(), "rows": rows}

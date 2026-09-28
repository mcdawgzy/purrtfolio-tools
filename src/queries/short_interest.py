"""FINRA short interest."""
from __future__ import annotations

from ..database import db_conn, row_dicts


# ---------------------------------------------------------------------------
# Short Interest
# ---------------------------------------------------------------------------
def get_si_meta() -> dict:
    """Top-level short interest info: latest settlement date, coverage stats, categories."""
    with db_conn() as c:
        latest = c.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]
        total = c.execute(
            "SELECT SUM(current_short) AS total_short, COUNT(*) AS count "
            "FROM short_interest WHERE settlement_date = ?",
            (latest,),  # NULL when the table is empty -> matches nothing
        ).fetchone()
        categories = [r[0] for r in c.execute(
            "SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()]
        periods = row_dicts(c.execute(
            "SELECT DISTINCT settlement_date FROM short_interest "
            "ORDER BY settlement_date DESC LIMIT 12"
        ))
        return {
            "latest_settlement": latest,
            "total_short_interest": total[0] if total and total[0] else 0,
            "ticker_count": total[1] if total and total[1] else 0,
            "categories": categories,
            "periods": [p["settlement_date"] for p in periods],
        }


def search_si_tickers(query: str, limit: int = 30) -> list[dict]:
    """Search tickers by symbol or name within the short interest watchlist."""
    with db_conn() as c:
        rows = c.execute("""
            SELECT t.ticker, COALESCE(t.name, t.ticker) AS name, t.category, t.exchange,
                   m.latest_short, m.latest_dtc, m.latest_change_pct,
                   t.free_float_shares
            FROM tickers t
            LEFT JOIN ticker_short_meta m ON m.symbol = t.ticker
            WHERE (t.ticker LIKE ? OR t.name LIKE ?)
              AND t.category IS NOT NULL
            ORDER BY CASE WHEN t.ticker LIKE ? THEN 0 ELSE 1 END,
                     m.latest_short DESC NULLS LAST
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"{query.upper()}%", limit)).fetchall()
        return row_dicts(rows)


def get_si_latest(min_short: int = 1_000_000, limit: int = 100) -> list[dict]:
    """Latest short interest snapshot for all tracked tickers, sorted by short size.

    Returns company name from the tickers table (enriched from FINRA issue_name).
    Also includes free_float_shares so the frontend can compute % of free float
    (current_short / free_float_shares * 100).
    """
    with db_conn() as c:
        rows = c.execute("""
            SELECT si.symbol,
                   COALESCE(t.name, si.issue_name) AS name,
                   t.category, t.exchange,
                   si.current_short, si.previous_short, si.avg_daily_volume,
                   si.days_to_cover, si.change_pct, si.change_abs, si.settlement_date,
                   t.free_float_shares
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.current_short >= ?
            ORDER BY si.current_short DESC
            LIMIT ?
        """, (min_short, limit)).fetchall()
        return row_dicts(rows)


def get_si_ticker(symbol: str) -> dict | None:
    """All short interest history for a single ticker.

    Returns the company name from the tickers table (enriched from FINRA
    issue_name). Includes free_float_shares and shares_outstanding for
    computing % of free float.
    """
    symbol = symbol.upper().strip()
    with db_conn() as c:
        rows = c.execute("""
            SELECT si.symbol,
                   COALESCE(t.name, si.issue_name) AS name,
                   t.category, t.exchange, t.industry,
                   si.settlement_date, si.current_short, si.previous_short,
                   si.avg_daily_volume, si.days_to_cover, si.change_pct,
                   si.change_abs, si.revision_flag, si.stock_split_flag,
                   t.free_float_shares, t.shares_outstanding
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.symbol = ?
            ORDER BY si.settlement_date DESC
        """, (symbol,)).fetchall()
        if not rows:
            return None
        rows = row_dicts(rows)
        # Compute % of free float for the latest period
        float_shares = rows[0].get("free_float_shares")
        pct_free_float = None
        if float_shares and float_shares > 0 and rows[0].get("current_short"):
            pct_free_float = round(rows[0]["current_short"] * 100.0 / float_shares, 2)
        return {
            "symbol": symbol,
            "name": rows[0]["name"],
            "category": rows[0]["category"],
            "exchange": rows[0]["exchange"],
            "industry": rows[0]["industry"],
            "free_float_shares": float_shares,
            "shares_outstanding": rows[0].get("shares_outstanding"),
            "pct_free_float": pct_free_float,
            "history": rows,
        }


def get_si_signals() -> dict:
    """Short interest signal sets for the latest settlement date."""
    with db_conn() as c:
        latest = c.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]
        if not latest:
            return {"latest_settlement": None, "spikes": [], "high_dtc": [],
                    "largest": [], "covering": [], "new_shorts": []}

        def q(sql, params, limit=50):
            return row_dicts(c.execute(sql + " LIMIT ?", (*params, limit)))

        spikes = q("""
            SELECT si.symbol, COALESCE(t.name, si.issue_name) AS name,
                   si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume,
                   t.free_float_shares AS free_float_shares
            FROM short_interest si JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ? AND si.change_pct >= 50 AND si.current_short >= 1000000
            ORDER BY si.change_pct DESC
        """, (latest,))

        high_dtc = q("""
            SELECT si.symbol, COALESCE(t.name, si.issue_name) AS name, si.current_short, si.days_to_cover,
                   si.avg_daily_volume, si.change_pct, t.free_float_shares AS free_float_shares
            FROM short_interest si JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ? AND si.days_to_cover >= 10 AND si.current_short >= 1000000
            ORDER BY si.days_to_cover DESC
        """, (latest,))

        largest = q("""
            SELECT si.symbol, COALESCE(t.name, si.issue_name) AS name, si.current_short, si.days_to_cover,
                   si.change_pct, t.free_float_shares AS free_float_shares
            FROM short_interest si JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ? AND si.current_short >= 1000000
            ORDER BY si.current_short DESC
        """, (latest,))

        covering = q("""
            SELECT si.symbol, COALESCE(t.name, si.issue_name) AS name, si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, t.free_float_shares AS free_float_shares
            FROM short_interest si JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ? AND si.change_pct <= -30 AND si.current_short >= 1000000
            ORDER BY si.change_pct ASC
        """, (latest,))

        new_shorts = q("""
            SELECT si.symbol, COALESCE(t.name, si.issue_name) AS name, si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, t.free_float_shares AS free_float_shares
            FROM short_interest si JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ? AND si.previous_short > 0
              AND si.current_short >= si.previous_short * 5 AND si.current_short >= 1000000
            ORDER BY (si.current_short * 1.0 / si.previous_short) DESC
        """, (latest,))

        # Compute pct_of_free_float for each signal set
        for rows in (spikes, high_dtc, largest, covering, new_shorts):
            for r in rows:
                ff = r.get("free_float_shares")
                cs = r.get("current_short")
                r["pct_of_free_float"] = round(cs * 100.0 / ff, 2) if ff and ff > 0 and cs else None

        return {
            "latest_settlement": latest,
            "spikes": spikes,
            "high_dtc": high_dtc,
            "largest": largest,
            "covering": covering,
            "new_shorts": new_shorts,
        }

"""
SQLite query layer for the 13F web dashboard.

Reads from the unified purrtfolio.db (canonical store for both 13F + Short Interest).
All functions are read-only. SQLite is opened in URI mode for read-only + immutable
so concurrent reads are safe and won't block the write cron jobs.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

# Default to the user's home purrtfolio.db. Override with PURRTFOLIO_DB env var.
_DEFAULT_DB = Path.home() / "purrtfolio.db"


def get_db_path() -> Path:
    import os
    p = os.environ.get("PURRTFOLIO_DB")
    return Path(p) if p else _DEFAULT_DB


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Read-only connection. Use as: with db_conn() as c: c.execute(...)"""
    path = get_db_path()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    # Open read-only + immutable (no locking, no write contention with cron jobs)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_dicts(cur_or_rows) -> list[dict[str, Any]]:
    """Accept either a Cursor (still pending fetchall) or an iterable of Rows."""
    rows = cur_or_rows
    if hasattr(rows, "fetchall"):
        rows = rows.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
def get_meta() -> dict:
    """Top-level site info: row counts, quarters available, last update."""
    with db_conn() as c:
        counts = {
            "funds": c.execute("SELECT COUNT(*) FROM funds").fetchone()[0],
            "filings": c.execute("SELECT COUNT(*) FROM filings_13f").fetchone()[0],
            "holdings": c.execute("SELECT COUNT(*) FROM holdings_13f").fetchone()[0],
            "changes": c.execute("SELECT COUNT(*) FROM holding_changes_13f").fetchone()[0],
            "unique_tickers": c.execute(
                "SELECT COUNT(DISTINCT ticker) FROM holdings_13f "
                "WHERE ticker IS NOT NULL AND ticker != ''"
            ).fetchone()[0],
        }
        quarters = _row_dicts(c.execute("""
            SELECT report_period, COUNT(DISTINCT fund_cik) as funds_filing,
                   SUM(CASE WHEN has_infotable=1 THEN total_value_usd ELSE 0 END) as total_aum_usd
            FROM filings_13f
            GROUP BY report_period ORDER BY report_period DESC
        """))
        last_update = c.execute(
            "SELECT MAX(MAX(created_at, '')) FROM "
            "(SELECT MAX(created_at) as created_at FROM filings_13f "
            " UNION ALL SELECT MAX(created_at) FROM holdings_13f "
            " UNION ALL SELECT MAX(created_at) FROM holding_changes_13f)"
        ).fetchone()[0]
        return {
            "counts": counts,
            "quarters": quarters,
            "last_update": last_update,
        }


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------
def list_funds() -> list[dict]:
    """All 27 funds with strategy + latest filing's AUM."""
    with db_conn() as c:
        rows = c.execute("""
                    SELECT
                        f.cik, f.name, f.strategy, f.aum_estimate, f.is_active,
                        fl.report_period AS latest_period,
                        fl.total_value_usd AS latest_aum_usd,
                        fl.total_holdings AS latest_holdings_count
                    FROM funds f
                    LEFT JOIN filings_13f fl ON fl.accession_number = (
                        SELECT accession_number FROM filings_13f
                        WHERE fund_cik = f.cik AND has_infotable = 1
                        ORDER BY report_period DESC LIMIT 1
                    )
                    WHERE f.is_active = 1
                    ORDER BY fl.total_value_usd DESC NULLS LAST, f.name
                """).fetchall()
        return _row_dicts(rows)


def get_fund(cik: str) -> dict | None:
    """Single fund detail."""
    with db_conn() as c:
        row = c.execute("""
            SELECT cik, name, strategy, aum_estimate, is_active, notes, created_at
            FROM funds WHERE cik = ?
        """, (cik,)).fetchone()
        if not row:
            return None
        fund = dict(row)
        # Filings history
        fund["filings"] = _row_dicts(c.execute("""
            SELECT accession_number, report_period, filing_date, submission_type,
                   total_value_usd, total_holdings, has_infotable
            FROM filings_13f WHERE fund_cik = ?
            ORDER BY report_period DESC
        """, (cik,)))
        return fund


# ---------------------------------------------------------------------------
# Holdings (latest quarter per fund)
# ---------------------------------------------------------------------------
def get_fund_holdings(
    cik: str,
    *,
    quarter: str | None = None,
    sort_by: str = "value",
    sort_dir: str = "desc",
    limit: int = 500,
    offset: int = 0,
    min_value: int | None = None,
    put_call: str = "",
    ticker_filter: str | None = None,
) -> dict:
    """Holdings for a fund in a given quarter (defaults to latest)."""
    sort_col = {
        "value": "market_value_usd",
        "shares": "shares",
        "ticker": "ticker",
        "change": "share_change",
        "cusip": "cusip",
    }.get(sort_by, "market_value_usd")
    sort_dir_sql = "DESC" if sort_dir.lower() != "asc" else "ASC"
    # NULL/empty tickers sort last regardless of direction
    nulls_last = "NULLS LAST" if sort_dir_sql == "DESC" else "NULLS FIRST"

    with db_conn() as c:
        # Resolve quarter
        if quarter:
            q = quarter
        else:
            r = c.execute("""
                SELECT report_period FROM filings_13f
                WHERE fund_cik = ? AND has_infotable = 1
                ORDER BY report_period DESC LIMIT 1
            """, (cik,)).fetchone()
            if not r:
                return {"holdings": [], "total": 0, "quarter": None}
            q = r[0]

        params: list[Any] = [cik, q, put_call]
        where = ["h.fund_cik = ?", "h.report_period = ?", "h.put_call = ?"]
        if min_value is not None:
            where.append("h.market_value_usd >= ?")
            params.append(min_value)
        if ticker_filter:
            where.append("(h.ticker LIKE ? OR h.issuer_name LIKE ?)")
            like = f"%{ticker_filter}%"
            params.extend([like, like])

        where_sql = " AND ".join(where)
        total = c.execute(
            f"SELECT COUNT(*) FROM holdings_13f h WHERE {where_sql}", params
        ).fetchone()[0]

        sql = f"""
            SELECT h.cusip, h.ticker, h.issuer_name, h.shares, h.share_type,
                   h.market_value_usd, h.put_call, h.title_of_class
            FROM holdings_13f h
            WHERE {where_sql}
            ORDER BY {sort_col} {sort_dir_sql} {nulls_last}, h.cusip
            LIMIT ? OFFSET ?
        """
        rows = c.execute(sql, [*params, limit, offset]).fetchall()
        return {
            "quarter": q,
            "cik": cik,
            "total": total,
            "limit": limit,
            "offset": offset,
            "holdings": _row_dicts(rows),
        }


# ---------------------------------------------------------------------------
# QoQ changes
# ---------------------------------------------------------------------------
def get_fund_changes(
    cik: str,
    *,
    quarter: str | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
    min_abs_value: int | None = None,
) -> dict:
    """QoQ changes for a fund in a given quarter."""
    with db_conn() as c:
        if quarter:
            q = quarter
        else:
            r = c.execute("""
                SELECT curr_report_period FROM holding_changes_13f
                WHERE fund_cik = ?
                ORDER BY curr_report_period DESC LIMIT 1
            """, (cik,)).fetchone()
            if not r:
                return {"changes": [], "total": 0, "quarter": None}
            q = r[0]

        params: list[Any] = [cik, q]
        where = ["hc.fund_cik = ?", "hc.curr_report_period = ?"]
        if status:
            where.append("hc.status = ?")
            params.append(status)
        if min_abs_value is not None:
            where.append("ABS(hc.value_change_usd) >= ?")
            params.append(min_abs_value)

        where_sql = " AND ".join(where)
        total = c.execute(
            f"SELECT COUNT(*) FROM holding_changes_13f hc WHERE {where_sql}", params
        ).fetchone()[0]

        sql = f"""
            SELECT hc.cusip, hc.ticker, hc.issuer_name,
                   hc.prev_report_period, hc.curr_report_period,
                   hc.prev_shares, hc.curr_shares, hc.share_change, hc.share_change_pct,
                   hc.prev_value_usd, hc.curr_value_usd,
                   hc.value_change_usd, hc.value_change_pct,
                   hc.status
            FROM holding_changes_13f hc
            WHERE {where_sql}
            ORDER BY ABS(hc.value_change_usd) DESC
            LIMIT ? OFFSET ?
        """
        rows = c.execute(sql, [*params, limit, offset]).fetchall()
        return {
            "quarter": q,
            "cik": cik,
            "total": total,
            "limit": limit,
            "offset": offset,
            "changes": _row_dicts(rows),
        }


# ---------------------------------------------------------------------------
# Cross-fund ticker view
# ---------------------------------------------------------------------------
def get_ticker_holders(ticker: str) -> dict:
    """Who holds this ticker, across all funds and recent quarters."""
    ticker = ticker.upper().strip()
    with db_conn() as c:
        # Per-fund summary across all available quarters
        rows = c.execute("""
            SELECT
                f.cik, f.name, f.strategy,
                fl.report_period, h.shares, h.market_value_usd,
                h.cusip, h.issuer_name,
                hc.status, hc.share_change, hc.value_change_usd, hc.share_change_pct,
                hc.prev_report_period, hc.curr_report_period
            FROM holdings_13f h
            JOIN filings_13f fl ON h.filing_accession = fl.accession_number
            JOIN funds f ON fl.fund_cik = f.cik
            LEFT JOIN holding_changes_13f hc
                ON hc.fund_cik = fl.fund_cik
                AND hc.cusip = h.cusip
                AND hc.curr_report_period = fl.report_period
            WHERE h.ticker = ?
            ORDER BY fl.report_period DESC, h.market_value_usd DESC
        """, (ticker,)).fetchall()

        if not rows:
            return {"ticker": ticker, "found": False, "holders": [], "history": []}

        # Aggregate per fund (latest holding)
        per_fund: dict[str, dict] = {}
        for r in rows:
            key = r["cik"]
            if key not in per_fund:
                per_fund[key] = dict(r)
        holders = sorted(
            per_fund.values(),
            key=lambda x: x["market_value_usd"],
            reverse=True,
        )
        # Quarter-by-quarter history (each quarter, total value across all funds)
        history_rows = c.execute("""
            SELECT report_period,
                   COUNT(DISTINCT fund_cik) as holders,
                   SUM(market_value_usd) as total_value_usd,
                   SUM(shares) as total_shares
            FROM holdings_13f
            WHERE ticker = ?
            GROUP BY report_period ORDER BY report_period
        """, (ticker,)).fetchall()

        return {
            "ticker": ticker,
            "found": True,
            "issuer_name": rows[0]["issuer_name"],
            "current_holders": len(holders),
            "total_current_value_usd": sum(h["market_value_usd"] for h in holders),
            "holders": holders,
            "history": _row_dicts(history_rows),
        }


# ---------------------------------------------------------------------------
# Consensus / aggregate views
# ---------------------------------------------------------------------------
def get_consensus(
    *,
    quarter: str | None = None,
    min_funds: int = 2,
    limit: int = 100,
) -> dict:
    """Tickers with cross-fund consensus moves in a quarter.

    For each ticker held by ≥N funds in the target quarter, compute the
    quarter-pair-over-quarter delta: aggregated value in `quarter` minus
    aggregated value in the immediately-prior quarter we have data for.
    Uses holding_changes_13f (already pair-aware and per-fund) instead of
    a raw join, so new/delisted tickers don't pollute the totals.
    """
    with db_conn() as c:
        if not quarter:
            r = c.execute(
                "SELECT report_period FROM filings_13f "
                "WHERE has_infotable=1 ORDER BY report_period DESC LIMIT 1"
            ).fetchone()
            if not r:
                return {"quarter": None, "min_funds": min_funds, "buys": [], "sells": []}
            quarter = r[0]

        # Sum value_change_usd per ticker across all funds for this quarter pair.
        # Already excludes NEW (= positive value_change_usd from $0) and
        # CLOSED (= negative value_change_usd to $0), so net captures only
        # incremental moves on continuing positions.
        rows = c.execute("""
            SELECT ticker,
                   SUM(value_change_usd) as net_change_usd,
                   COUNT(DISTINCT fund_cik) as funds_moving,
                   SUM(CASE WHEN status='NEW' THEN 1 ELSE 0 END) as funds_new,
                   SUM(CASE WHEN status='INCREASED' THEN 1 ELSE 0 END) as funds_increased,
                   SUM(CASE WHEN status='DECREASED' THEN 1 ELSE 0 END) as funds_decreased,
                   SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) as funds_closed
            FROM holding_changes_13f
            WHERE curr_report_period = ?
              AND ticker != '' AND ticker IS NOT NULL
            GROUP BY ticker
            HAVING COUNT(DISTINCT fund_cik) >= ?
            ORDER BY net_change_usd DESC
        """, (quarter, min_funds)).fetchall()

        all_rows = _row_dicts(rows)
        return {
            "quarter": quarter,
            "min_funds": min_funds,
            "buys": [r for r in all_rows if r["net_change_usd"] > 0][:limit],
            "sells": [r for r in all_rows if r["net_change_usd"] < 0]
                      [::-1][:limit],
        }


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------
def list_sectors() -> list[dict]:
    """Sector aggregation for the latest quarter (if sector data is populated).

    Note: our tickers.sector column is currently NULL — we'd need to enrich it
    via GICS mapping before this becomes meaningful. Endpoint kept for forward
    compatibility."""
    with db_conn() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM tickers WHERE sector IS NOT NULL AND sector != ''"
        ).fetchone()[0]
        if n == 0:
            return []
        rows = c.execute("""
            SELECT t.sector,
                   COUNT(DISTINCT h.fund_cik) as holders,
                   SUM(h.market_value_usd) as total_value_usd,
                   COUNT(*) as positions
            FROM holdings_13f h
            JOIN filings_13f fl ON h.filing_accession = fl.accession_number
            JOIN tickers t ON h.ticker = t.ticker
            WHERE fl.report_period = (
                SELECT MAX(report_period) FROM filings_13f WHERE has_infotable=1
            )
              AND t.sector IS NOT NULL AND t.sector != ''
            GROUP BY t.sector ORDER BY total_value_usd DESC
        """).fetchall()
        return _row_dicts(rows)


# ---------------------------------------------------------------------------
# Health (lightweight)
# ---------------------------------------------------------------------------
def health() -> dict:
    with db_conn() as c:
        ok = c.execute("SELECT 1").fetchone() is not None
    return {"ok": ok, "db_path": str(get_db_path())}
"""SQLite query layer for the 13F web dashboard.

Reads from the unified purrtfolio.db (canonical store for both 13F + Short Interest).
All functions are read-only. SQLite is opened in URI mode for read-only + immutable
so concurrent reads are safe and won't block the write cron jobs.

On startup (in production on Render), if DB is not found locally, download
from GitHub Release asset (db-vYYYY-MM-DD).
"""
from __future__ import annotations

import logging
import os
import json
import sqlite3
import urllib.request
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

# Default to the user's home purrtfolio.db. Override with PURRTFOLIO_DB env var.
_DEFAULT_DB = Path.home() / "purrtfolio.db"

# GitHub Release asset URL for production DB
_RELEASE_ASSET = "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-11b/purrtfolio.db"

logger = logging.getLogger(__name__)


def _download_db_if_needed(db_path: Path) -> Path:
    """Download DB from GitHub Release if it doesn't exist locally."""
    if db_path.exists():
        return db_path
    logger.info(f"DB not found at {db_path}, downloading from {_RELEASE_ASSET}...")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(_RELEASE_ASSET, db_path)
    logger.info(f"Downloaded DB ({db_path.stat().st_size / 1e6:.1f}MB)")
    return db_path


def get_db_path() -> Path:
    import os
    p = os.environ.get("PURRTFOLIO_DB")
    return Path(p) if p else _DEFAULT_DB


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Read-only connection. Use as: with db_conn() as c: c.execute(...)"""
    path = _download_db_if_needed(get_db_path())
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

        # Latest short interest for this ticker (may be None if not in SI watchlist)
        latest_si_row = c.execute("""
            SELECT settlement_date, current_short, previous_short,
                   avg_daily_volume, days_to_cover, change_pct, change_abs
            FROM short_interest
            WHERE symbol = ?
            ORDER BY settlement_date DESC
            LIMIT 1
        """, (ticker,)).fetchone()
        latest_si = dict(latest_si_row) if latest_si_row else None

        # Short interest meta summary (peak, avg DTC, etc.)
        si_meta_row = c.execute("""
            SELECT latest_settlement, latest_short, peak_short,
                   avg_short_12m, peak_dtc,
                   latest_dtc, peak_short_date, updated_at
            FROM ticker_short_meta
            WHERE symbol = ?
        """, (ticker,)).fetchone()
        si_meta = dict(si_meta_row) if si_meta_row else None

        if not rows:
            return {
                "ticker": ticker,
                "found": False,
                "holders": [],
                "history": [],
                "latest_si": latest_si,
                "si_meta": si_meta,
            }

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
            "latest_si": latest_si,
            "si_meta": si_meta,
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
    """Sector rotation between the two most recent report periods.

    Returns one row per sector with prev/curr totals, value delta, and
    holder/position changes. Replaces the old single-quarter allocation view
    that didn't show rotation."""
    with db_conn() as c:
        rows = _row_dicts(c.execute("""
            WITH two_periods AS (
                SELECT report_period FROM filings_13f
                WHERE has_infotable=1
                GROUP BY report_period ORDER BY report_period DESC LIMIT 2
            ),
            periods AS (
                SELECT (SELECT report_period FROM two_periods ORDER BY report_period DESC LIMIT 1) AS curr_q,
                       (SELECT report_period FROM two_periods ORDER BY report_period ASC  LIMIT 1) AS prev_q
            ),
            prev_agg AS (
                SELECT t.sector,
                       COUNT(DISTINCT h.fund_cik) AS holders,
                       COUNT(*) AS positions,
                       SUM(h.market_value_usd) AS total_value_usd
                FROM holdings_13f h
                JOIN tickers t ON h.ticker = t.ticker
                CROSS JOIN periods p
                WHERE h.report_period = p.prev_q
                  AND t.sector IS NOT NULL AND t.sector != ''
                  AND t.sector != 'ETFs & Funds'
                  AND h.put_call = ''
                GROUP BY t.sector
            ),
            curr_agg AS (
                SELECT t.sector,
                       COUNT(DISTINCT h.fund_cik) AS holders,
                       COUNT(*) AS positions,
                       SUM(h.market_value_usd) AS total_value_usd
                FROM holdings_13f h
                JOIN tickers t ON h.ticker = t.ticker
                CROSS JOIN periods p
                WHERE h.report_period = p.curr_q
                  AND t.sector IS NOT NULL AND t.sector != ''
                  AND t.sector != 'ETFs & Funds'
                  AND h.put_call = ''
                GROUP BY t.sector
            )
            SELECT
                COALESCE(c.sector, pr.sector) AS sector,
                pr.total_value_usd AS prev_value_usd,
                c.total_value_usd AS curr_value_usd,
                COALESCE(c.total_value_usd, 0) - COALESCE(pr.total_value_usd, 0) AS value_change_usd,
                pr.holders AS prev_holders,
                c.holders AS curr_holders,
                COALESCE(c.holders, 0) - COALESCE(pr.holders, 0) AS holder_change,
                pr.positions AS prev_positions,
                c.positions AS curr_positions,
                COALESCE(c.positions, 0) - COALESCE(pr.positions, 0) AS position_change
            FROM prev_agg pr
            FULL OUTER JOIN curr_agg c ON pr.sector = c.sector
            ORDER BY ABS(value_change_usd) DESC NULLS LAST
        """))
        return rows


def get_sector_periods() -> dict:
    """Return the two report periods backing the sector rotation view
    so the frontend can label the comparison (e.g. '2026-03-31 -> 2026-06-30')."""
    with db_conn() as c:
        period_rows = _row_dicts(c.execute(
            "SELECT report_period FROM filings_13f "
            "WHERE has_infotable=1 "
            "GROUP BY report_period ORDER BY report_period DESC LIMIT 2"
        ))
        if len(period_rows) >= 2:
            return {"prev_q": period_rows[1]["report_period"], "curr_q": period_rows[0]["report_period"]}
        if len(period_rows) == 1:
            return {"prev_q": None, "curr_q": period_rows[0]["report_period"]}
        return {"prev_q": None, "curr_q": None}


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
            (latest,) if latest else ()
        ).fetchone()
        categories = [r[0] for r in c.execute(
            "SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()]
        periods = _row_dicts(c.execute(
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
        return _row_dicts(rows)


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
        return _row_dicts(rows)


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
        rows = _row_dicts(rows)
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
            return _row_dicts(c.execute(sql + " LIMIT ?", (*params, limit)))

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

        return {
            "latest_settlement": latest,
            "spikes": spikes,
            "high_dtc": high_dtc,
            "largest": largest,
            "covering": covering,
            "new_shorts": new_shorts,
        }


# ---------------------------------------------------------------------------
# Market Snapshot
# ---------------------------------------------------------------------------
def get_snapshot_dir() -> Path:
    """Directory where the macro pipeline saves its output (PNG + JSON).

    On Render (production), the macro output directory won't exist — the
    macro pipeline runs locally and copies its output into static/snapshots/
    via the cron job. On local dev, the pipeline writes to
    snapshots/macro/output/ directly.
    """
    # Prefer a SNAPSHOT_OUTPUT_DIR env var (production), fall back to the local
    # snapshots/macro/output directory relative to the project.
    env_dir = os.environ.get("SNAPSHOT_OUTPUT_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_absolute():
            return p
        return Path.cwd() / "13f-scanner-web" / "snapshots" / "macro" / "output"
    # Local development: macro pipeline output
    local_dir = Path(__file__).resolve().parent.parent / "snapshots" / "macro" / "output"
    if local_dir.exists():
        return local_dir
    # Fallback: snapshots copied into static/ by the cron pipeline (Render)
    return Path(__file__).resolve().parent.parent / "static" / "snapshots"


def _find_latest_report_json(out_dir: Path) -> Path | None:
    """Find the latest market_report JSON in a directory.

    Checks for both dated names (market_report_YYYYMMDD.json) and
    the latest symlink/copy (market_report_latest.json).
    """
    import glob
    # Prefer dated files (newest first), then fall back to _latest
    files = sorted(glob.glob(str(out_dir / "market_report_*.json")), reverse=True)
    if files:
        return Path(files[0])
    return None


def _resolve_snapshot_filenames(out_dir: Path, date_str: str) -> tuple[str, str]:
    """Return (png_filename, caption) for a given date_str, trying both
    dated and '_latest' naming conventions.

    Returns (png_filename or None, caption or "").
    """
    # Try dated filenames first
    png_dated = out_dir / f"market_snapshot_{date_str}.png"
    png_latest = out_dir / "market_snapshot.png"
    caption_dated = out_dir / f"market_caption_{date_str}.txt"
    caption_latest = out_dir / "market_caption_latest.txt"

    png_filename = None
    if png_dated.exists():
        png_filename = png_dated.name
    elif png_latest.exists():
        png_filename = png_latest.name

    caption = ""
    if caption_dated.exists():
        caption = caption_dated.read_text().strip()
    elif caption_latest.exists():
        caption = caption_latest.read_text().strip()

    return png_filename, caption


def get_latest_snapshot() -> dict | None:
    """Read the latest macro market snapshot report JSON.

    Returns a dict with date_str, png_filename, caption, and top_movers
    (the 3 biggest movers by absolute pct_change, with their driver narratives).
    Returns None if no snapshot is available yet.
    """
    out_dir = get_snapshot_dir()
    if not out_dir.exists():
        return None

    json_path = _find_latest_report_json(out_dir)
    if not json_path:
        return None

    with open(json_path, "r") as f:
        report = json.load(f)

    date_str = json_path.stem.replace("market_report_", "").replace("_latest", "")
    png_filename, caption = _resolve_snapshot_filenames(out_dir, date_str)

    # Extract top 3 movers by absolute pct_change
    data_rows = [r for r in report["rows"] if r.get("pct_change") is not None]
    top3 = sorted(data_rows, key=lambda x: abs(x["pct_change"]), reverse=True)[:3]

    top_movers = [
        {
            "name": r["name"],
            "pct_change": r["pct_change"],
            "driver": r["driver"],
            "level_move": r["level_move"],
        }
        for r in top3
    ]

    return {
        "date_str": date_str,
        "png_filename": png_filename,
        "caption": caption,
        "top_movers": top_movers,
        "timestamp": report.get("timestamp", ""),
    }


def get_snapshot_by_date(date_str: str) -> dict | None:
    """Read a specific snapshot by date (YYYYMMDD)."""
    out_dir = get_snapshot_dir()
    json_path = out_dir / f"market_report_{date_str}.json"
    if not json_path.exists():
        return None

    with open(json_path, "r") as f:
        report = json.load(f)

    png_filename, caption = _resolve_snapshot_filenames(out_dir, date_str)

    data_rows = [r for r in report["rows"] if r.get("pct_change") is not None]
    top3 = sorted(data_rows, key=lambda x: abs(x["pct_change"]), reverse=True)[:3]

    top_movers = [
        {
            "name": r["name"],
            "pct_change": r["pct_change"],
            "driver": r["driver"],
            "level_move": r["level_move"],
        }
        for r in top3
    ]

    return {
        "date_str": date_str,
        "png_filename": png_filename,
        "caption": caption,
        "top_movers": top_movers,
        "timestamp": report.get("timestamp", ""),
    }


# ---------------------------------------------------------------------------
# Health (lightweight)
# ---------------------------------------------------------------------------
def health() -> dict:
    with db_conn() as c:
        ok = c.execute("SELECT 1").fetchone() is not None
        si_latest = c.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]
    return {"ok": ok, "db_path": str(get_db_path()), "si_latest_settlement": si_latest}
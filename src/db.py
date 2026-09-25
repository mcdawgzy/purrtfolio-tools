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
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

# Default to the user's home purrtfolio.db. Override with PURRTFOLIO_DB env var.
_DEFAULT_DB = Path.home() / "purrtfolio.db"

# GitHub Release asset URL for production DB
_RELEASE_ASSET = "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-25/purrtfolio.db.gz"

logger = logging.getLogger(__name__)


def _download_with_redirect(url: str, dest: str) -> None:
    """Download a URL to dest, following HTTP redirects.

    Tries curl first (available on Render Linux), falls back to
    urllib with a proper HTTPRedirectHandler.
    """
    import subprocess, shutil as _sh
    curl = _sh.which("curl")
    if curl:
        result = subprocess.run(
            [curl, "-fSL", "-o", dest, url],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"curl failed (exit {result.returncode}): "
                f"{result.stderr.decode()[:500]}"
            )
        return
    # Fallback: urllib with redirect handler
    import urllib.request as _ul
    opener = _ul.build_opener(_ul.HTTPRedirectHandler)
    with opener.open(url) as response, open(dest, "wb") as out:
        import shutil
        shutil.copyfileobj(response, out)


def _db_has_new_tables(db_path: Path) -> bool:
    """Check whether the existing DB contains the new scanner tables
    AND has actual data (not just empty schema from a partial build)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        names = {t[0] for t in tables}
        required = {"price_history", "price_momentum_signals", "corr_matrices"}
        if not required.issubset(names):
            return False
        # Verify the tables have data
        for tbl in required:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            conn.close()
            if count == 0:
                return False
        return True
    except Exception:
        return False


_db_validated_path: str | None = None

def _download_db_if_needed(db_path: Path) -> Path:
    """Download DB from GitHub Release if it doesn't exist locally.

    The release asset is gzip-compressed (purrtfolio.db.gz) to keep the
    download fast on Render's free tier. We decompress on the fly.

    Also re-downloads if the existing DB lacks the new tables (stale build).

    Caches the validation result per-process so we don't re-open 4 SQLite
    connections on every request just to verify the DB hasn't changed.
    """
    global _db_validated_path
    if _db_validated_path == str(db_path) and db_path.exists() and db_path.stat().st_size > 10_000_000:
        return db_path
    if db_path.exists() and _db_has_new_tables(db_path):
        _db_validated_path = str(db_path)
        return db_path
    logger.info(f"DB stale or missing at {db_path}, downloading fresh copy...")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Download the .gz file to a temp path, decompress, then swap
    gz_path = str(db_path) + ".gz.new"
    tmp_db = str(db_path) + ".new"
    _download_with_redirect(_RELEASE_ASSET, gz_path)
    logger.info(f"Downloaded ({os.path.getsize(gz_path) / 1e6:.1f}MB compressed)")

    # Decompress
    import gzip, shutil
    with gzip.open(gz_path, "rb") as f_in, open(tmp_db, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(gz_path)
    logger.info(f"Decompressed DB ({os.path.getsize(tmp_db) / 1e6:.1f}MB)")

    # Replace the old DB atomically
    if db_path.exists():
        os.chmod(db_path, 0o644)  # ensure writable
        os.remove(db_path)
    os.rename(tmp_db, db_path)
    logger.info(f"DB swapped to {db_path}")
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
# Factor Exposure (Style Drift) + Crowded Trades
# ---------------------------------------------------------------------------
# Reads from `ticker_factors` (populated by scanners/13f/enrich_factors.py)
# joined against the latest-quarter 13F holdings.  All exposure is
# portfolio-value-weighted: weight(ticker) = market_value_usd / total_AUM.
#
# Factor table columns: size_bucket, value_bucket, momentum_bucket
# (see enrich_factors.py for classification thresholds).
# ---------------------------------------------------------------------------
_DIMENSIONS = [
    ("size",          "size_bucket",      "Size (Market Cap)",
     ["Large", "Mid", "Small", "Unknown"]),
    ("value_growth",  "value_bucket",     "Value / Growth",
     ["Value", "Blend", "Growth", "Unknown"]),
    ("momentum",      "momentum_bucket",  "Momentum",
     ["Momentum", "Neutral", "Contrarian", "Unknown"]),
]


def _latest_quarter(conn) -> str | None:
    r = conn.execute(
        "SELECT MAX(report_period) FROM filings_13f WHERE has_infotable=1"
    ).fetchone()
    return r[0] if r else None


def _has_ticker_factors(conn) -> bool:
    """Gracefully degrade if the factor table isn't populated yet."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ticker_factors'"
    ).fetchone()
    return row is not None


def get_factor_meta() -> dict:
    """Latest quarter, AUM coverage, and enrichment status for the factors tab."""
    with db_conn() as c:
        if not _has_ticker_factors(c):
            return {"quarter": _latest_quarter(c), "coverage_pct": 0,
                    "total_aum_usd": 0, "covered_aum_usd": 0,
                    "classified_tickers": 0, "last_enrichment": None,
                    "ready": False}
        quarter = _latest_quarter(c)
        total_aum = c.execute(
            "SELECT SUM(market_value_usd) FROM holdings_13f "
            "WHERE report_period=? AND put_call=''", (quarter,)
        ).fetchone()[0] or 0
        covered = c.execute("""
            SELECT SUM(h.market_value_usd) AS covered
            FROM holdings_13f h JOIN ticker_factors tf ON h.ticker = tf.ticker
            WHERE h.report_period=?
        """, (quarter,)).fetchone()[0] or 0
        n = c.execute("SELECT COUNT(*) FROM ticker_factors").fetchone()[0]
        last = c.execute(
            "SELECT MAX(enriched_at) FROM ticker_factors"
        ).fetchone()[0]
        return {
            "quarter": quarter,
            "coverage_pct": round(covered / total_aum * 100, 1) if total_aum else 0,
            "total_aum_usd": total_aum,
            "covered_aum_usd": covered,
            "classified_tickers": n,
            "last_enrichment": last,
            "ready": True,
        }


def _factor_holdings(conn, quarter: str, pooled: bool) -> str:
    """SQL fragment returning per-ticker (and optionally per-fund) latest-quarter
    holdings joined to `tickers.name`.  When pooled=True the value is summed
    across all funds (for overall exposure).  When pooled=False, strategy is
    retained (for per-strategy exposure)."""
    if pooled:
        return f"""
            SELECT h.ticker, t.name, SUM(h.market_value_usd) AS mv
            FROM holdings_13f h
            JOIN tickers t ON h.ticker = t.ticker
            JOIN filings_13f fl ON h.filing_accession = fl.accession_number
            JOIN funds f ON fl.fund_cik = f.cik
            WHERE h.report_period = ?
              AND h.ticker IS NOT NULL AND h.ticker != '' AND h.put_call = ''
            GROUP BY h.ticker, t.name
        """, (quarter,)
    return f"""
        SELECT h.ticker, t.name, f.strategy, f.name AS fund_name, f.cik,
               SUM(h.market_value_usd) AS mv
        FROM holdings_13f h
        JOIN tickers t ON h.ticker = t.ticker
        JOIN filings_13f fl ON h.filing_accession = fl.accession_number
        JOIN funds f ON fl.fund_cik = f.cik
        WHERE h.report_period = ?
          AND h.ticker IS NOT NULL AND h.ticker != '' AND h.put_call = ''
        GROUP BY h.ticker, f.cik, f.strategy
    """, (quarter,)


def get_factor_exposure(quarter: str | None = None) -> dict:
    """Portfolio-value-weighted factor exposure for the latest 13F quarter.

    Returns overall (all-funds-pooled) breakdowns per dimension plus a
    per-strategy breakout, so the frontend can render bar charts and a
    strategy-comparison table.
    """
    with db_conn() as c:
        if not _has_ticker_factors(c):
            meta = get_factor_meta()
            return {"quarter": meta["quarter"], "coverage_pct": 0,
                    "total_aum_usd": 0, "covered_aum_usd": 0,
                    "classified_tickers": 0, "dimensions": [], "by_strategy": []}
        if not quarter:
            quarter = _latest_quarter(c)
            if not quarter:
                return {"quarter": None, "dimensions": [], "by_strategy": []}

        # overall pooled holdings (one row per ticker, value summed across funds)
        pooled_sql, pparams = _factor_holdings(c, quarter, pooled=True)
        pooled = c.execute(
            f"WITH hold AS ({pooled_sql}) "
            f"SELECT h.ticker, h.mv FROM hold h "
            f"JOIN ticker_factors tf ON h.ticker = tf.ticker",
            pparams,
        ).fetchall()

        pooled_total = sum(r[1] for r in pooled) or 0

        # per-strategy holdings (one row per ticker+fund)
        strat_sql, sparams = _factor_holdings(c, quarter, pooled=False)
        strat_rows = c.execute(
            f"WITH hold AS ({strat_sql}) "
            f"SELECT h.strategy, h.fund_name, h.cik, h.ticker, h.mv FROM hold h "
            f"JOIN ticker_factors tf ON h.ticker = tf.ticker",
            sparams,
        ).fetchall()
        # strategy totals
        strat_totals: dict[str, float] = {}
        for r in strat_rows:
            strat_totals[r[0]] = strat_totals.get(r[0], 0) + r[4]

        # ticker -> factor buckets + fund holders (reuse already-fetched rows)
        tf_map = {
            r[0]: {"size": r[1], "value_growth": r[2], "momentum": r[3]}
            for r in c.execute(
                "SELECT ticker, size_bucket, value_bucket, momentum_bucket FROM ticker_factors"
            ).fetchall()
        }
        # ticker -> set of fund ciks (overall holders count per bucket)
        ticker_ciks: dict[str, set] = {}
        for _s, _n, _cik, ticker, _mv in strat_rows:
            ticker_ciks.setdefault(ticker, set()).add(_cik)

        dimensions: list[dict] = []
        for key, col, label, order in _DIMENSIONS:
            # overall — pool all funds, group by factor bucket in Python
            bucket_vals: dict[str, float] = {}
            bucket_ticks: dict[str, int] = {}
            bucket_ciks: dict[str, set] = {}
            for ticker, mv in pooled:
                b = tf_map.get(ticker, {}).get(key) or "Unknown"
                bucket_vals[b] = bucket_vals.get(b, 0) + mv
                bucket_ticks[b] = bucket_ticks.get(b, 0) + 1
                bucket_ciks.setdefault(b, set()).update(ticker_ciks.get(ticker, set()))
            overall_list = []
            for b in order:
                v = bucket_vals.get(b, 0)
                overall_list.append({
                    "bucket": b, "value_usd": v,
                    "pct": round(v / pooled_total * 100, 1) if pooled_total else 0,
                    "tickers": bucket_ticks.get(b, 0),
                    "holders": len(bucket_ciks.get(b, set())),
                })

            # by strategy
            by_strat: list[dict] = []
            for strat in sorted(strat_totals):
                stot = strat_totals[strat]
                rows = c.execute(f"""
                    WITH hold AS ({strat_sql})
                    SELECT tf.{col} AS bucket, SUM(h.mv) AS value_usd,
                           COUNT(DISTINCT h.cik) AS holders
                    FROM hold h
                    JOIN ticker_factors tf ON h.ticker = tf.ticker
                    WHERE h.strategy = ?
                    GROUP BY tf.{col}
                """, (quarter, strat)).fetchall()
                breakdown = {b: 0 for b in order}
                for r in rows:
                    breakdown[r[0]] = round(r[1] / stot * 100, 1) if stot else 0
                by_strat.append({"strategy": strat, "aum_usd": stot, "breakdown": breakdown})

            dimensions.append({
                "key": key, "label": label, "buckets": order,
                "overall": overall_list, "by_strategy": by_strat,
            })

        total_aum = c.execute(
            "SELECT SUM(market_value_usd) FROM holdings_13f "
            "WHERE report_period=? AND put_call=''", (quarter,)
        ).fetchone()[0] or 0
        covered = c.execute("""
            SELECT SUM(h.market_value_usd) FROM holdings_13f h
            JOIN ticker_factors tf ON h.ticker = tf.ticker
            WHERE h.report_period=?
        """, (quarter,)).fetchone()[0] or 0
        return {
            "quarter": quarter,
            "coverage_pct": round(covered / total_aum * 100, 1) if total_aum else 0,
            "total_aum_usd": total_aum,
            "covered_aum_usd": covered,
            "classified_tickers": len(pooled),
            "dimensions": dimensions,
        }


def get_factor_ticker(ticker: str) -> dict | None:
    """Single-ticker factor classification + who holds it (latest quarter)."""
    ticker = ticker.upper().strip()
    with db_conn() as c:
        if not _has_ticker_factors(c):
            return None
        f = c.execute(
            "SELECT ticker, market_cap, pe_ratio, price_to_book, size_bucket, "
            "value_bucket, momentum_bucket, momentum_roc_20d, sector, enriched_at "
            "FROM ticker_factors WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not f:
            return None
        factor = dict(zip(["ticker", "market_cap", "pe_ratio", "price_to_book",
                           "size_bucket", "value_bucket", "momentum_bucket",
                           "momentum_roc_20d", "sector", "enriched_at"], f))
        quarter = _latest_quarter(c)
        holders = c.execute("""
            SELECT f.cik, f.name, f.strategy, fl.total_value_usd AS fund_aum,
                   h.market_value_usd AS position_value,
                   ROUND(h.market_value_usd * 100.0 / fl.total_value_usd, 2) AS pct_of_fund,
                   h.shares
            FROM holdings_13f h
            JOIN filings_13f fl ON h.filing_accession = fl.accession_number
            JOIN funds f ON fl.fund_cik = f.cik
            WHERE h.report_period = ? AND h.ticker = ?
            ORDER BY h.market_value_usd DESC
            LIMIT 30
        """, (quarter, ticker)).fetchall()
        factor["quarter"] = quarter
        factor["holders"] = [dict(zip(
            ["fund_cik", "fund_name", "strategy", "fund_aum", "position_value",
             "pct_of_fund", "shares"], r)) for r in holders]
        return factor


def get_crowded_trades(quarter: str | None = None, limit: int = 25) -> dict:
    """Most-crowded positions: held by the most funds + largest value +
    directional bias (net adders this quarter).  Pure 13F — no factor data."""
    with db_conn() as c:
        if not quarter:
            quarter = _latest_quarter(c)
            if not quarter:
                return {"quarter": None, "rows": []}
        rows = c.execute("""
            WITH hold AS (
                SELECT h.ticker, t.name, t.sector,
                       COUNT(DISTINCT fl.fund_cik) AS holders,
                       SUM(h.market_value_usd) AS total_value
                FROM holdings_13f h
                JOIN tickers t ON h.ticker = t.ticker
                JOIN filings_13f fl ON h.filing_accession = fl.accession_number
                WHERE h.report_period = ?
                  AND h.ticker != '' AND h.put_call = ''
                GROUP BY h.ticker, t.name, t.sector
            ),
            ch AS (
                SELECT ticker,
                       SUM(CASE WHEN status IN ('INCREASED','NEW') THEN 1 ELSE 0 END) AS funds_added,
                       SUM(CASE WHEN status IN ('DECREASED','CLOSED') THEN 1 ELSE 0 END) AS funds_removed
                FROM holding_changes_13f
                WHERE curr_report_period = ? AND ticker != ''
                GROUP BY ticker
            )
            SELECT h.ticker, h.name, h.sector, h.holders, h.total_value,
                   COALESCE(ch.funds_added, 0) AS funds_added,
                   COALESCE(ch.funds_removed, 0) AS funds_removed
            FROM hold h LEFT JOIN ch ON ch.ticker = h.ticker
            ORDER BY h.holders DESC, h.total_value DESC
            LIMIT ?
        """, (quarter, quarter, limit)).fetchall()
        return {
            "quarter": quarter,
            "rows": _row_dicts(rows),
        }


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


# ---------------------------------------------------------------------------
# Put/Call Ratio (CBOE)
# ---------------------------------------------------------------------------
_PCRIES = ("put_call_ratio", "put_call_latest")


def _pcr_table_exists(c) -> bool:
    """Check whether the put_call_ratio table is present in this DB."""
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='put_call_ratio'"
    ).fetchone() is not None


def get_pcr_meta() -> dict:
    """Top-level PCR info: latest date, series coverage, ingestion log."""
    with db_conn() as c:
        if not _pcr_table_exists(c):
            return {"latest_date": None, "periods": [], "series": [], "last_update": None}

        latest = c.execute("SELECT MAX(date) FROM put_call_ratio").fetchone()[0]
        periods = _row_dicts(c.execute(
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
        if not _pcr_table_exists(c):
            return {"latest_date": None, "rows": []}
        rows = _row_dicts(c.execute("""
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
        if not _pcr_table_exists(c):
            return {"series": series, "rows": []}
        rows = _row_dicts(c.execute("""
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
        if not _pcr_table_exists(c):
            return {"latest_date": None, "signals": []}
        latest = c.execute("SELECT MAX(date) FROM put_call_ratio").fetchone()[0]
        signals = _row_dicts(c.execute("""
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
def _iv_table_exists(c) -> bool:
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='iv_rank'"
    ).fetchone() is not None


def get_iv_meta() -> dict:
    """Metadata: latest date, ticker count, signal counts, last ingestion."""
    with db_conn() as c:
        if not _iv_table_exists(c):
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
            "last_ingestion": _row_dicts([last_log])[0] if last_log else None,
        }


def get_iv_latest() -> dict:
    with db_conn() as c:
        if not _iv_table_exists(c):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM iv_rank").fetchone()[0]
        rows = _row_dicts(c.execute("""
            SELECT ticker, date, iv, iv_rank, iv_pctile, days_52w,
                   iv_min_52w, iv_max_52w, iv_mean_52w, signal
            FROM iv_rank
            WHERE date = ?
            ORDER BY iv_rank DESC NULLS LAST, ticker
        """, (latest,)))
        return {"latest_date": latest, "rows": rows}


def get_iv_history(ticker: str, days: int = 300) -> dict:
    with db_conn() as c:
        if not _iv_table_exists(c):
            return {"ticker": ticker.upper(), "rows": []}
        rows = _row_dicts(c.execute("""
            SELECT date, ticker, iv, iv_rank, iv_pctile, signal
            FROM iv_rank
            WHERE ticker = ?
            ORDER BY date ASC
            LIMIT ?
        """, (ticker.upper(), days)))
        return {"ticker": ticker.upper(), "rows": rows}


def _ua_table_exists(c) -> bool:
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unusual_activity'"
    ).fetchone() is not None


def get_ua_meta() -> dict:
    """Metadata: latest date, ticker count, signal counts, last ingestion."""
    with db_conn() as c:
        if not _ua_table_exists(c):
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
            "last_ingestion": _row_dicts([last_log])[0] if last_log else None,
        }


def get_ua_latest() -> dict:
    with db_conn() as c:
        if not _ua_table_exists(c):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        rows = _row_dicts(c.execute("""
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
        if not _ua_table_exists(c):
            return {"latest_date": None, "rows": []}
        latest = c.execute("SELECT MAX(date) FROM unusual_activity").fetchone()[0]
        rows = _row_dicts(c.execute("""
            SELECT ticker, activity_type, call_put, expiry, strike,
                   notional_usd, severity_score, signal
            FROM unusual_activity
            WHERE date = ? AND signal IN ('EXTREME', 'HIGH')
            ORDER BY severity_score DESC
        """, (latest,)))
        return {"latest_date": latest, "rows": rows}


def get_ua_history(ticker: str, limit: int = 100) -> dict:
    with db_conn() as c:
        if not _ua_table_exists(c):
            return {"ticker": ticker.upper(), "rows": []}
        rows = _row_dicts(c.execute("""
            SELECT date, activity_type, call_put, expiry, strike,
                   volume, voi_ratio, notional_usd, iv_pct, price,
                   vol_ratio, severity_score, signal
            FROM unusual_activity
            WHERE ticker = ?
            ORDER BY date ASC
            LIMIT ?
        """, (ticker.upper(), limit)))
        return {"ticker": ticker.upper(), "rows": rows}
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
# Economic Calendar
# ---------------------------------------------------------------------------
def get_econ_events(
    *,
    days_ahead: int = 30,
    impact: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Upcoming economic calendar events from the economic_events table.

    Mirrors the read-only pattern from get_si_latest / get_si_signals.
    Returns empty list if the table doesn't exist yet (e.g. old DB mount).
    """
    with db_conn() as c:
        try:
            c.execute("SELECT 1 FROM economic_events LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            logger.warning("economic_events table not found in DB — returning empty")
            return []
        where: list[str] = [
            "event_date >= date('now')",
            f"event_date <= date('now', '+{days_ahead} days')",
        ]
        params: list[Any] = []
        if impact:
            where.append("impact = ?")
            params.append(impact)
        if category:
            where.append("category = ?")
            params.append(category)
        where_sql = " AND ".join(where)

        sql = f"""
            SELECT event_date, event_time, event_name, category, impact,
                   actual, prior, forecast, timezone_id, source, url
            FROM economic_events
            WHERE {where_sql}
            ORDER BY event_date, event_time
        """ + (" LIMIT ?" if limit else "")
        if limit:
            params.append(limit)
        rows = c.execute(sql, params).fetchall()
        return _row_dicts(rows)


def get_econ_meta() -> dict:
    """Top-level economic calendar info: last refresh, categories, impact dist.

    Returns zeroed metadata if the table doesn't exist yet.
    """
    with db_conn() as c:
        try:
            c.execute("SELECT 1 FROM economic_events LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            logger.warning("economic_events table not found in DB — returning empty meta")
            return {"last_update": None, "upcoming_count": 0, "categories": []}
        last_update = c.execute(
            "SELECT MAX(updated_at) FROM economic_events"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE event_date >= date('now')"
        ).fetchone()[0]
        categories = [r[0] for r in c.execute(
            "SELECT DISTINCT category FROM economic_events "
            "WHERE event_date >= date('now') ORDER BY category"
        ).fetchall()]
        return {
            "last_update": last_update,
            "upcoming_count": total,
            "categories": categories,
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


# ---------------------------------------------------------------------------
# Form 4 Insider Trading
# ---------------------------------------------------------------------------
def _has_table(c, name: str) -> bool:
    """Check if a table exists (for graceful degradation when DB not yet populated)."""
    row = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def get_insider_meta() -> dict:
    """Top-level insider trading info: latest filing, form4 count, tickers covered."""
    with db_conn() as c:
        if not _has_table(c, "insider_submissions"):
            return {"latest_filing_date": None, "total_form4_filings": 0,
                    "tickers_covered": 0, "quarters_available": []}
        latest = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]
        tickers = c.execute("""
            SELECT COUNT(DISTINCT issuertradingsymbol)
            FROM insider_submissions
            WHERE issuertradingsymbol IS NOT NULL
              AND issuertradingsymbol != ''
        """).fetchone()[0]
        quarters = [r[0] for r in c.execute("""
            SELECT DISTINCT quarter FROM insider_submissions
            WHERE quarter IS NOT NULL ORDER BY quarter DESC LIMIT 12
        """).fetchall()]
        return {
            "latest_filing_date": latest,
            "total_form4_filings": total,
            "tickers_covered": tickers,
            "quarters_available": quarters,
        }


def search_insider_tickers(query: str, limit: int = 30) -> list[dict]:
    """Search tickers that have insider transaction data."""
    with db_conn() as c:
        if not _has_table(c, "insider_submissions"):
            return []
        rows = c.execute("""
            SELECT DISTINCT
                t.ticker, COALESCE(t.name, s.issuername) AS name, COUNT(*) as tx_count
            FROM insider_submissions s
            LEFT JOIN tickers t ON t.ticker = s.issuertradingsymbol
            WHERE s.issuertradingsymbol LIKE ?
               OR t.name LIKE ?
               OR s.issuername LIKE ?
            GROUP BY COALESCE(t.ticker, s.issuertradingsymbol), COALESCE(t.name, s.issuername)
            ORDER BY tx_count DESC
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        return _row_dicts(rows)


def get_insider_latest(ticker: str | None = None, limit: int = 100,
                       min_value: int | None = None) -> list[dict]:
    """Latest insider transactions, optionally filtered to a ticker.

    Joins submissions → owners → transactions. Filters to Form 4 filings.
    """
    ticker = ticker.upper().strip() if ticker else None
    with db_conn() as c:
        if not _has_table(c, "insider_submissions"):
            return []
        where: list[str] = ["s.document_type IN ('4', '4/A')"]
        params: list[Any] = []
        if ticker:
            where.append("s.issuertradingsymbol = ?")
            params.append(ticker)
        if min_value is not None:
            where.append("t.transaction_value_usd >= ?")
            params.append(min_value)
        where_sql = " AND ".join(where)

        rows = c.execute(f"""
            SELECT
                s.accession_number,
                s.filing_date,
                s.period_of_report,
                s.document_type,
                s.issuername,
                s.issuertradingsymbol as ticker,
                o.rptownercik,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.security_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.trans_acquired_disp_cd,
                t.trans_code,
                t.transaction_value_usd,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                t.direct_indirect_ownership,
                t.nature_of_ownership,
                t.trans_timeliness
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE {where_sql}
            ORDER BY s.filing_date DESC, t.trans_date DESC
            LIMIT ?
        """, (*params, limit)).fetchall()
        return _row_dicts(rows)


def get_insider_ticker(symbol: str) -> dict | None:
    """Full insider trading history for a single ticker.

    Returns company info, insider list, and all transactions.
    """
    symbol = symbol.upper().strip()
    with db_conn() as c:
        if not _has_table(c, "insider_submissions"):
            return None

        # Basic ticker info from shared dimension
        t = c.execute(
            "SELECT ticker, name, sector, industry, category FROM tickers WHERE ticker = ?",
            (symbol,)
        ).fetchone()
        ticker_name = dict(t) if t else None

        # All transactions for this ticker
        rows = c.execute("""
            SELECT
                s.accession_number,
                s.filing_date,
                s.period_of_report,
                s.document_type,
                o.rptownercik,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.security_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.trans_acquired_disp_cd,
                t.trans_code,
                t.transaction_value_usd,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                t.direct_indirect_ownership,
                t.nature_of_ownership,
                t.trans_timeliness
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.issuertradingsymbol = ?
              AND s.document_type IN ('4', '4/A')
            ORDER BY s.filing_date DESC, t.trans_date DESC
        """, (symbol,)).fetchall()

        if not rows:
            return None

        transactions = _row_dicts(rows)

        # Latest filing info
        latest = c.execute("""
            SELECT s.accession_number, s.filing_date, s.period_of_report,
                   s.document_type, s.issuername
            FROM insider_submissions s
            WHERE s.issuertradingsymbol = ?
              AND s.document_type IN ('4', '4/A')
            ORDER BY s.filing_date DESC LIMIT 1
        """, (symbol,)).fetchone()
        latest_info = dict(latest) if latest else None

        # Distinct insiders who traded
        insiders = []
        seen = set()
        for r in transactions:
            key = r["rptownername"]
            if key not in seen:
                seen.add(key)
                ins_txns = [tx for tx in transactions if tx["rptownername"] == key]
                buys = sum(tx.get("transaction_value_usd") or 0
                           for tx in ins_txns if tx["trans_acquired_disp_cd"] == "A")
                sells = sum(tx.get("transaction_value_usd") or 0
                            for tx in ins_txns if tx["trans_acquired_disp_cd"] == "D")
                insiders.append({
                    "name": key,
                    "cik": r.get("rptownercik"),
                    "relationship": r["rptowner_relationship"],
                    "title": r.get("rptowner_title"),
                    "tx_count": len(ins_txns),
                    "total_buy_value_usd": buys,
                    "total_sell_value_usd": sells,
                })

        # Aggregate totals
        total_buy = sum(tx.get("transaction_value_usd") or 0
                        for tx in transactions if tx["trans_acquired_disp_cd"] == "A")
        total_sell = sum(tx.get("transaction_value_usd") or 0
                         for tx in transactions if tx["trans_acquired_disp_cd"] == "D")

        return {
            "symbol": symbol,
            "company_name": ticker_name["name"] if ticker_name
                          else (latest_info["issuername"] if latest_info else None),
            "sector": ticker_name["sector"] if ticker_name else None,
            "industry": ticker_name["industry"] if ticker_name else None,
            "category": ticker_name["category"] if ticker_name else None,
            "latest_filing": latest_info,
            "insiders": insiders,
            "transactions": transactions,
            "total_transactions": len(transactions),
            "total_form4_filings": len(set(r["accession_number"] for r in transactions)),
            "total_buy_value_usd": total_buy,
            "total_sell_value_usd": total_sell,
            "net_value_usd": total_buy - total_sell,
        }


def get_insider_signals(limit: int = 100) -> dict:
    """Compute signal sets from recent insider transactions."""
    with db_conn() as c:
        if not _has_table(c, "insider_submissions"):
            return {"latest_filing_date": None, "top_buys": [], "top_sells": [], "officer_trades": []}

        latest_filing = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]

        buys = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.direct_indirect_ownership,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'A'
              AND t.trans_code IN ('P', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND t.direct_indirect_ownership = 'D'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        sells = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.direct_indirect_ownership,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'D'
              AND t.trans_code IN ('S', 'D', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND t.direct_indirect_ownership = 'D'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        officers = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.trans_acquired_disp_cd,
                t.trans_code,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND o.rptowner_relationship LIKE '%OFFICER%'
              AND t.trans_code IN ('P', 'S', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
            ORDER BY s.filing_date DESC, t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return {
            "latest_filing_date": latest_filing,
            "top_buys": _row_dicts(buys),
            "top_sells": _row_dicts(sells),
            "officer_trades": _row_dicts(officers),
        }


# ---------------------------------------------------------------------------
# News Sentiment
# ---------------------------------------------------------------------------
def _news_table_exists(c) -> bool:
    """Check whether the news_sentiment tables are present in this DB."""
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='news_headlines'"
    ).fetchone() is not None


def get_news_meta() -> dict:
    """Top-level news sentiment metadata: latest date, sources, counts, ingestion log."""
    with db_conn() as c:
        if not _news_table_exists(c):
            return {"latest_date": None, "total_headlines": 0,
                    "sources": [], "signal_counts": {}, "last_ingestion": None}

        latest = c.execute(
            "SELECT MAX(date(datetime(retrieved_at, 'localtime'))) FROM news_headlines"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM news_headlines"
        ).fetchone()[0]
        sources = [r[0] for r in c.execute(
            "SELECT DISTINCT source FROM news_headlines ORDER BY source"
        ).fetchall()]
        signal_date = c.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]
        signal_counts = {}
        if signal_date:
            signal_counts["bullish"] = c.execute(
                "SELECT COUNT(*) FROM ticker_news_sentiment "
                "WHERE date = ? AND headline_count >= 2 AND avg_sentiment >= 0.15",
                (signal_date,)
            ).fetchone()[0]
            signal_counts["bearish"] = c.execute(
                "SELECT COUNT(*) FROM ticker_news_sentiment "
                "WHERE date = ? AND headline_count >= 2 AND avg_sentiment <= -0.15",
                (signal_date,)
            ).fetchone()[0]
        last_log = c.execute("""
            SELECT started_at, completed_at, status,
                   urls_checked, headlines_found, headlines_stored,
                   error_message
            FROM ingestion_log_news
            ORDER BY started_at DESC LIMIT 1
        """).fetchone()

        return {
            "latest_date": latest,
            "total_headlines": total,
            "sources": sources,
            "latest_signal_date": signal_date,
            "signal_counts": signal_counts,
            "last_ingestion": dict(last_log) if last_log else None,
        }


def get_news_headlines(limit: int = 100) -> list[dict[str, Any]]:
    """Latest headlines across all sources, newest first."""
    with db_conn() as c:
        if not _news_table_exists(c):
            return []
        return _row_dicts(c.execute("""
            SELECT id, source, title, url, published_at,
                   sentiment_score, sentiment_label, tickers_mentioned
            FROM news_headlines
            ORDER BY retrieved_at DESC, published_at DESC
            LIMIT ?
        """, (limit,)))


def get_news_ticker(ticker: str) -> dict | None:
    """Get news sentiment detail for a single ticker: latest aggregate + individual headlines."""
    ticker = ticker.upper().strip()
    with db_conn() as c:
        if not _news_table_exists(c):
            return None
        agg = c.execute("""
            SELECT ticker, date, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker, 30)).fetchall()
        headlines = _row_dicts(c.execute("""
            SELECT source, title, url, published_at,
                   sentiment_score, sentiment_label
            FROM news_headlines
            WHERE tickers_mentioned LIKE ?
            ORDER BY published_at DESC
            LIMIT 50
        """, (f"%{ticker}%",)))
        if not agg and not headlines:
            return None
        rows = _row_dicts(agg)
        rows.reverse()  # oldest first
        return {
            "ticker": ticker,
            "history": rows,
            "headlines": headlines,
        }


def get_news_signals() -> dict:
    """Current bullish / bearish ticker signals from the latest aggregated data."""
    with db_conn() as c:
        if not _news_table_exists(c):
            return {"latest_date": None, "bullish": [], "bearish": []}
        latest_date = c.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]
        if not latest_date:
            return {"latest_date": None, "bullish": [], "bearish": []}
        bullish = _row_dicts(c.execute("""
            SELECT ticker, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ? AND headline_count >= 2 AND avg_sentiment >= 0.15
            ORDER BY avg_sentiment DESC, headline_count DESC
            LIMIT 20
        """, (latest_date,)))
        bearish = _row_dicts(c.execute("""
            SELECT ticker, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ? AND headline_count >= 2 AND avg_sentiment <= -0.15
            ORDER BY avg_sentiment ASC, headline_count DESC
            LIMIT 20
        """, (latest_date,)))
        return {
            "latest_date": latest_date,
            "bullish": bullish,
            "bearish": bearish,
        }


# ---------------------------------------------------------------------------
# Customizable Stock Screener
# ---------------------------------------------------------------------------
def get_screener_meta() -> dict:
    """Metadata for the screener: available sectors + latest price date."""
    with db_conn() as c:
        sectors = [
            r[0] for r in c.execute(
                "SELECT DISTINCT sector FROM tickers "
                "WHERE is_active = 1 AND sector IS NOT NULL AND sector != '' "
                "ORDER BY sector"
            ).fetchall()
        ]
        latest_price_date = c.execute(
            "SELECT MAX(date) FROM price_history"
        ).fetchone()[0]
        ticker_count = c.execute(
            "SELECT COUNT(DISTINCT ticker) FROM tickers WHERE is_active = 1"
        ).fetchone()[0]
    return {
        "sectors": sectors,
        "latest_price_date": latest_price_date,
        "ticker_count": ticker_count,
    }


def get_screener_results(
    sector: str = "",
    min_price: float = 0,
    max_price: float | None = None,
    min_volume: int = 0,
    min_market_cap: float = 0,
    etf_only: bool = False,
    stocks_only: bool = False,
    sort_col: str = "market_cap",
    sort_dir: str = "desc",
    limit: int = 100,
) -> list[dict]:
    """Screen tickers by fundamental + price/volume criteria.

    Filters against the latest price_history row per ticker joined to the
    tickers dimension. Market cap is computed as close × shares_outstanding.
    Sorting is done in Python for flexibility (dynamic sort column).
    """
    valid_sort_cols = {
        "price", "volume", "market_cap", "ticker", "name", "sector",
        "shares_outstanding", "pct_change",
    }
    if sort_col not in valid_sort_cols:
        sort_col = "market_cap"

    with db_conn() as c:
        # Latest price + 5-day ROC via correlated subqueries
        rows = _row_dicts(c.execute("""
            SELECT
                t.ticker, t.name, t.sector, t.industry, t.category,
                t.is_etf, t.exchange,
                lp.close AS price, lp.volume, lp.date AS price_date,
                t.shares_outstanding, t.free_float_shares,
                lp.close * COALESCE(t.shares_outstanding, 0) AS market_cap,
                ((lp.close * 1.0 / p5.close) - 1.0) AS pct_change
            FROM tickers t
            JOIN (
                SELECT ticker, close, volume, date
                FROM price_history ph1
                WHERE date = (SELECT MAX(date) FROM price_history ph2
                              WHERE ph2.ticker = ph1.ticker)
            ) lp ON lp.ticker = t.ticker
            LEFT JOIN (
                SELECT ticker, close
                FROM price_history ph3
                WHERE date = (
                    SELECT date FROM price_history
                    WHERE ticker = ph3.ticker
                    ORDER BY date DESC LIMIT 1 OFFSET 4
                )
            ) p5 ON p5.ticker = t.ticker
            WHERE t.is_active = 1
              AND lp.close > 0
              AND (:sector = '' OR t.sector = :sector)
              AND lp.close >= :min_price
              AND (:max_price IS NULL OR lp.close <= :max_price)
              AND lp.volume >= :min_volume
              AND (:min_mc = 0 OR (lp.close * COALESCE(t.shares_outstanding, 0)) >= :min_mc)
              AND (:etf_only = 0 OR t.is_etf = 1)
              AND (:stocks_only = 0 OR t.is_etf = 0)
        """, {
            "sector": sector,
            "min_price": min_price,
            "max_price": max_price if max_price is not None else None,
            "min_volume": min_volume,
            "min_mc": min_market_cap,
            "etf_only": 1 if etf_only else 0,
            "stocks_only": 1 if stocks_only else 0,
        }))

    # Sort in Python (dynamic column)
    reverse = sort_dir == "desc"
    rows.sort(key=lambda r: (r.get(sort_col) is None, r.get(sort_col) or 0), reverse=reverse)
    # Clamp pct_change to sane floats
    for r in rows:
        pc = r.get("pct_change")
        if pc is not None and (pc != pc or pc == float("inf") or pc == float("-inf")):
            r["pct_change"] = None
    return rows[:limit]


# ---------------------------------------------------------------------------
# Famous Trader Quotes
# ---------------------------------------------------------------------------
def init_trader_quotes() -> None:
    """Create the trader_quotes table if it doesn't exist (writable)."""
    path = get_db_path()
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trader_quotes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            author        TEXT    NOT NULL,
            quote         TEXT    NOT NULL,
            category      TEXT,
            source        TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trader_quotes_category
        ON trader_quotes(category)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trader_quotes_unique
        ON trader_quotes(author, quote)
    """)
    conn.commit()
    conn.close()


def get_trader_quotes(category: str = "", limit: int = 100) -> list[dict]:
    """Retrieve trader quotes, optionally filtered by category."""
    with db_conn() as c:
        if category:
            rows = c.execute(
                "SELECT author, quote, category, source "
                "FROM trader_quotes WHERE category = ? "
                "ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT author, quote, category, source "
                "FROM trader_quotes ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows][:limit]


def get_trader_quote_categories() -> list[str]:
    """Return distinct categories used in the trader_quotes table."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT DISTINCT category FROM trader_quotes "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category"
        ).fetchall()
    return [r[0] for r in rows]


def get_random_trader_quote() -> dict | None:
    """Return a single random quote."""
    with db_conn() as c:
        row = c.execute(
            "SELECT author, quote, category, source "
            "FROM trader_quotes ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Earnings Revision Momentum
# ---------------------------------------------------------------------------
def init_earnings_revisions() -> None:
    """Create earnings revision tables if they don't exist (writable)."""
    path = get_db_path()
    conn = sqlite3.connect(str(path))
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
    with db_conn() as c:
        rows = c.execute("""
            SELECT ticker, latest_report_date, avg_revision_4q, pct_positive,
                   avg_surprise_pct, trend, zscore, created_at
            FROM earnings_revision_momentum
            ORDER BY zscore DESC, pct_positive DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_earnings_revision_history(ticker: str) -> list[dict]:
    """Return historical momentum snapshots for a single ticker."""
    with db_conn() as c:
        rows = c.execute("""
            SELECT date, avg_revision_4q, pct_positive, avg_surprise_pct,
                   trend, zscore
            FROM earnings_revision_history
            WHERE ticker = ?
            ORDER BY date DESC
        """, (ticker.upper(),)).fetchall()
    return [dict(r) for r in rows]


def get_earnings_revision_meta() -> dict:
    """Metadata for the earnings revision page."""
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
    return {
        "latest_date": latest,
        "ticker_count": total,
        "improving": improving,
        "deteriorating": deteriorating,
    }

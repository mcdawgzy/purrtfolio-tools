"""13F funds, holdings, QoQ changes, cross-fund ticker view, consensus, sectors."""
from __future__ import annotations

from typing import Any

from ..database import db_conn, row_dicts


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
        return row_dicts(rows)


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
        fund["filings"] = row_dicts(c.execute("""
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
            "holdings": row_dicts(rows),
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
            "changes": row_dicts(rows),
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
            WHERE h.ticker = ? AND h.put_call = ''
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
        # A fund is a *current* holder only if the ticker is in its latest filing;
        # otherwise the row is its last position before exiting.
        latest_by_fund = dict(c.execute("""
            SELECT fund_cik, MAX(report_period) FROM filings_13f
            WHERE has_infotable = 1 GROUP BY fund_cik
        """).fetchall())
        for h in per_fund.values():
            h["is_current"] = h["report_period"] == latest_by_fund.get(h["cik"])
        holders = sorted(
            per_fund.values(),
            key=lambda x: (x["is_current"], x["market_value_usd"] or 0),
            reverse=True,
        )
        current = [h for h in holders if h["is_current"]]
        # Quarter-by-quarter history (each quarter, total value across all funds)
        history_rows = c.execute("""
            SELECT report_period,
                   COUNT(DISTINCT fund_cik) as holders,
                   SUM(market_value_usd) as total_value_usd,
                   SUM(shares) as total_shares
            FROM holdings_13f
            WHERE ticker = ? AND put_call = ''
            GROUP BY report_period ORDER BY report_period
        """, (ticker,)).fetchall()

        return {
            "ticker": ticker,
            "found": True,
            "issuer_name": rows[0]["issuer_name"],
            "current_holders": len(current),
            "total_current_value_usd": sum(h["market_value_usd"] or 0 for h in current),
            "holders": holders,
            "history": row_dicts(history_rows),
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

        all_rows = row_dicts(rows)
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
        rows = row_dicts(c.execute("""
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
        period_rows = row_dicts(c.execute(
            "SELECT report_period FROM filings_13f "
            "WHERE has_infotable=1 "
            "GROUP BY report_period ORDER BY report_period DESC LIMIT 2"
        ))
        if len(period_rows) >= 2:
            return {"prev_q": period_rows[1]["report_period"], "curr_q": period_rows[0]["report_period"]}
        if len(period_rows) == 1:
            return {"prev_q": None, "curr_q": period_rows[0]["report_period"]}
        return {"prev_q": None, "curr_q": None}

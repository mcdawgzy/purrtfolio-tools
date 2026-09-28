"""Factor exposure (style drift) + 13F crowded positions."""
from __future__ import annotations

from ..database import db_conn, row_dicts, table_exists


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


def get_factor_meta() -> dict:
    """Latest quarter, AUM coverage, and enrichment status for the factors tab."""
    with db_conn() as c:
        if not table_exists(c, "ticker_factors"):
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
            WHERE h.report_period=? AND h.put_call=''
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


def _factor_holdings(quarter: str, pooled: bool) -> tuple[str, tuple]:
    """SQL fragment returning per-ticker (and optionally per-fund) latest-quarter
    holdings joined to `tickers.name`.  When pooled=True the value is summed
    across all funds (for overall exposure).  When pooled=False, strategy is
    retained (for per-strategy exposure)."""
    if pooled:
        return """
            SELECT h.ticker, t.name, SUM(h.market_value_usd) AS mv
            FROM holdings_13f h
            JOIN tickers t ON h.ticker = t.ticker
            JOIN filings_13f fl ON h.filing_accession = fl.accession_number
            JOIN funds f ON fl.fund_cik = f.cik
            WHERE h.report_period = ?
              AND h.ticker IS NOT NULL AND h.ticker != '' AND h.put_call = ''
            GROUP BY h.ticker, t.name
        """, (quarter,)
    return """
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
        if not table_exists(c, "ticker_factors"):
            meta = get_factor_meta()
            return {"quarter": meta["quarter"], "coverage_pct": 0,
                    "total_aum_usd": 0, "covered_aum_usd": 0,
                    "classified_tickers": 0, "dimensions": [], "by_strategy": []}
        if not quarter:
            quarter = _latest_quarter(c)
            if not quarter:
                return {"quarter": None, "dimensions": [], "by_strategy": []}

        # overall pooled holdings (one row per ticker, value summed across funds)
        pooled_sql, pparams = _factor_holdings(quarter, pooled=True)
        pooled = c.execute(
            f"WITH hold AS ({pooled_sql}) "
            f"SELECT h.ticker, h.mv FROM hold h "
            f"JOIN ticker_factors tf ON h.ticker = tf.ticker",
            pparams,
        ).fetchall()

        pooled_total = sum(r[1] for r in pooled) or 0

        # per-strategy holdings (one row per ticker+fund)
        strat_sql, sparams = _factor_holdings(quarter, pooled=False)
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

            # by strategy - single query per dimension (not one per strategy x dimension)
            strat_bucket_rows = c.execute(f"""
                WITH hold AS ({strat_sql})
                SELECT h.strategy, tf.{col} AS bucket,
                       SUM(h.mv) AS value_usd,
                       COUNT(DISTINCT h.cik) AS holders
                FROM hold h
                JOIN ticker_factors tf ON h.ticker = tf.ticker
                GROUP BY h.strategy, tf.{col}
            """, (quarter,)).fetchall()
            strat_buckets: dict = {}
            for _s, _b, _v, _h in strat_bucket_rows:
                strat_buckets.setdefault(_s, {})[_b] = (_v, _h)
            by_strat: list[dict] = []
            for strat in sorted(strat_totals):
                stot = strat_totals[strat]
                breakdown = {b: 0 for b in order}
                for b in order:
                    val, _holders = strat_buckets.get(strat, {}).get(b, (0, 0))
                    breakdown[b] = round(val / stot * 100, 1) if stot else 0
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
            WHERE h.report_period=? AND h.put_call=''
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
        if not table_exists(c, "ticker_factors"):
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
            "rows": row_dicts(rows),
        }

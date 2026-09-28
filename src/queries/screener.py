"""Customizable stock screener."""
from __future__ import annotations

from ..database import db_conn, row_dicts


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
        rows = row_dicts(c.execute("""
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

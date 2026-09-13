"""Compute and store rolling correlation matrices from price_history.

For each ticker in the watchlist, computes Pearson correlation of daily
returns vs each pivot ticker, over multiple windows (1mo / 3mo / 6mo / 1yr).
Results are stored as compact JSON rows in corr_matrices.
"""
from __future__ import annotations

import logging
import sqlite3
import json
import numpy as np
import pandas as pd
from datetime import date
from typing import List, Dict, Any

from .config import CORR_WINDOWS, PIVOT_TICKERS, CORR_TICKERS, DB_PATH
from .db import init_db, upsert_corr_row, get_latest_corr_date

logger = logging.getLogger(__name__)


def _load_price_matrix(
    conn: sqlite3.Connection,
    tickers: List[str],
    date_str: str,
    max_bars: int = 300,
) -> pd.DataFrame | None:
    """Load a wide DataFrame of adj_close prices for the given tickers.

    Aligns on date, picks the most recent *max_bars* trading days.
    """
    # Use tickers table's ticker column — match case-insensitively
    placeholders = ", ".join("?" for _ in tickers)
    upper_tickers = [t.upper() for t in tickers]
    rows = conn.execute(f"""
        SELECT ticker, date, adj_close
        FROM price_history
        WHERE ticker IN ({placeholders})
          AND adj_close IS NOT NULL
        ORDER BY ticker, date DESC
    """, upper_tickers).fetchall()

    if not rows:
        return None

    # Build wide frame
    raw: dict[str, dict[str, float]] = {}
    for r in rows:
        ticker = r["ticker"]
        raw.setdefault(ticker, {})[r["date"]] = r["adj_close"]

    # Convert to DataFrame: each ticker a column, dates as index
    frame = pd.DataFrame(raw)
    if frame.empty:
        return None

    # Sort by date, take the most recent max_bars
    frame = frame.sort_index()
    if len(frame) > max_bars:
        frame = frame.iloc[-max_bars:]

    return frame


def _compute_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns from price levels."""
    return df.pct_change().dropna()


def compute_correlations(
    prices: pd.DataFrame,
    pivots: List[str],
    target_tickers: List[str],
    window: int,
) -> Dict[str, Dict[str, float]]:
    """For each target ticker, compute correlation of its returns vs each pivot.

    Returns: {target_ticker: {pivot_ticker: corr}}
    """
    returns = _compute_returns(prices)
    result: dict[str, dict[str, float]] = {}

    pivot_norm = [p.upper() for p in pivots]
    target_norm = [t.upper() for t in target_tickers]

    # Only keep tickers present in the data
    available = [c for c in returns.columns if c.upper() in target_norm]
    pivots_available = [c for c in returns.columns if c.upper() in pivot_norm]

    for tgt in available:
        series = returns[tgt].tail(window)
        if len(series) < 5:
            continue
        # Normalize pivot lookups
        pivot_keys = {c.upper(): c for c in pivots_available}

        corr_dict: dict[str, float] = {}
        for p in pivots_available:
            pkey = p.upper()
            other = returns[p].tail(window)
            # Align on date index
            aligned = pd.concat([series, other], axis=1, keys=["s", "o"]).dropna()
            if len(aligned) < 5:
                continue
            s_vals = aligned["s"]
            o_vals = aligned["o"]
            if float(s_vals.std()) == 0 or float(o_vals.std()) == 0:
                continue
            corr_val = float(s_vals.corr(o_vals))
            if not np.isnan(corr_val):
                corr_dict[pkey] = round(corr_val, 4)

        if corr_dict:
            result[tgt] = corr_dict

    return result


def run_once(dry_run: bool = False) -> dict:
    """Compute correlation matrices for all windows and persist to DB.

    Uses the latest trading day present in price_history as the signal date.
    """
    logger.info("Computing correlation matrices...")

    # Determine the latest date with price data
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    latest_date = conn.execute(
        "SELECT MAX(date) FROM price_history"
    ).fetchone()[0]
    conn.close()

    if not latest_date:
        return {"status": "error", "error": "No price_history data found"}

    # Determine which tickers to compute correlations for
    target_tickers: List[str] = []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT DISTINCT ph.ticker
        FROM price_history ph
        JOIN tickers t ON ph.ticker = t.ticker
        WHERE ph.adj_close IS NOT NULL
    """).fetchall()
    target_tickers = [r["ticker"] for r in rows]
    conn.close()

    if not target_tickers:
        return {"status": "error", "error": "No tickers with price data"}

    logger.info("Computing correlations for %d tickers vs %d pivots",
                len(target_tickers), len(PIVOT_TICKERS))

    all_written = 0

    # Load price data once (reuse across windows)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    all_tickers = list(set(target_tickers + PIVOT_TICKERS))
    prices = _load_price_matrix(conn, all_tickers, latest_date, max_bars=300)
    conn.close()

    if prices is None or prices.empty:
        return {"status": "error", "error": "Could not load price matrix"}

    for window_name, window_days in CORR_WINDOWS.items():
        corr_map = compute_correlations(prices, PIVOT_TICKERS, target_tickers, window_days)

        if dry_run:
            logger.info("DRY RUN window=%s: %d ticker correlations", window_name, len(corr_map))
        else:
            init_db()
            for ticker, pivots_corr in corr_map.items():
                upsert_corr_row(ticker, latest_date, window_name, pivots_corr)
            all_written += len(corr_map)

        logger.info("Window %s: %d tickers", window_name, len(corr_map))

    return {
        "status": "completed",
        "signal_date": latest_date,
        "windows_computed": len(CORR_WINDOWS),
        "total_rows": all_written,
        "target_tickers": len(target_tickers),
        "pivot_tickers": len(PIVOT_TICKERS),
    }


if __name__ == "__main__":
    import json
    result = run_once()
    print(json.dumps(result, indent=2, default=str))

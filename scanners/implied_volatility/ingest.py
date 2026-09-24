"""
Data ingestion pipeline for IV Rank Scanner.

Fetches ATM implied volatility via yfinance options chains, computes
52-week IV Rank and IV Percentile, and stores results in the unified
purrtfolio.db SQLite database.
"""
import logging
import math
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import yfinance as yf

from .config import (
    DB_PATH, WATCHLIST, LOOKBACK_DAYS,
    IVP_HIGH_THRESHOLD, IVP_LOW_THRESHOLD,
    MAX_WORKERS, IV_MIN, IV_MAX,
)
from .db import init_db, get_db, get_latest_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  IV fetching
# --------------------------------------------------------------------------- #
def get_atm_iv(ticker: str) -> Optional[float]:
    """Fetch ATM implied volatility (%) for a single ticker from yfinance.

    yfinance's free options data sometimes returns stale/placeholder IV for
    exact ATM strikes. Instead, we use the **next-expiry** chain (skipping any
    same-day expiry) and average IV from OTM options 2–10% away from spot —
    these are the most actively traded and reliably populated strikes.

    Returns IV as a percentage (e.g. 15.5 for 15.5%) or None.
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            logger.warning(f"{ticker}: no price history")
            return None
        spot = hist["Close"].iloc[-1]
        if math.isnan(spot) or spot <= 0:
            return None

        expirations = tk.options
        if not expirations:
            logger.warning(f"{ticker}: no options expiries")
            return None

        # Skip same-day expiry (IV is ~0 when options expire today)
        exp = expirations[1] if len(expirations) > 1 else expirations[0]
        chain = tk.option_chain(exp)

        calls = chain.calls
        puts = chain.puts

        # OTM calls: strike 2–10% above spot
        call_otm = calls[
            (calls["strike"] > spot * 1.02) & (calls["strike"] <= spot * 1.10)
        ]
        # OTM puts: strike 2–10% below spot
        put_otm = puts[
            (puts["strike"] < spot * 0.98) & (puts["strike"] >= spot * 0.90)
        ]

        ivs = []
        for df in [call_otm, put_otm]:
            for _, r in df.iterrows():
                iv = r.get("impliedVolatility")
                if iv is not None and not math.isnan(iv):
                    pct = iv * 100
                    if IV_MIN <= pct <= IV_MAX:
                        ivs.append(pct)

        if not ivs:
            return None

        return round(sum(ivs) / len(ivs), 2)

    except Exception as e:
        logger.warning(f"{ticker}: yfinance error — {e}")
        return None


def fetch_all_ivs(tickers: list) -> dict:
    """Fetch IV for all tickers in parallel (ThreadPoolExecutor)."""
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(get_atm_iv, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                iv = future.result(timeout=30)
            except Exception as e:
                logger.warning(f"{ticker}: fetch error — {e}")
                iv = None
            results[ticker] = iv
    return results


# --------------------------------------------------------------------------- #
#  IV Rank / Percentile computation
# --------------------------------------------------------------------------- #
def compute_iv_metrics(conn, ticker: str, current_iv: float):
    """Compute IV Rank, IV Percentile, and 52-week stats from historical DB data.

    Returns:
      (iv_rank, iv_pctile, days_52w, iv_min, iv_max, iv_mean, iv_median, iv_std)
      or (None, None, days, None, None, None, None, None) when <10 data points.
    """
    rows = conn.execute("""
        SELECT iv FROM iv_rank
        WHERE ticker = ? AND iv IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
    """, (ticker.upper(), LOOKBACK_DAYS)).fetchall()

    historical_ivs = [r["iv"] for r in rows]
    days = len(historical_ivs)

    if days < 10:
        return (None, None, days, None, None, None, None, None)

    all_ivs = historical_ivs + [current_iv]
    min_iv = min(all_ivs)
    max_iv = max(all_ivs)

    # IV Rank: position within the 52-week range
    if max_iv > min_iv:
        iv_rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
    else:
        iv_rank = 50.0

    # IV Percentile: fraction of days with IV below current
    below = sum(1 for v in all_ivs if v < current_iv)
    iv_pctile = below / len(all_ivs) * 100

    # Stats
    mean = sum(historical_ivs) / len(historical_ivs)
    var = sum((x - mean) ** 2 for x in historical_ivs) / len(historical_ivs)
    std = var ** 0.5
    sorted_ivs = sorted(historical_ivs)
    n = len(sorted_ivs)
    if n % 2 == 1:
        median = sorted_ivs[n // 2]
    else:
        median = (sorted_ivs[n // 2 - 1] + sorted_ivs[n // 2]) / 2

    return (
        round(iv_rank, 1),
        round(iv_pctile, 1),
        days,
        round(min_iv, 2),
        round(max_iv, 2),
        round(mean, 2),
        round(median, 2),
        round(std, 2),
    )


def classify_signal(iv_pctile: Optional[float]) -> str:
    """Classify current IV regime based on IV Percentile."""
    if iv_pctile is None:
        return "NEUTRAL"
    if iv_pctile >= IVP_HIGH_THRESHOLD:
        return "HIGH_IV"
    if iv_pctile <= IVP_LOW_THRESHOLD:
        return "LOW_IV"
    return "NEUTRAL"


# --------------------------------------------------------------------------- #
#  Daily ingestion
# --------------------------------------------------------------------------- #
def ingest_daily(target_date: date) -> dict:
    """Ingest IV data for all watchlist tickers for a given date."""
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ingestion_log_iv (date, status) VALUES (?, 'started')",
            (str(target_date),)
        )
        log_id = cursor.lastrowid
        rows_inserted = 0
        errors = []

        ivs = fetch_all_ivs(WATCHLIST)

        for ticker in WATCHLIST:
            iv = ivs.get(ticker)
            if iv is None:
                errors.append(f"{ticker}: no IV data")
                continue

            iv_rank, iv_pctile, days_52w, iv_min, iv_max, iv_mean, iv_median, iv_std = \
                compute_iv_metrics(conn, ticker, iv)
            signal = classify_signal(iv_pctile)

            cursor.execute("""
                INSERT OR REPLACE INTO iv_rank
                    (date, ticker, iv, iv_rank, iv_pctile, days_52w,
                     iv_min_52w, iv_max_52w, iv_mean_52w, iv_median_52w, iv_std_52w, signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(target_date), ticker, iv, iv_rank, iv_pctile, days_52w,
                  iv_min, iv_max, iv_mean, iv_median, iv_std, signal))
            rows_inserted += 1

        cursor.execute(
            "UPDATE ingestion_log_iv SET status='completed', rows_inserted=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (rows_inserted, log_id)
        )
        conn.commit()

    logger.info(f"IV Rank ingest for {target_date}: {rows_inserted} rows, {len(errors)} errors")
    return {
        "date": str(target_date),
        "status": "completed",
        "rows_inserted": rows_inserted,
        "ticker_count": len(WATCHLIST),
        "errors": errors[:5],
    }


def get_latest_available_date() -> Optional[date]:
    """Return today's date (yfinance provides current data)."""
    return date.today()

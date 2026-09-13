"""Ingest daily price data for the momentum watchlist via yfinance.

Called by the Hermes cron job. For each ticker:
  1. Fetch the last 90 calendar days of daily bars (enough to cover all
     momentum windows + volume EMA with margin).
  2. Upsert into price_history.
  3. Compute momentum signals (ROC, SMA, volume ratio, consolidation, gaps).
  4. Upsert signals into price_momentum_signals.

The latest trading day's bar is used as the signal_date.
"""
from __future__ import annotations

import logging
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from typing import List, Dict, Any

from .config import (
    CURATED_TICKERS, MOMENTUM_WINDOWS, VOLUME_SPIKE_THRESHOLD,
    MIN_PRICE_USD,
)
from .db import init_db, upsert_daily_bars, upsert_signal, get_latest_signal_date

logger = logging.getLogger(__name__)


def fetch_ticker_history(ticker: str, days: int = 90) -> pd.DataFrame:
    """Fetch daily OHLCV for *ticker* from yfinance."""
    try:
        tk = yf.Ticker(ticker)
        # period=90d + some margin, interval=1d
        hist = tk.history(period=f"{days}d", interval="1d", auto_adjust=False)
        if hist.empty:
            logger.warning("No data for %s", ticker)
        return hist
    except Exception as e:
        logger.error("yfinance error for %s: %s", ticker, e)
        return pd.DataFrame()


def _normalize_bars(ticker: str, hist: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert a yfinance DataFrame into the list of dicts our DB expects."""
    if hist.empty:
        return []
    bars: list[dict] = []
    for ts, row in hist.iterrows():
        d = ts.strftime("%Y-%m-%d")
        bars.append({
            "ticker":    ticker,
            "date":      d,
            "open":      float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high":      float(row["High"]) if pd.notna(row["High"]) else None,
            "low":       float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close":     float(row["Close"]) if pd.notna(row["Close"]) else None,
            "adj_close": float(row["Adj Close"]) if pd.notna(row["Adj Close"]) else None,
            "volume":    int(row["Volume"]) if pd.notna(row["Volume"]) else None,
        })
    return bars


def compute_signals(hist: pd.DataFrame) -> Dict[str, Any] | None:
    """Compute momentum signals from a DataFrame of daily bars.

    Returns None if insufficient data (< 50 rows).
    """
    if hist.empty or len(hist) < MOMENTUM_WINDOWS["long"]:
        return None

    # Sort ascending by date (oldest first)
    hist = hist.sort_index()

    closes = hist["Close"]
    volumes = hist["Volume"]
    adj_close = hist["Adj Close"]

    latest = closes.iloc[-1]
    prev_close = closes.iloc[-2]

    # Rate of change
    roc_10d  = _roc(closes, MOMENTUM_WINDOWS["short"])
    roc_20d  = _roc(closes, MOMENTUM_WINDOWS["medium"])
    roc_50d  = _roc(closes, MOMENTUM_WINDOWS["long"])

    # Simple moving averages
    sma_10d = float(closes.iloc[-MOMENTUM_WINDOWS["short"]:].mean())
    sma_20d = float(closes.iloc[-MOMENTUM_WINDOWS["medium"]:].mean())
    sma_50d = float(closes.iloc[-MOMENTUM_WINDOWS["long"]:].mean())

    # Volume metrics
    vol_window = volumes.iloc[-MOMENTUM_WINDOWS["short"]:]
    if len(vol_window) > 0 and vol_window.mean() > 0:
        vol_ema_10d = float(vol_window.ewm(span=10, adjust=False).mean().iloc[-1])
        volume_ratio = float(volumes.iloc[-1] / vol_ema_10d)
    else:
        vol_ema_10d = None
        volume_ratio = None

    # Consolidation: price hasn't moved much in last 20 days, low volume
    range_20d = float(closes.iloc[-20:].max() - closes.iloc[-20:].min())
    is_consolidating = 0
    if sma_20d and sma_20d > 0:
        range_pct = range_20d / sma_20d
        if range_pct < 0.05 and volume_ratio is not None and volume_ratio < 1.2:
            is_consolidating = 1

    # Volume spike: today's volume > 2x the 10-day volume EMA
    is_volume_spike = 0
    if volume_ratio is not None and volume_ratio >= VOLUME_SPIKE_THRESHOLD:
        is_volume_spike = 1

    # Earnings gap: overnight gap vs prior close
    gapped_open = 0
    gap_pct = None
    if len(closes) >= 2 and prev_close > 0:
        todays_open = hist["Open"].iloc[-1]
        gap_pct = (todays_open / prev_close) - 1
        if abs(gap_pct) > 0.02:  # >2% gap
            gapped_open = 1

    return {
        "roc_10d":            round(roc_10d, 4)  if roc_10d is not None else None,
        "roc_20d":            round(roc_20d, 4)  if roc_20d is not None else None,
        "roc_50d":            round(roc_50d, 4)  if roc_50d is not None else None,
        "sma_10d":            round(sma_10d, 4)  if sma_10d else None,
        "sma_20d":            round(sma_20d, 4)  if sma_20d else None,
        "sma_50d":            round(sma_50d, 4)  if sma_50d else None,
        "volume_ema_10d":     round(vol_ema_10d, 1) if vol_ema_10d else None,
        "volume_ratio":       round(volume_ratio, 3) if volume_ratio else None,
        "is_volume_spike":    is_volume_spike,
        "is_consolidating":   is_consolidating,
        "gapped_open":        gapped_open,
        "gap_pct":            round(gap_pct, 4) if gap_pct is not None else None,
    }


def _roc(series: pd.Series, days: int) -> float | None:
    """Rate of change over *days* trading days, as a decimal fraction."""
    if len(series) < days + 1:
        return None
    try:
        old = series.iloc[-(days + 1)]
        new = series.iloc[-1]
        if old != 0:
            return float((new / old) - 1)
        return None
    except (IndexError, ZeroDivisionError):
        return None


def run_once(tickers: list[str] | None = None, dry_run: bool = False) -> dict:
    """Fetch latest bars for all watchlist tickers, compute signals, write to DB.

    Returns a summary dict.
    """
    tickers = tickers or CURATED_TICKERS
    logger.info("Fetching price data for %d tickers...", len(tickers))

    all_bars: list[dict] = []
    all_signals: list[tuple[str, date, dict]] = []
    errors: list[dict] = []

    for ticker in tickers:
        try:
            hist = fetch_ticker_history(ticker, days=90)
            if hist.empty:
                errors.append({"ticker": ticker, "error": "no data"})
                continue

            bars = _normalize_bars(ticker, hist)
            all_bars.extend(bars)

            signals = compute_signals(hist)
            if signals:
                signal_date = hist.index[-1].date()
                all_signals.append((ticker, signal_date, signals))
            else:
                errors.append({"ticker": ticker, "error": "insufficient data for signals"})

        except Exception as e:
            logger.error("Error processing %s: %s", ticker, e)
            errors.append({"ticker": ticker, "error": str(e)})

    if not dry_run:
        if all_bars:
            init_db()
            upsert_daily_bars(all_bars)

        for ticker, signal_date, sigs in all_signals:
            upsert_signal(ticker, signal_date, **sigs)
    else:
        logger.info("DRY RUN — would upsert %d bars, %d signals", len(all_bars), len(all_signals))

    latest = get_latest_signal_date() if not dry_run else (all_signals[0][1] if all_signals else None)
    summary = {
        "status": "completed" if not errors else "completed_with_errors",
        "tickers_processed": len(tickers) - len(errors),
        "bars_written": len(all_bars),
        "signals_written": len(all_signals),
        "errors": errors[:10],  # cap error list
        "latest_signal_date": str(latest) if latest else None,
    }
    logger.info(
        "Done: %d/%d tickers OK, %d bars, %d signals, %d errors",
        summary["tickers_processed"], len(tickers),
        summary["bars_written"], summary["signals_written"], len(errors),
    )
    return summary


if __name__ == "__main__":
    import json
    result = run_once()
    print(json.dumps(result, indent=2, default=str))

"""Data ingestion for Unusual Options Activity & Dark Pool proxy scanner.

Fetches yfinance options chains and daily volume/history to detect:
  - High-volume options strikes (volume/OI ratio, large notional)
  - Daily volume spikes vs 20-day average (dark-pool / block-trade proxy)

Stores results in the unified purrtfolio.db SQLite database.
"""
import logging
import math
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from math import inf

import yfinance as yf

from .config import (
    DB_PATH, WATCHLIST,
    MIN_VOLUME, MIN_VOI_RATIO, MIN_NOTIONAL,
    MIN_SEVERITY, MIN_VOL_RATIO, MIN_VOL_SPIKE_NOTIONAL,
    VOL_LOOKBACK, PRICE_WINDOW_DAYS, MAX_WORKERS,
)
from .db import init_db, get_db, get_latest_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _num(v, default=0):
    """Convert pandas/numpy scalar to float, treating NaN/Inf/None as default."""
    if v is None:
        return default
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        return default
    return f


# --------------------------------------------------------------------------- #
#  Unusual options activity
# --------------------------------------------------------------------------- #
def scan_unusual_options(ticker: str) -> list:
    """Scan yfinance options chain for unusual options activity.

    Looks at the nearest non-expired chain, flags strikes where:
      - volume >= MIN_VOLUME contracts
      - volume / openInterest >= MIN_VOI_RATIO
      - notional >= MIN_NOTIONAL USD

    Returns a list of activity dicts.
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            logger.warning(f"{ticker}: no price history")
            return []
        spot = hist["Close"].iloc[-1]
        if math.isnan(spot) or spot <= 0:
            return []

        expirations = tk.options
        if not expirations:
            return []

        # Skip same-day expiry
        exp = expirations[1] if len(expirations) > 1 else expirations[0]
        chain = tk.option_chain(exp)

        activities = []
        for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
            for _, row in df.iterrows():
                vol = _num(row.get("volume"))
                if vol < MIN_VOLUME:
                    continue

                oi = _num(row.get("openInterest"))
                strike = _num(row.get("strike"))
                bid = _num(row.get("bid"))
                ask = _num(row.get("ask"))
                iv_raw = row.get("impliedVolatility")
                mid = (bid + ask) / 2 if bid > 0 or ask > 0 else 0

                notional = vol * 100 * mid
                if notional < MIN_NOTIONAL:
                    continue

                voi_ratio = vol / oi if oi > 0 else None
                iv_pct = round(iv_raw * 100, 2) if iv_raw is not None and _num(iv_raw) > 0 else None

                # Severity: VOI ratio (0-40) + notional (0-30) + ITM proximity (0-30)
                voi_score = min((voi_ratio or 0) * 15, 40)
                notional_score = min(notional / 200_000 * 5, 30)  # 0 at $200K → 30 at $1.2M

                moneyness = abs(strike - spot) / spot
                itm_score = (1 - moneyness) * 30 if moneyness < 0.15 else 0  # ATM gets 30

                severity = round(voi_score + notional_score + itm_score, 1)
                if severity < MIN_SEVERITY:
                    continue

                signal = "EXTREME" if severity >= 80 else "HIGH" if severity >= 60 else "MEDIUM" if severity >= 30 else "LOW"

                activities.append({
                    "ticker": ticker,
                    "activity_type": "options",
                    "call_put": opt_type,
                    "expiry": exp,
                    "strike": strike,
                    "volume": int(vol),
                    "open_interest": int(oi) if oi > 0 else None,
                    "voi_ratio": round(voi_ratio, 3) if oi > 0 else None,
                    "notional_usd": round(notional, 0),
                    "iv_pct": iv_pct,
                    "price": round(spot, 2),
                    "severity_score": severity,
                    "signal": signal,
                })

        # Sort by severity descending
        activities.sort(key=lambda x: x["severity_score"], reverse=True)
        return activities

    except Exception as e:
        logger.warning(f"{ticker}: options scan error — {e}")
        return []


# --------------------------------------------------------------------------- #
#  Volume spike detection (dark-pool proxy)
# --------------------------------------------------------------------------- #
def scan_volume_spikes(ticker: str) -> Optional[dict]:
    """Detect unusual daily volume spike as a dark-pool / block-trade proxy.

    Compares today's volume to the 20-day average. A spike >= MIN_VOL_RATIO×
    with notional >= MIN_VOL_SPIKE_NOTIONAL indicates possible institutional
    dark-pool activity.

    Returns an activity dict or None.
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=f"{PRICE_WINDOW_DAYS}d", interval="1d")
        if hist.empty or len(hist) < VOL_LOOKBACK + 1:
            return None

        volumes = hist["Volume"].fillna(0)
        prices = hist["Close"]

        avg_vol = volumes.iloc[-(VOL_LOOKBACK + 1):-1].mean()
        today_vol = volumes.iloc[-1]
        today_price = prices.iloc[-1]

        if avg_vol <= 0 or math.isnan(today_price) or today_price <= 0:
            return None

        vol_ratio = today_vol / avg_vol
        notional = today_vol * today_price

        if vol_ratio < MIN_VOL_RATIO or notional < MIN_VOL_SPIKE_NOTIONAL:
            return None

        severity = min(vol_ratio * 15, 100)  # cap at 100
        signal = "EXTREME" if severity >= 80 else "HIGH" if severity >= 60 else "MEDIUM" if severity >= 30 else "LOW"

        return {
            "ticker": ticker,
            "activity_type": "volume",
            "call_put": "underlying",
            "expiry": None,
            "strike": None,
            "volume": int(today_vol),
            "open_interest": None,
            "voi_ratio": None,
            "notional_usd": round(notional, 0),
            "iv_pct": None,
            "price": round(today_price, 2),
            "avg_vol_20d": round(avg_vol, 0),
            "vol_ratio": round(vol_ratio, 2),
            "severity_score": round(severity, 1),
            "signal": signal,
        }

    except Exception as e:
        logger.warning(f"{ticker}: volume scan error — {e}")
        return None


# --------------------------------------------------------------------------- #
#  Daily ingestion
# --------------------------------------------------------------------------- #
def scan_ticker(ticker: str) -> list:
    """Run both options and volume scans for a single ticker."""
    results = []
    results.extend(scan_unusual_options(ticker))
    vs = scan_volume_spikes(ticker)
    if vs:
        results.append(vs)
    return results


def ingest_daily(target_date: date) -> dict:
    """Ingest unusual activity data for all watchlist tickers."""
    init_db()
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO ingestion_log_ua (date, status) VALUES (?, 'started')",
            (str(target_date),)
        )
        log_id = c.lastrowid
        rows_inserted = 0
        errors = []

        # Clear same-date entries (idempotent re-ingest)
        c.execute("DELETE FROM unusual_activity WHERE date = ?", (str(target_date),))

        all_activities = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(scan_ticker, t): t for t in WATCHLIST}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    acts = future.result(timeout=30)
                    all_activities.extend(acts)
                except Exception as e:
                    logger.warning(f"{ticker}: scan error — {e}")
                    errors.append(f"{ticker}: {e}")

        for act in all_activities:
            c.execute("""
                INSERT INTO unusual_activity
                    (date, ticker, activity_type, call_put, expiry, strike,
                     volume, open_interest, voi_ratio, notional_usd, iv_pct,
                     price, avg_vol_20d, vol_ratio, severity_score, signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(target_date), act["ticker"], act["activity_type"],
                act["call_put"], act["expiry"], act["strike"],
                act["volume"], act["open_interest"], act["voi_ratio"],
                act["notional_usd"], act["iv_pct"], act["price"],
                act.get("avg_vol_20d"), act.get("vol_ratio"),
                act["severity_score"], act["signal"],
            ))
            rows_inserted += 1

        c.execute(
            "UPDATE ingestion_log_ua SET status='completed', rows_inserted=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (rows_inserted, log_id)
        )
        conn.commit()

    n_tickers = len({a["ticker"] for a in all_activities})
    n_extreme = sum(1 for a in all_activities if a["signal"] == "EXTREME")
    n_high = sum(1 for a in all_activities if a["signal"] == "HIGH")
    logger.info(f"UA ingest for {target_date}: {rows_inserted} activities across {n_tickers} tickers "
                f"(EXTREME={n_extreme}, HIGH={n_high}, errors={len(errors)})")
    return {
        "date": str(target_date),
        "status": "completed",
        "rows_inserted": rows_inserted,
        "ticker_count": n_tickers,
        "extreme_count": n_extreme,
        "high_count": n_high,
        "errors": errors[:5],
    }


def get_pending_date() -> Optional[date]:
    latest_in_db = get_latest_date()
    today_str = date.today().isoformat()
    if latest_in_db and latest_in_db == today_str:
        return None
    return date.today()

"""
Data ingestion pipeline for CBOE daily put/call ratio data.

Source: https://cdn.cboe.com/data/us/options/market_statistics/daily/{YYYY-MM-DD}_daily_options

Returns JSON with:
  ratios[]: [{name: "TOTAL PUT/CALL RATIO", value: "0.96"}, ...]
  "SUM OF ALL PRODUCTS": [{name: "VOLUME", call, put, total}, {name: "OPEN INTEREST", ...}]
  "INDEX OPTIONS": [...]
  "EQUITY OPTIONS": [...]
  "EXCHANGE TRADED PRODUCTS": [...]
  "CBOE VOLATILITY INDEX (VIX)": [...]
  etc.
"""
import asyncio
import httpx
import sqlite3
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from datetime import datetime

from .config import (
    DB_PATH, CBOE_API_BASE, CBOE_CSV_BASE, SERIES_MAP, VOLUME_MAP,
    MAX_LOOKBACK_DAYS, PCR_HIGH_THRESHOLD, PCR_LOW_THRESHOLD,
    MA_SHORT, MA_MEDIUM, MA_LONG, HTTP_HEADERS,
)
from .db import get_db, init_db


def get_latest_available_date() -> Optional[date]:
    """Try recent business days on the CBOE API, return the most recent date with data."""
    today = date.today()
    for i in range(0, MAX_LOOKBACK_DAYS):
        check_date = today - timedelta(days=i)
        if check_date.weekday() >= 5:  # Skip weekends
            continue
        date_str = check_date.strftime("%Y-%m-%d")
        url = f"{CBOE_API_BASE}/{date_str}_daily_options"
        try:
            resp = httpx.get(url, timeout=15, headers=HTTP_HEADERS)
            if resp.status_code == 200 and len(resp.content) > 200:
                return check_date
        except Exception:
            continue
    return None


async def download_daily_data(target_date: date) -> Optional[Dict[str, Any]]:
    """Download the daily put/call ratio JSON for a given date."""
    date_str = target_date.strftime("%Y-%m-%d")
    url = f"{CBOE_API_BASE}/{date_str}_daily_options"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=HTTP_HEADERS)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Error downloading {date_str}: {e}")
        return None


def parse_ratio_value(data: Dict[str, Any], ratio_name: str) -> Optional[float]:
    """Extract a ratio value from the 'ratios' list by name."""
    for r in data.get("ratios", []):
        if r.get("name") == ratio_name:
            return float(r["value"])
    return None


def parse_volume(data: Dict[str, Any], category_key: str, metric: str) -> Dict[str, int]:
    """Extract volume/OI for a category from the JSON.

    metric: 'VOLUME' or 'OPEN INTEREST'
    Returns: {'call': int, 'put': int, 'total': int}
    """
    section = data.get(category_key, [])
    for item in section:
        if item.get("name") == metric:
            return {
                "call": int(item.get("call", 0) or 0),
                "put": int(item.get("put", 0) or 0),
                "total": int(item.get("total", 0) or 0),
            }
    return {"call": 0, "put": 0, "total": 0}


def ingest_date(conn: sqlite3.Connection, target_date: date, data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse CBOE JSON and store one day of data for all series."""
    cursor = conn.cursor()

    # Log start
    cursor.execute(
        "INSERT INTO ingestion_log_pcr (date, status) VALUES (?, 'started')",
        (target_date,),
    )
    log_id = cursor.lastrowid

    rows_inserted = 0
    for ratio_name, series_key in SERIES_MAP.items():
        ratio = parse_ratio_value(data, ratio_name)
        if ratio is None:
            continue

        # Volume/OI lookup — map series to its category section
        category_key = None
        for cat, key in VOLUME_MAP.items():
            if key == series_key:
                category_key = cat
                break
        if category_key is None:
            continue

        vol = parse_volume(data, category_key, "VOLUME")
        oi = parse_volume(data, category_key, "OPEN INTEREST")

        cursor.execute("""
            INSERT OR REPLACE INTO put_call_ratio
                (date, series, ratio, call_volume, put_volume, total_volume,
                 call_oi, put_oi, total_oi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            target_date, series_key, ratio,
            vol["call"], vol["put"], vol["total"],
            oi["call"], oi["put"], oi["total"],
        ))
        rows_inserted += 1

    # Update materialized latest table + compute signals
    update_latest_and_signals(conn)

    cursor.execute(
        "UPDATE ingestion_log_pcr SET status='completed', rows_inserted=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
        (rows_inserted, log_id),
    )
    conn.commit()

    return {
        "date": str(target_date),
        "status": "completed",
        "rows_inserted": rows_inserted,
    }


def update_latest_and_signals(conn: sqlite3.Connection) -> None:
    """Recompute the put_call_latest materialized table with MA and signal."""
    cursor = conn.cursor()

    for series_key in SERIES_MAP.values():
        # Get latest 60 days of data for this series
        cursor.execute("""
            SELECT date, ratio
            FROM put_call_ratio
            WHERE series = ?
            ORDER BY date DESC
            LIMIT 60
        """, (series_key,))
        rows = cursor.fetchall()

        if not rows:
            continue

        # Data is ordered DESC; we need ASC for MA computation
        ratios = [(r["date"], r["ratio"]) for r in rows]
        ratios_asc = list(reversed(ratios))
        values = [r[1] for r in ratios_asc if r[1] is not None]

        latest = ratios_asc[-1]  # most recent (last in ASC order)
        latest_date, latest_ratio = latest

        # Moving averages
        ma5 = _safe_ma(values, MA_SHORT)
        ma20 = _safe_ma(values, MA_MEDIUM)
        ma50 = _safe_ma(values, MA_LONG)

        # Z-score vs 50-day mean
        z_score = _zscore(values, MA_LONG)

        # Signal
        signal = _classify_signal(latest_ratio, z_score)

        # Volume/OI from latest date
        cursor.execute("""
            SELECT call_volume, put_volume, total_volume,
                   call_oi, put_oi, total_oi
            FROM put_call_ratio
            WHERE series = ? AND date = ?
        """, (series_key, latest_date))
        vol_row = cursor.fetchone()
        vol = {k: (vol_row[k] if vol_row else 0) for k in
               ("call_volume", "put_volume", "total_volume", "call_oi", "put_oi", "total_oi")}

        cursor.execute("""
            INSERT OR REPLACE INTO put_call_latest
                (series, date, ratio, call_volume, put_volume, total_volume,
                 call_oi, put_oi, total_oi, ma5, ma20, ma50, z_score, signal, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            series_key, latest_date, latest_ratio,
            vol["call_volume"], vol["put_volume"], vol["total_volume"],
            vol["call_oi"], vol["put_oi"], vol["total_oi"],
            ma5, ma20, ma50, z_score, signal,
        ))

    conn.commit()


def _safe_ma(values: List[float], period: int) -> Optional[float]:
    """Simple moving average over the last `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _zscore(values: List[float], period: int) -> Optional[float]:
    """Z-score of latest value vs period-day mean/std."""
    if len(values) < period + 2:
        return None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    std = variance ** 0.5
    if std == 0:
        return None
    return (values[-1] - mean) / std


def _classify_signal(ratio: Optional[float], z_score: Optional[float]) -> str:
    """Classify the put/call ratio reading.

    High PCR = more puts → bearish sentiment (contrarian buy)
    Low PCR  = more calls → bullish complacency (contrarian sell)
    """
    if ratio is None:
        return "NEUTRAL"

    if z_score is not None and abs(z_score) >= 2.0:
        return "EXTREME_HIGH" if z_score > 0 else "EXTREME_LOW"

    if ratio >= PCR_HIGH_THRESHOLD:
        return "HIGH"
    if ratio <= PCR_LOW_THRESHOLD:
        return "LOW"
    return "NEUTRAL"


async def ingest_date_async(target_date: date) -> Dict[str, Any]:
    """Download and ingest a single date."""
    data = await download_daily_data(target_date)
    if data is None:
        return {"date": str(target_date), "status": "no_data"}

    with get_db() as conn:
        try:
            return ingest_date(conn, target_date, data)
        except Exception as e:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ingestion_log_pcr (date, status, error_message) VALUES (?, 'failed', ?)",
                (target_date, str(e)),
            )
            conn.commit()
            return {"date": str(target_date), "status": "failed", "error": str(e)}


async def ingest_latest() -> Dict[str, Any]:
    """Find and ingest the most recent available date."""
    latest_date = get_latest_available_date()
    if latest_date is None:
        return {"status": "no_data", "error": "No recent CBOE data found"}

    # Check if already ingested
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM put_call_ratio WHERE date = ? LIMIT 1", (latest_date,))
        if cursor.fetchone():
            return {"status": "already_ingested", "date": str(latest_date)}

    result = await ingest_date_async(latest_date)
    result["source"] = "CBOE"
    return result


async def backfill(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """Backfill a date range."""
    results = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # business days only
            print(f"Ingesting {current}...")
            data = await download_daily_data(current)
            if data:
                with get_db() as conn:
                    result = ingest_date(conn, current, data)
                    results.append(result)
                    print(f"  {result['rows_inserted']} series ingested")
            else:
                results.append({"date": str(current), "status": "no_data"})
                print(f"  no data")
            current += timedelta(days=1)
        else:
            current += timedelta(days=1)
    return results

"""
Data ingestion pipeline for FINRA short interest data
"""
import asyncio
import httpx
import pandas as pd
from io import StringIO
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
import json
import sqlite3

from .config import DB_PATH, FINRA_CDN_BASE, WATCHLIST_PATH
from .db import get_db, init_db

# Load watchlist
with open(WATCHLIST_PATH, "r") as f:
    WATCHLIST = json.load(f)

ALL_TICKERS = set(WATCHLIST["all_tickers"])
CATEGORIES = WATCHLIST["categories"]

def get_category(symbol: str) -> str:
    """Get category for a symbol"""
    for cat, tickers in CATEGORIES.items():
        if symbol in tickers:
            return cat
    return "other"

def get_finra_settlement_dates(start_date: date, end_date: date) -> List[date]:
    """Generate FINRA settlement dates (15th and month-end) in range"""
    dates = []
    current = start_date.replace(day=1)
    
    while current <= end_date:
        # 15th of month (or previous business day)
        d15 = current.replace(day=15)
        if d15.weekday() >= 5:  # Weekend
            d15 = d15 - timedelta(days=d15.weekday() - 4)
        if start_date <= d15 <= end_date:
            dates.append(d15)
        
        # Month-end (last business day)
        if current.month == 12:
            next_month = current.replace(year=current.year+1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month+1, day=1)
        month_end = next_month - timedelta(days=1)
        if month_end.weekday() >= 5:
            month_end = month_end - timedelta(days=month_end.weekday() - 4)
        if start_date <= month_end <= end_date:
            dates.append(month_end)
        
        current = next_month
    
    return sorted(set(dates))

async def download_finra_csv(settlement_date: date) -> Optional[pd.DataFrame]:
    """Download FINRA CSV for a settlement date"""
    date_str = settlement_date.strftime("%Y%m%d")
    url = f"{FINRA_CDN_BASE}/shrt{date_str}.csv"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
    except Exception as e:
        print(f"Error downloading {date_str}: {e}")
        return None
    
    try:
        df = pd.read_csv(StringIO(resp.text), sep='|')
        df.columns = [c.strip() for c in df.columns]
        
        # Convert numeric columns
        numeric_cols = [
            'currentShortPositionQuantity', 'previousShortPositionQuantity', 
            'averageDailyVolumeQuantity', 'daysToCoverQuantity', 
            'changePercent', 'changePreviousNumber'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Normalize symbol
        df['symbolCode'] = df['symbolCode'].str.upper().str.strip()
        df['settlementDate'] = pd.to_datetime(df['settlementDate']).dt.date
        
        return df
    except Exception as e:
        print(f"Error parsing CSV for {date_str}: {e}")
        return None

def ingest_settlement_date(conn: sqlite3.Connection, settlement_date: date, df: pd.DataFrame) -> Dict[str, Any]:
    """Ingest one settlement date's data for watchlist tickers only"""
    cursor = conn.cursor()
    
    # Log start
    cursor.execute("""
        INSERT INTO ingestion_log_si (settlement_date, total_rows, status)
        VALUES (?, ?, 'started')
    """, (settlement_date, len(df)))
    log_id = cursor.lastrowid
    conn.commit()
    
    # Filter to watchlist
    watchlist_df = df[df['symbolCode'].isin(ALL_TICKERS)].copy()
    watchlist_count = len(watchlist_df)
    
    new_rows = 0
    updated_rows = 0
    
    for _, row in watchlist_df.iterrows():
        symbol = row['symbolCode']
        
        # Check if exists
        cursor.execute("""
            SELECT id FROM short_interest 
            WHERE symbol = ? AND settlement_date = ?
        """, (symbol, settlement_date))
        existing = cursor.fetchone()
        
        data = {
            'symbol': symbol,
            'settlement_date': settlement_date,
            'issue_name': row.get('issueName'),
            'exchange': row.get('issuerServicesGroupExchangeCode'),
            'market_class': row.get('marketClassCode'),
            'current_short': int(row['currentShortPositionQuantity']) if pd.notna(row['currentShortPositionQuantity']) else None,
            'previous_short': int(row['previousShortPositionQuantity']) if pd.notna(row['previousShortPositionQuantity']) else None,
            'avg_daily_volume': int(row['averageDailyVolumeQuantity']) if pd.notna(row['averageDailyVolumeQuantity']) else None,
            'days_to_cover': float(row['daysToCoverQuantity']) if pd.notna(row['daysToCoverQuantity']) else None,
            'change_pct': float(row['changePercent']) if pd.notna(row['changePercent']) else None,
            'change_abs': int(row['changePreviousNumber']) if pd.notna(row['changePreviousNumber']) else None,
            'revision_flag': row.get('revisionFlag'),
            'stock_split_flag': row.get('stockSplitFlag'),
        }
        
        if existing:
            cursor.execute("""
                UPDATE short_interest SET
                    issue_name = ?, exchange = ?, market_class = ?,
                    current_short = ?, previous_short = ?, avg_daily_volume = ?,
                    days_to_cover = ?, change_pct = ?, change_abs = ?,
                    revision_flag = ?, stock_split_flag = ?
                WHERE symbol = ? AND settlement_date = ?
            """, (
                data['issue_name'], data['exchange'], data['market_class'],
                data['current_short'], data['previous_short'], data['avg_daily_volume'],
                data['days_to_cover'], data['change_pct'], data['change_abs'],
                data['revision_flag'], data['stock_split_flag'],
                symbol, settlement_date
            ))
            updated_rows += 1
        else:
            cursor.execute("""
                INSERT INTO short_interest (
                    symbol, settlement_date, issue_name, exchange, market_class,
                    current_short, previous_short, avg_daily_volume, days_to_cover,
                    change_pct, change_abs, revision_flag, stock_split_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['symbol'], data['settlement_date'], data['issue_name'],
                data['exchange'], data['market_class'],
                data['current_short'], data['previous_short'], data['avg_daily_volume'],
                data['days_to_cover'], data['change_pct'], data['change_abs'],
                data['revision_flag'], data['stock_split_flag']
            ))
            new_rows += 1
    
    # Update tickers table (unified schema)
    for _, row in watchlist_df.iterrows():
        symbol = row['symbolCode']
        cursor.execute("""
            INSERT OR REPLACE INTO tickers (
                ticker, name, exchange, market_class, category,
                latest_settlement, latest_short, latest_dtc, latest_change_pct, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            symbol,
            row.get('issueName'),
            row.get('issuerServicesGroupExchangeCode'),
            row.get('marketClassCode'),
            get_category(symbol),
            settlement_date,
            int(row['currentShortPositionQuantity']) if pd.notna(row['currentShortPositionQuantity']) else None,
            float(row['daysToCoverQuantity']) if pd.notna(row['daysToCoverQuantity']) else None,
            float(row['changePercent']) if pd.notna(row['changePercent']) else None
        ))
    
    conn.commit()
    
    # Update log
    cursor.execute("""
        UPDATE ingestion_log_si SET
            watchlist_rows = ?, new_rows = ?, updated_rows = ?,
            status = 'completed', completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (watchlist_count, new_rows, updated_rows, log_id))
    conn.commit()
    
    return {
        'settlement_date': str(settlement_date),
        'total_rows': len(df),
        'watchlist_rows': watchlist_count,
        'new_rows': new_rows,
        'updated_rows': updated_rows
    }

async def ingest_date(settlement_date: date) -> Dict[str, Any]:
    """Download and ingest a single settlement date"""
    df = await download_finra_csv(settlement_date)
    if df is None:
        return {'settlement_date': str(settlement_date), 'error': 'No data available'}
    
    with get_db() as conn:
        return ingest_settlement_date(conn, settlement_date, df)

async def backfill(start_date: date, end_date: date) -> List[Dict]:
    """Backfill historical data for a date range"""
    dates = get_finra_settlement_dates(start_date, end_date)
    results = []
    
    for d in dates:
        print(f"Ingesting {d}...")
        result = await ingest_date(d)
        results.append(result)
        if 'error' not in result:
            print(f"  {result['watchlist_rows']} watchlist rows, {result['new_rows']} new, {result['updated_rows']} updated")
        else:
            print(f"  {result['error']}")
    
    return results

async def ingest_latest() -> Dict[str, Any]:
    """Ingest the most recent available settlement date"""
    # Get latest settlement date from FINRA (approximately 7 business days ago)
    # We'll try recent dates until we find one
    today = date.today()
    for i in range(1, 20):
        check_date = today - timedelta(days=i)
        # Only check business days that could be settlement dates
        if check_date.day in [15] or check_date == (check_date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1):
            result = await ingest_date(check_date)
            if 'error' not in result and result['watchlist_rows'] > 0:
                return result
    return {'error': 'No recent data found'}

def sync_watchlist():
    """Sync watchlist JSON to database (unified schema: tickers table)"""
    with get_db() as conn:
        cursor = conn.cursor()
        for cat, tickers in CATEGORIES.items():
            for symbol in tickers:
                cursor.execute("""
                    INSERT OR REPLACE INTO tickers (ticker, category, is_active)
                    VALUES (?, ?, 1)
                """, (symbol, cat))
        conn.commit()
    print(f"Synced {len(ALL_TICKERS)} tickers to watchlist (tickers table)")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m short_interest_scanner.ingest <command> [args]")
        print("Commands:")
        print("  backfill YYYY-MM-DD YYYY-MM-DD  - Backfill date range")
        print("  latest                          - Ingest latest available")
        print("  sync-watchlist                  - Sync watchlist to DB")
        print("  dates YYYY-MM-DD YYYY-MM-DD     - List settlement dates in range")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "backfill":
        start = date.fromisoformat(sys.argv[2])
        end = date.fromisoformat(sys.argv[3])
        init_db()
        sync_watchlist()
        asyncio.run(backfill(start, end))
    
    elif cmd == "latest":
        init_db()
        sync_watchlist()
        result = asyncio.run(ingest_latest())
        print(json.dumps(result, indent=2, default=str))
    
    elif cmd == "sync-watchlist":
        init_db()
        sync_watchlist()
    
    elif cmd == "dates":
        start = date.fromisoformat(sys.argv[2])
        end = date.fromisoformat(sys.argv[3])
        dates = get_finra_settlement_dates(start, end)
        for d in dates:
            print(d)
    
    else:
        print(f"Unknown command: {cmd}")

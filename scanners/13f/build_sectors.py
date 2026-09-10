#!/usr/bin/env python3
"""
Build GICS sector mapping for all tickers in the 13F database.
Uses yfinance to fetch sector/industry data.
"""
import sqlite3
import time
from pathlib import Path
import sys

import yfinance as yf

DB_PATH = Path(r"C:\Users\cho_i\purrtfolio.db")

def create_sector_table(conn):
    """Create the sectors table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sectors (
            ticker TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT,
            market_cap BIGINT,
            currency TEXT,
            country TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("✓ Created sectors table")

def get_tickers_to_map(conn):
    """Get all unique tickers from holdings that don't have sector mapping yet."""
    rows = conn.execute("""
        SELECT DISTINCT h.ticker
        FROM holdings h
        LEFT JOIN sectors s ON h.ticker = s.ticker
        WHERE h.ticker IS NOT NULL 
          AND h.ticker != ''
          AND s.ticker IS NULL
        ORDER BY h.ticker
    """).fetchall()
    return [r[0] for r in rows]

def fetch_sector_data(ticker):
    """Fetch sector/industry from yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {
            'sector': info.get('sector'),
            'industry': info.get('industry'),
            'market_cap': info.get('marketCap'),
            'currency': info.get('currency'),
            'country': info.get('country'),
        }
    except Exception as e:
        return {'error': str(e)}

def main():
    print("=" * 60)
    print("  Building GICS Sector Mapping")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    create_sector_table(conn)
    
    tickers = get_tickers_to_map(conn)
    print(f"Found {len(tickers)} tickers needing sector mapping")
    
    if not tickers:
        print("All tickers already mapped!")
        return
    
    batch_size = 100
    success = 0
    failed = 0
    
    for i, ticker in enumerate(tickers):
        if i % batch_size == 0 and i > 0:
            conn.commit()
            print(f"  Progress: {i}/{len(tickers)} - Success: {success}, Failed: {failed}")
            time.sleep(1)  # Rate limiting
        
        data = fetch_sector_data(ticker)
        
        if 'error' in data:
            failed += 1
            if failed <= 5:
                print(f"  ✗ {ticker}: {data['error']}")
            continue
        
        if data.get('sector') or data.get('industry'):
            conn.execute("""
                INSERT OR REPLACE INTO sectors 
                (ticker, sector, industry, market_cap, currency, country, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                ticker,
                data.get('sector'),
                data.get('industry'),
                data.get('market_cap'),
                data.get('currency'),
                data.get('country'),
            ))
            success += 1
        else:
            failed += 1
        
        # Small delay to be respectful
        time.sleep(0.1)
    
    conn.commit()
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"  Complete!")
    print(f"  Success: {success}")
    print(f"  Failed:  {failed}")
    print(f"  Total:   {len(tickers)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
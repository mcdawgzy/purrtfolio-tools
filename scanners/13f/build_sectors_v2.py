#!/usr/bin/env python3
"""
Build GICS sector mapping for top tickers by total portfolio value.
Focuses on the most impactful holdings.
"""
import sqlite3
import time
from pathlib import Path
import sys

import yfinance as yf

DB_PATH = Path(r"C:\Users\cho_i\purrtfolio.db")

def create_sector_table(conn):
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

def get_top_tickers(conn, min_total_value=1_000_000_000):
    """Get tickers with at least $1B total across all funds."""
    rows = conn.execute("""
        SELECT h.ticker, SUM(h.market_value_usd) as total_value
        FROM holdings h
        LEFT JOIN sectors s ON h.ticker = s.ticker
        WHERE h.ticker IS NOT NULL 
          AND h.ticker != ''
          AND s.ticker IS NULL
        GROUP BY h.ticker
        HAVING total_value >= ?
        ORDER BY total_value DESC
    """, (min_total_value,)).fetchall()
    return [(r[0], r[1]) for r in rows]

def fetch_sector_data(ticker):
    """Fetch sector/industry from yfinance with better error handling."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        # Handle None values
        sector = info.get('sector')
        industry = info.get('industry')
        
        # ETFs often don't have sector/industry, use fund family or category
        if not sector and not industry:
            fund_family = info.get('fundFamily')
            category = info.get('category')
            if fund_family:
                sector = f"ETF - {fund_family}"
            elif category:
                sector = f"ETF - {category}"
        
        return {
            'sector': sector,
            'industry': industry,
            'market_cap': info.get('marketCap'),
            'currency': info.get('currency'),
            'country': info.get('country'),
        }
    except Exception as e:
        return {'error': str(e)}

def main():
    print("=" * 60)
    print("  Building GICS Sector Mapping (Top Holdings Only)")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    create_sector_table(conn)
    
    # Start with $1B threshold
    threshold = 1_000_000_000
    tickers = get_top_tickers(conn, threshold)
    
    # If too few, lower threshold
    while len(tickers) < 500 and threshold > 10_000_000:
        threshold //= 10
        tickers = get_top_tickers(conn, threshold)
    
    print(f"Mapping {len(tickers)} tickers with >= ${threshold/1e9:.1f}B total value")
    
    success = 0
    failed = 0
    batch_size = 50
    
    for i, (ticker, total_value) in enumerate(tickers):
        if i % batch_size == 0 and i > 0:
            conn.commit()
            print(f"  Progress: {i}/{len(tickers)} - Success: {success}, Failed: {failed}")
            time.sleep(0.5)
        
        data = fetch_sector_data(ticker)
        
        if 'error' in data:
            failed += 1
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
        
        time.sleep(0.05)
    
    conn.commit()
    
    # Final stats
    total_mapped = conn.execute('SELECT COUNT(*) FROM sectors').fetchone()[0]
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"  Complete!")
    print(f"  New mapped: {success}")
    print(f"  Failed:     {failed}")
    print(f"  Total in DB: {total_mapped}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
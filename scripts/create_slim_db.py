#!/usr/bin/env python
"""Create a slim momentum DB (price_history + corr_matrices + tickers)
from the full DB.

This smaller DB (~1-2MB compressed) allows the Render web service to
download it quickly on cold start instead of the 67MB full DB.
"""
import sqlite3
import gzip
import shutil
import os
from pathlib import Path

SRC_DB = Path("C:/Users/cho_i/purrtfolio.db")
DST_DB = Path("C:/Users/cho_i/13f-scanner-web/scanners/price_momentum/momentum_data.db")
DST_GZ = DST_DB.with_suffix(".db.gz")

# Tickers to include in the slim DB (must match CURATED_TICKERS in config)
WATCHLIST_TICKERS = [
    "^GSPC", "^NDX", "^DJI", "^RUT",
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "AVGO", "ASML", "AMD", "INTC", "CRM", "ADBE", "NFLX", "ORCL",
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW",
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY",
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY",
    "WMT", "HD", "PG", "KO", "PEP", "COST", "NKE", "MCD",
    "^N225", "^GDAXI", "^FTSE", "^STOXX", "^HSI",
    "DX-Y.NYB", "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X",
    "^IRX", "^FVX", "^TNX", "^TYX",
    "GC=F", "SI=F", "CL=F", "BZ=F", "HG=F",
    "HYG", "LQD", "TIP", "^VIX",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO",
    "BTC-USD", "ETH-USD",
]

TABLES_FULL_COPY = [
    "price_history",
    "price_momentum_signals",
    "corr_matrices",
    "ticker_short_meta",
]

if __name__ == "__main__":
    if DST_DB.exists():
        DST_DB.unlink()

    conn = sqlite3.connect(str(DST_DB))
    conn.execute(f"ATTACH DATABASE '{SRC_DB}' AS src")

    # Full table copies
    for table in TABLES_FULL_COPY:
        schema = conn.execute(
            "SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        if not schema:
            print(f"Table {table} not found in source, skipping")
            continue
        print(f"Copying {table}...")
        conn.execute(schema[0])
        conn.execute(f"INSERT INTO {table} SELECT * FROM src.{table}")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {count} rows")

    # Filtered copy: tickers (all tickers that appear in momentum signals)
    schema = conn.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='table' AND name='tickers'"
   ).fetchone()
    if schema:
        print("Copying tickers (filtered to momentum tickers)...")
        conn.execute(schema[0])
        # All tickers that appear in price_history or price_momentum_signals
        sig_ticks = conn.execute("SELECT DISTINCT ticker FROM src.price_momentum_signals").fetchall()
        all_ticks = set(r[0] for r in sig_ticks)
        # Also include watchlist tickers
        all_ticks.update(WATCHLIST_TICKERS)
        placeholders = ",".join("?" * len(all_ticks))
        conn.execute(
            f"INSERT INTO tickers SELECT * FROM src.tickers WHERE ticker IN ({placeholders})",
            list(all_ticks)
        )
        count = conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
        print(f"  {count} rows")

    conn.commit()
    conn.close()

    # Compress
    with open(DST_DB, "rb") as f_in, gzip.open(str(DST_GZ), "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    print(f"\nSlim DB: {os.path.getsize(DST_DB) / 1e6:.1f}MB")
    print(f"Compressed: {os.path.getsize(DST_GZ) / 1e6:.1f}MB")

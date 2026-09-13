#!/usr/bin/env python
"""Create a slim momentum DB (price_history + corr_matrices only) from the full DB.

This smaller DB (~10-15MB compressed vs 67MB for the full DB) allows the
Render web service to download it quickly on cold start.
"""
import sqlite3
import gzip
import shutil
import os
from pathlib import Path

SRC_DB = Path("C:/Users/cho_i/purrtfolio.db")
DST_DB = Path("C:/Users/cho_i/13f-scanner-web/scanners/price_momentum/momentum_data.db")
DST_GZ = DST_DB.with_suffix(".db.gz")

tables_to_copy = [
    "price_history",
    "price_momentum_signals",
    "corr_matrices",
]

if __name__ == "__main__":
    # Create slim DB by ATTACHing the source and copying specific tables
    if DST_DB.exists():
        DST_DB.unlink()
    
    conn = sqlite3.connect(str(DST_DB))
    conn.execute(f"ATTACH DATABASE '{SRC_DB}' AS src")
    
    for table in tables_to_copy:
        # Get the schema
        schema = conn.execute(
            "SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        if not schema:
            print(f"Table {table} not found in source DB, skipping")
            continue
        print(f"Copying {table}...")
        conn.execute(schema[0])
        # Copy data
        conn.execute(f"INSERT INTO {table} SELECT * FROM src.{table}")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {count} rows")
    
    conn.commit()
    conn.close()
    
    # Compress
    with open(DST_DB, "rb") as f_in, gzip.open(DST_GZ, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    
    print(f"\nSlim DB: {os.path.getsize(DST_DB) / 1e6:.1f}MB")
    print(f"Compressed: {os.path.getsize(DST_GZ) / 1e6:.1f}MB")

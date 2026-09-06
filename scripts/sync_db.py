#!/usr/bin/env python3
"""
Sync purrtfolio.db to Render's persistent disk or Turso.
Run this after the quarterly 13F ingestion completes on the local machine.
"""
import os, shutil, sqlite3, argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Source DB path (e.g. ~/purrtfolio.db)")
    parser.add_argument("--dest", required=True, help="Destination DB path on Render")
    args = parser.parse_args()

    src = Path(args.source).expanduser()
    dst = Path(args.dest)
    
    if not src.exists():
        print(f"ERROR: Source not found: {src}")
        return 1
    
    # Verify source is healthy
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    counts = {
        "funds": conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0],
        "holdings": conn.execute("SELECT COUNT(*) FROM holdings_13f").fetchone()[0],
        "changes": conn.execute("SELECT COUNT(*) FROM holding_changes_13f").fetchone()[0],
    }
    conn.close()
    print(f"Source DB: {counts}")
    
    # Copy (atomic via temp)
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = dst.with_suffix(".tmp")
    shutil.copy2(src, temp)
    temp.replace(dst)
    print(f"Copied {src} -> {dst} ({dst.stat().st_size/1e6:.1f}MB)")
    return 0

if __name__ == "__main__":
    exit(main())

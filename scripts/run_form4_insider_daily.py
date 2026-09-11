#!/usr/bin/env python3
"""
Cron pipeline for Form 4 insider trading data ingestion.

Called by Hermes cron job. Downloads the latest SEC Insider Transactions
Data Set chunk files and ingests Form 3/4/5 transactions for the watchlist.
Uses the canonical unified database (purrtfolio.db).

Cron spec: At 06:00 UTC daily
"""
import sys
import os
from pathlib import Path

# Ensure the scanners package is importable
SCRIPT_DIR = Path(__file__).resolve().parent  # .../scripts/
PROJECT_ROOT = SCRIPT_DIR.parent               # .../13f-scanner-web/
SCANNER_DIR = PROJECT_ROOT / "scanners" / "form4_insider_trading"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCANNER_DIR))

from form4_insider_trading.main import main

if __name__ == "__main__":
    # DB path — can be overridden by cron engine via --db
    db_path = os.environ.get("PURRTFOLIO_DB", os.path.expanduser("c:\\Users\\cho_i\\purrtfolio.db"))
    sys.argv = [sys.argv[0]] + ["--db", db_path, "run"]
    main()

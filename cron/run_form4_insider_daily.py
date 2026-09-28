#!/usr/bin/env python
"""Hermes cron entry point: run Form 4 insider trading scanner daily ingestion check.

Delegates to form4_insider_trading.main.run(), which:
  1. Initializes the DB (idempotent)
  2. Syncs the ticker watchlist
  3. Checks the SEC Insider Transactions Data Sets for new quarterly data
  4. Ingests any new Form 3/4/5 transactions for the curated watchlist
  5. Returns a dict with status / processed tickers / summary

Usage:
  python run_form4_insider_daily.py        # run via Hermes cron
  python run_form4_insider_daily.py --json # print full JSON result
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the scanners package importable when run from any cwd
sys.path.insert(0, str(REPO / "scanners"))

from form4_insider_trading.main import run  # noqa: E402


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    try:
        result = run()
    except Exception as e:
        print(f"Status: error")
        print(f"Error: {e}")
        return 1

    status = result.get("status", "unknown")
    if emit_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Status: {status}")
        if status == "no_new_data":
            print("New transactions: 0")
        elif status == "completed":
            processed = result.get("processed_tickers", 0)
            new_records = result.get("new_records", 0)
            print(f"Processed: {processed} ticker(s), {new_records} new insider trades")
            for r in result.get("results", []):
                if "error" in r:
                    print(f"  {r.get('ticker', '?')}: FAILED ({r['error']})")
                else:
                    print(f"  {r.get('ticker')}: {r.get('new', 0)} new, {r.get('updated', 0)} updated")
        elif status == "error":
            print(f"Error: {result.get('error')}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

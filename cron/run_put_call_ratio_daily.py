#!/usr/bin/env python
"""Hermes cron entry point: run CBOE put/call ratio scanner daily ingestion check.

Delegates to put_call_ratio.scheduler.run_once(), which:
  1. Initializes the DB schema (idempotent)
  2. Finds the most recent business date with CBOE data not yet in DB
  3. Downloads + parses the daily JSON from https://cdn.cboe.com/...
  4. Stores ratio + volume/OI for all series (TOTAL, INDEX, EQUITY, ETP, VIX, etc.)
  5. Recomputes 5/20/50-day MAs, z-scores, and sentiment signals
  6. Returns a dict with status / date / rows processed

Usage:
  python run_put_call_ratio_daily.py          # run via Hermes cron
  python run_put_call_ratio_daily.py --json   # print full JSON result
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the package importable when run from any cwd (Hermes runs from its own workdir)
sys.path.insert(0, str(REPO / "scanners"))

from put_call_ratio.scheduler import run_once  # noqa: E402


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    try:
        result = run_once()
    except Exception as e:
        print("Status: error")
        print(f"Error: {e}")
        return 1

    status = result.get("status", "unknown")
    if emit_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Status: {status}")
        if status == "no_new_data":
            print(f"Latest in DB: {result.get('latest_in_db', 'unknown')}")
        elif status == "completed":
            d = result.get("date", "unknown")
            rows = result.get("result", {}).get("rows_inserted", 0)
            print(f"Date: {d} — {rows} series ingested")
        elif status == "error":
            print(f"Error: {result.get('error')}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

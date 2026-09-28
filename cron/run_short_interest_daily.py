#!/usr/bin/env python
"""Hermes cron entry point: run short interest scanner daily ingestion check.

Delegates to short_interest_scanner.scheduler.run_once(), which:
  1. Initializes the DB (idempotent)
  2. Syncs the watchlist into the tickers table
  3. Discovers FINRA bi-weekly settlement dates published ~7 business days ago
  4. Ingests any missing dates for the curated watchlist
  5. Returns a dict with status / processed dates / per-date results

Usage:
  python run_short_interest_daily.py        # run via Hermes cron
  python run_short_interest_daily.py --json # print full JSON result
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the package importable when run from any cwd (Hermes runs from its own workdir)
sys.path.insert(0, str(REPO / "scanners"))

from short_interest_scanner.scheduler import run_once  # noqa: E402


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    try:
        result = run_once()
    except Exception as e:  # pragma: no cover - surfaced to cron delivery
        print(f"Status: error")
        print(f"Error: {e}")
        return 1

    status = result.get("status", "unknown")
    if emit_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Status: {status}")
        if status == "no_new_data":
            print("Pending dates: 0")
        elif status == "completed":
            processed = result.get("processed", 0)
            print(f"Processed: {processed} settlement date(s)")
            for r in result.get("results", []):
                if "error" in r:
                    print(f"  {r.get('settlement_date')}: FAILED ({r['error']})")
                else:
                    print(
                        f"  {r['settlement_date']}: "
                        f"{r['watchlist_rows']} watchlist rows "
                        f"({r['new_rows']} new, {r['updated_rows']} updated)"
                    )
        elif status == "error":
            print(f"Error: {result.get('error')}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
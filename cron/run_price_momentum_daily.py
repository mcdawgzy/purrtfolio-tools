#!/usr/bin/env python
"""Hermes cron entry point: run price momentum ingestion daily.

Delegates to price_momentum.ingest.run_once(), which:
  1. Initializes the DB schemas (idempotent)
  2. Fetches 90 days of daily OHLCV for the ~50-ticker momentum watchlist
  3. Computes momentum signals (ROC, SMA, volume ratio, consolidation, gaps)
  4. Upserts bars + signals into purrtfolio.db

Usage:
  python run_price_momentum_daily.py        # run via Hermes cron
  python run_price_momentum_daily.py --json # print full JSON result
  python run_price_momentum_daily.py --dry  # dry run, no DB writes
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the scanners package importable when run from any cwd (Hermes runs from
# its own workdir; our script lives under ~/AppData/Local/hermes/scripts/)
sys.path.insert(0, str(REPO / "scanners"))

from price_momentum.ingest import run_once  # noqa: E402


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    dry_run = "--dry" in sys.argv[1:]

    try:
        result = run_once(dry_run=dry_run)
    except Exception as e:
        print(f"Status: error")
        print(f"Error: {e}")
        return 1

    status = result.get("status", "unknown")
    if emit_json or dry_run:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Status: {status}")
        print(f"Tickers processed: {result.get('tickers_processed', 0)}")
        print(f"Bars written: {result.get('bars_written', 0)}")
        print(f"Signals written: {result.get('signals_written', 0)}")
        if result.get("errors"):
            for err in result["errors"][:5]:
                print(f"  {err.get('ticker', '?')}: {err.get('error', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

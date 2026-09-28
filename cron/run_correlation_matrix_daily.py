#!/usr/bin/env python
"""Hermes cron entry point: run correlation matrix computation daily.

Delegates to correlation_matrix.ingest.run_once(), which:
  1. Initializes the corr_matrices table (idempotent)
  2. Loads daily adj_close prices from price_history (populated by the
     price momentum scanner)
  3. Computes rolling Pearson correlations (1mo/3mo/6mo/1yr) for all
     watchlist tickers vs asset-class pivot tickers
  4. Upserts results into corr_matrices in purrtfolio.db

Usage:
  python run_correlation_matrix_daily.py        # via Hermes cron
  python run_correlation_matrix_daily.py --json # full JSON result
  python run_correlation_matrix_daily.py --dry  # dry run, no DB writes
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the scanners package importable when run from any cwd
sys.path.insert(0, str(REPO / "scanners"))

from correlation_matrix.ingest import run_once  # noqa: E402


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
        print(f"Signal date: {result.get('signal_date', 'N/A')}")
        print(f"Total rows written: {result.get('total_rows', 0)}")
        print(f"Window sets: {result.get('windows_computed', 0)}")
        print(f"Target tickers: {result.get('target_tickers', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

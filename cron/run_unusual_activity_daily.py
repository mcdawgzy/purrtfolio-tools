#!/usr/bin/env python3
"""
Cron entry point for Unusual Activity Scanner.

Scheduled daily at 06:00 UTC+10 (same window as Put/Call Ratio, Short Interest).
Fetches options chain data from yfinance for watchlist tickers and detects
unusual options activity based on volume/open-interest spikes and notional.

The --script flag in the Hermes cron engine resolves this file by name
via a shim in ~/AppData/Local/hermes/scripts/ (see cron/README.md).
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys

SCANNERS_DIR = str(REPO / "scanners")
if SCANNERS_DIR not in sys.path:
    sys.path.insert(0, SCANNERS_DIR)

from unusual_activity.scheduler import run_once


if __name__ == "__main__":
    result = run_once()
    print(result)
    sys.exit(0)  # Do not fail the cron even on partial errors — error is logged

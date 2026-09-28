#!/usr/bin/env python3
"""
Cron entry point for IV Rank Scanner.

Scheduled daily at 06:00 UTC+10 (same window as Put/Call Ratio and
Short Interest cron jobs). Fetches ATM implied volatility from yfinance
for all watchlist tickers and computes 52-week IV Rank / IV Percentile.

The --script flag in the Hermes cron engine resolves this file by name
via a shim in ~/AppData/Local/hermes/scripts/ (see cron/README.md).
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys

REPO_DIR = str(REPO)  # scanners is a package under the repo root
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from scanners.implied_volatility.scheduler import run_once


if __name__ == "__main__":
    result = run_once()
    print(result)
    sys.exit(0)  # Do not fail the cron even on partial errors — error is logged

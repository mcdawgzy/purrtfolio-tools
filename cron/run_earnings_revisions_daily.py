#!/usr/bin/env python3
"""
Cron entry point for Earnings Revision Momentum scanner.

Scheduled daily at 05:30 UTC+10 (after market close on US exchanges).
Fetches yfinance earnings history for watchlist tickers and computes
revision momentum scores, storing results in purrtfolio.db.

The --script flag in the Hermes cron engine resolves this file by name
via a shim in ~/AppData/Local/hermes/scripts/ (see cron/README.md).
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import json
import logging
import sys


REPO_DIR = str(REPO)  # scanners is a package under the repo root
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("earnings_revisions")


def run_once():
    """Fetch earnings data for all watchlist tickers and update momentum scores."""
    from scanners.earnings_revisions.ingest import run_once as _run
    result = _run()
    logger.info(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    try:
        result = run_once()
        print(json.dumps(result, indent=2))
        sys.exit(0)  # Do not fail the cron — error is logged
    except Exception as e:
        logger.error(f"Earnings revisions ingestion failed: {e}", exc_info=True)
        sys.exit(0)  # Always exit 0 — error is logged, no retry storms

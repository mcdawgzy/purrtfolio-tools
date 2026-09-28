#!/usr/bin/env python3
"""
Cron entry point for Famous Trader Quotes initialization.

Seeds the trader_quotes table with ~50 curated quotes from famous investors
and traders. Runs daily to catch new additions; INSERT OR IGNORE prevents
duplicates. The logic lives in scanners/trader_quotes/seed.py.

Scheduled: daily at 03:00 UTC+10 (early window, before market open).
Hermes resolves this file by name via a shim in ~/AppData/Local/hermes/scripts/
(see cron/README.md).
"""
import json
import logging
import sys
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("trader_quotes")


if __name__ == "__main__":
    try:
        from scanners.trader_quotes.seed import run_once

        result = run_once()
        print(json.dumps(result, indent=2))
        sys.exit(0)  # Do not fail the cron — error is logged
    except Exception as e:
        logger.error(f"Trader quotes initialization failed: {e}", exc_info=True)
        sys.exit(0)  # Always exit 0 — error is logged, no retry storms

#!/usr/bin/env python3
"""
Cron entry point for Famous Trader Quotes initialization.

Seeds the trader_quotes table with ~50 curated quotes from famous investors
and traders. Runs daily to catch new additions; INSERT OR IGNORE prevents
duplicates.

Scheduled: daily at 03:00 UTC+10 (early window, before market open).
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


SCANNERS_DIR = str(REPO / "scanners")
if SCANNERS_DIR not in sys.path:
    sys.path.insert(0, SCANNERS_DIR)

SRC_DIR = str(REPO / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("trader_quotes")

SEED_FILE = str(REPO / "scanners" / "trader_quotes" / "quotes_seed.json")


def run_once():
    """Initialize the trader_quotes table and seed it with curated quotes."""
    from db import init_trader_quotes, get_trader_quote_categories

    # 1. Create table
    init_trader_quotes()
    logger.info("trader_quotes table initialized (CREATE IF NOT EXISTS)")

    # 2. Load seed data
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        quotes = json.load(f)

    # 3. Insert quotes (idempotent via INSERT OR IGNORE on a unique key)
    import sqlite3
    db_path = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))
    conn = sqlite3.connect(str(db_path))

    inserted = 0
    for q in quotes:
        cur = conn.execute(
            "INSERT OR IGNORE INTO trader_quotes (author, quote, category, source) "
            "VALUES (?, ?, ?, ?)",
            (q["author"], q["quote"], q.get("category", ""), q.get("source", "")),
        )
        inserted += cur.rowcount

    conn.commit()

    # 4. Verify
    total = conn.execute("SELECT COUNT(*) FROM trader_quotes").fetchone()[0]
    cats = get_trader_quote_categories()
    conn.close()

    logger.info(f"Seeded {inserted} new quotes ({total} total)")
    logger.info(f"Categories: {', '.join(cats)}")
    return {
        "inserted": inserted,
        "total": total,
        "categories": len(cats),
    }


if __name__ == "__main__":
    try:
        result = run_once()
        print(json.dumps(result, indent=2))
        sys.exit(0)  # Do not fail the cron — error is logged
    except Exception as e:
        logger.error(f"Trader quotes initialization failed: {e}", exc_info=True)
        sys.exit(0)  # Always exit 0 — error is logged, no retry storms

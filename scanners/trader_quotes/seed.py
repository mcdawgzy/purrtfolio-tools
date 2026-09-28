"""Create the trader_quotes table and seed it from quotes_seed.json (idempotent).

    python -m scanners.trader_quotes
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..common import DB_PATH, connect

SEED_FILE = Path(__file__).resolve().parent / "quotes_seed.json"
logger = logging.getLogger("trader_quotes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trader_quotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    author        TEXT    NOT NULL,
    quote         TEXT    NOT NULL,
    category      TEXT,
    source        TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trader_quotes_category ON trader_quotes(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trader_quotes_unique ON trader_quotes(author, quote);
"""


def run_once(db_path: Path = DB_PATH) -> dict:
    """Create the table (if needed) and insert any quotes not already present."""
    quotes = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        inserted = 0
        for q in quotes:
            cur = conn.execute(
                "INSERT OR IGNORE INTO trader_quotes (author, quote, category, source) "
                "VALUES (?, ?, ?, ?)",
                (q["author"], q["quote"], q.get("category", ""), q.get("source", "")),
            )
            inserted += cur.rowcount
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM trader_quotes").fetchone()[0]
        cats = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM trader_quotes "
            "WHERE category IS NOT NULL AND category != '' ORDER BY category")]
    finally:
        conn.close()
    logger.info(f"Seeded {inserted} new quotes ({total} total)")
    logger.info(f"Categories: {', '.join(cats)}")
    return {"inserted": inserted, "total": total, "categories": len(cats)}

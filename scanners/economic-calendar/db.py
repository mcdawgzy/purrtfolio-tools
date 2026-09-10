"""Database layer for the Economic Calendar scanner.

Mirrors scanners/short_interest_scanner/db.py — SQLite with connection
context managers, write access for ingest.  The canonical DB is
purrtfolio.db (shared with 13F + SI scanners).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config import DB_PATH

logger = logging.getLogger("econ-cal-db")

# Schema is defined inline so init_db() is self-contained and idempotent.
TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS economic_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date   DATE    NOT NULL,           -- calendar date (UTC)
    event_time   TEXT,                       -- HH:MM 24h (UTC)
    event_name   TEXT    NOT NULL,           -- e.g. "US Non-Farm Payrolls"
    category     TEXT    NOT NULL,           -- "US Economics", "FOMC", "ECB", etc.
    impact       TEXT    NOT NULL,           -- "high" | "medium" | "low"
    actual       TEXT,                       -- actual value (post-release)
    prior        TEXT,                       -- previous value
    forecast     TEXT,                       -- consensus forecast
    timezone_id  TEXT,                       -- e.g. "America/New_York"
    source       TEXT,                       -- "FOMC", "Finnhub", "ECB", etc.
    url          TEXT,                       -- source URL if available
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_date, event_time, event_name, category)
) WITHOUT ROWID -- using event_date as rowid prefix
""".replace("WITHOUT ROWID", "")  # keep standard table for simplicity

# Re-declare without WITHOUT ROWID
TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS economic_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date   DATE    NOT NULL,
    event_time   TEXT,
    event_name   TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    impact       TEXT    NOT NULL DEFAULT 'high',
    actual       TEXT,
    prior        TEXT,
    forecast     TEXT,
    timezone_id  TEXT,
    source       TEXT,
    url          TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_date, event_time, event_name, category)
)
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_econ_event_date   ON economic_events(event_date);
CREATE INDEX IF NOT EXISTS idx_econ_category     ON economic_events(category);
CREATE INDEX IF NOT EXISTS idx_econ_impact       ON economic_events(impact);
CREATE INDEX IF NOT EXISTS idx_econ_source       ON economic_events(source);
CREATE INDEX IF NOT EXISTS idx_econ_is_upcoming  ON economic_events(event_date) 
    WHERE impact = 'high';
"""


def init_db(db_path: Path | str | None = None) -> None:
    """Create the economic_events table + indexes if they don't exist."""
    db_path = Path(db_path) if db_path else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(TABLE_SCHEMA)
        conn.executescript(INDEX_SCHEMA)
        conn.commit()
        logger.info(f"DB initialised at {db_path}")
    finally:
        conn.close()


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Writeable connection context manager (for ingest)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_event(
    event_date: str,
    event_time: str | None,
    event_name: str,
    category: str,
    impact: str = "high",
    actual: str | None = None,
    prior: str | None = None,
    forecast: str | None = None,
    timezone_id: str | None = None,
    source: str | None = None,
    url: str | None = None,
) -> int:
    """Insert or update an economic event. Returns the row id."""
    with db_conn() as c:
        row = c.execute(
            """
            INSERT INTO economic_events 
                (event_date, event_time, event_name, category, impact,
                 actual, prior, forecast, timezone_id, source, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_date, event_time, event_name, category)
            DO UPDATE SET
                impact       = excluded.impact,
                actual       = COALESCE(excluded.actual, economic_events.actual),
                prior        = excluded.prior,
                forecast     = excluded.forecast,
                timezone_id  = COALESCE(excluded.timezone_id, economic_events.timezone_id),
                source       = excluded.source,
                url          = COALESCE(excluded.url, economic_events.url),
                updated_at   = CURRENT_TIMESTAMP
            """,
            (event_date, event_time, event_name, category, impact,
             actual, prior, forecast, timezone_id, source, url),
        )
        return c.total_changes

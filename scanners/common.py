"""Shared paths and SQLite helpers for every scanner.

All scanners write to one SQLite file, ``purrtfolio.db``:
  - ``PURRTFOLIO_DB`` env var, else ``~/purrtfolio.db``.

Price history / momentum signals / correlations live in the same file on the
cron host. The API on Render reads them from a small extract published with
each DB release (``momentum_data.db``), pointed to by ``MOMENTUM_DB``.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))
MOMENTUM_DB_PATH = Path(os.environ.get("MOMENTUM_DB", DB_PATH))


def connect(path: Path | str = DB_PATH, *, readonly: bool = False,
            timeout: float = 30) -> sqlite3.Connection:
    """Open a connection with Row factory; read-only uses SQLite URI mode."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(str(path), timeout=timeout)
        conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# Tables shared by several scanners. Created here, once, so the schema doesn't
# depend on which scanner happens to run first against a fresh database.
SHARED_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    ticker        TEXT PRIMARY KEY,
    name          TEXT,
    cik           TEXT,           -- Company CIK (for SEC cross-ref)
    exchange      TEXT,           -- 'NMS', 'NYSE', 'ARCA', 'NNM', etc.
    market_class  TEXT,           -- FINRA market class code
    sector        TEXT,           -- GICS sector
    industry      TEXT,           -- GICS industry
    category      TEXT,           -- Our watchlist category (mega_cap_tech, biotech, etc.)
    is_etf        BOOLEAN DEFAULT 0,
    is_active     BOOLEAN DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    shares_outstanding BIGINT,
    free_float_shares  BIGINT
);

CREATE TABLE IF NOT EXISTS sectors (
    ticker       TEXT PRIMARY KEY,
    sector       TEXT,
    industry     TEXT,
    market_cap   BIGINT,
    currency     TEXT,
    country      TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_shared_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SHARED_SCHEMA)

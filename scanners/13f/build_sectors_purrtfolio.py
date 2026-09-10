#!/usr/bin/env python3
"""
Ensure the `sectors` table exists in the unified purrtfolio.db used by the
quarterly cron. The legacy `13f_scanner.db` has 49 manually-curated sector
mappings; this script copies them into purrtfolio.db so the Excel export's
sector-aggregation query (export.export_sector_analysis) has data to work with.

Run from anywhere; safe to re-run (idempotent).
"""
import sqlite3
import sys
from pathlib import Path

PURRTFOLIO_DB = Path(r"C:\Users\cho_i\purrtfolio.db")
LEGACY_DB = Path(r"C:\Users\cho_i\13f-scanner-web\scanners\13f\data\13f_scanner.db")


def ensure_sectors_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sectors (
            ticker TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT,
            market_cap BIGINT,
            currency TEXT,
            country TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def copy_from_legacy(conn: sqlite3.Connection) -> int:
    """Copy (ticker, sector, industry) rows from 13f_scanner.db.sectors if present."""
    if not LEGACY_DB.exists():
        print(f"  legacy DB not found at {LEGACY_DB}; skipping copy")
        return 0
    legacy = sqlite3.connect(str(LEGACY_DB))
    try:
        rows = legacy.execute(
            "SELECT ticker, sector, industry FROM sectors WHERE sector IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        print("  legacy DB has no sectors table; skipping copy")
        legacy.close()
        return 0

    inserted = 0
    for ticker, sector, industry in rows:
        if not ticker:
            continue
        cur = conn.execute(
            """
            INSERT INTO sectors (ticker, sector, industry, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ticker) DO UPDATE SET
                sector = excluded.sector,
                industry = excluded.industry,
                last_updated = CURRENT_TIMESTAMP
            """,
            (ticker, sector, industry),
        )
        if cur.rowcount > 0:
            inserted += 1
    legacy.close()
    conn.commit()
    return inserted


def main() -> int:
    if not PURRTFOLIO_DB.exists():
        print(f"ERROR: {PURRTFOLIO_DB} not found", file=sys.stderr)
        return 1

    print(f"Target DB: {PURRTFOLIO_DB}")
    conn = sqlite3.connect(str(PURRTFOLIO_DB))
    try:
        ensure_sectors_table(conn)
        copied = copy_from_legacy(conn)
        total = conn.execute("SELECT COUNT(*) FROM sectors").fetchone()[0]
        by_sector = conn.execute(
            "SELECT sector, COUNT(*) FROM sectors "
            "WHERE sector IS NOT NULL GROUP BY sector ORDER BY 2 DESC"
        ).fetchall()
    finally:
        conn.close()

    print(f"  copied from legacy: {copied}")
    print(f"  total sectors rows in purrtfolio.db: {total}")
    print("  by sector:")
    for sector, n in by_sector:
        print(f"    {sector}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
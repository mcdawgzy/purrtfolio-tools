#!/usr/bin/env python3
"""
Enrich tickers with GICS sector/industry data for the unified purrtfolio.db.

This script:
  1. Finds tickers in holdings_13f (latest quarter) that lack sector data in the
     `tickers` table, prioritized by total AUM (largest positions first)
  2. Fetches sector/industry from yfinance
  3. Updates the `tickers` table's sector/industry columns in-place
  4. Also populates the `sectors` table for cross-referencing

Run via cron after each quarterly 13F ingestion, or standalone:
  python enrich_sectors.py --db C:\\Users\\cho_i\\purrtfolio.db
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import yfinance as yf

DEFAULT_DB = Path(r"C:\Users\cho_i\purrtfolio.db")


def get_latest_quarter(conn: sqlite3.Connection) -> str | None:
    """Return the most recent report_period with infotable data."""
    row = conn.execute(
        "SELECT MAX(report_period) FROM filings_13f WHERE has_infotable=1"
    ).fetchone()
    return row[0] if row else None


def get_tickers_needing_sector(conn: sqlite3.Connection, limit: int = 0) -> list[str]:
    """Get tickers from holdings_13f missing sector data, prioritized by AUM.

    Uses the latest quarter's holdings to rank by total market value — we want
    sector coverage on the biggest positions first, since the rotation view
    is value-weighted.
    """
    latest_q = get_latest_quarter(conn)
    sql = """
        SELECT h.ticker, SUM(h.market_value_usd) AS total_aum
        FROM holdings_13f h
        JOIN tickers t ON h.ticker = t.ticker
        WHERE h.ticker IS NOT NULL
          AND h.ticker != ''
          AND h.put_call = ''
          AND (t.sector IS NULL OR t.sector = '')
    """
    params = []
    if latest_q:
        sql += " AND h.report_period = ?"
        params.append(latest_q)
    sql += " GROUP BY h.ticker ORDER BY total_aum DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


def get_tickers_with_sector(conn: sqlite3.Connection) -> dict[str, str]:
    """Get existing sector mappings from tickers table for reference."""
    rows = conn.execute("""
        SELECT ticker, sector, industry
        FROM tickers
        WHERE sector IS NOT NULL AND sector != ''
    """).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def fetch_sectors_batch(tickers: list[str]) -> dict[str, tuple]:
    """Fetch sector/industry for a batch of tickers via yfinance.

    Returns {ticker: (sector, industry)} for successful lookups.
    """
    results = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info
            sector = info.get("sector")
            industry = info.get("industry")
            if sector or industry:
                results[ticker] = (sector or "", industry or "")
        except Exception as e:
            print(f"  ✗ {ticker}: {e}", file=sys.stderr)
        time.sleep(0.05)  # be respectful to yfinance
    return results


def update_tickers_sector(conn: sqlite3.Connection, sector_map: dict[str, tuple]) -> int:
    """Update tickers table with sector/industry data. Returns count of rows updated."""
    updated = 0
    for ticker, (sector, industry) in sector_map.items():
        cur = conn.execute("""
            UPDATE tickers
            SET sector = ?, industry = ?, updated_at = CURRENT_TIMESTAMP
            WHERE ticker = ?
        """, (sector, industry, ticker))
        if cur.rowcount > 0:
            updated += 1
    conn.commit()
    return updated


def sync_sectors_table(conn: sqlite3.Connection, sector_map: dict[str, tuple]) -> int:
    """Also write to the dedicated sectors table for cross-referencing."""
    inserted = 0
    for ticker, (sector, industry) in sector_map.items():
        conn.execute("""
            INSERT INTO sectors (ticker, sector, industry, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ticker) DO UPDATE SET
                sector = excluded.sector,
                industry = excluded.industry,
                last_updated = CURRENT_TIMESTAMP
        """, (ticker, sector, industry))
        inserted += 1
    conn.commit()
    return inserted


def ensure_sectors_table(conn: sqlite3.Connection):
    """Create sectors table if it doesn't exist (unified schema)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sectors (
            ticker TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT,
            market_cap BIGINT,
            currency TEXT,
            country TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Enrich tickers with GICS sector data")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to purrtfolio.db")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit tickers to process (0 = all unmatched)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    ensure_sectors_table(conn)

    existing = get_tickers_with_sector(conn)
    print(f"  Already have sector for {len(existing)} tickers")

    latest_q = get_latest_quarter(conn)
    print(f"  Latest quarter with filing data: {latest_q}")

    tickers = get_tickers_needing_sector(conn, limit=args.limit if args.limit else 0)
    print(f"  {len(tickers)} tickers need sector mapping")

    if not tickers:
        print("  All tickers already mapped!")
        conn.close()
        return

    # Process in batches of 50 (yfinance can be slow, keep batches manageable)
    batch_size = 50
    total_updated = 0
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  Processing batch {i//batch_size + 1}: {len(batch)} tickers...")
        sector_map = fetch_sectors_batch(batch)
        n = update_tickers_sector(conn, sector_map)
        n_sectors = sync_sectors_table(conn, sector_map)
        total_updated += n
        print(f"    {n} tickers updated ({n_sectors} written to sectors table)")
        time.sleep(1)  # rate limiting between batches

    conn.commit()

    # Summary
    final = conn.execute(
        "SELECT COUNT(*) FROM tickers WHERE sector IS NOT NULL AND sector != ''"
    ).fetchone()[0]
    total_tickers = conn.execute("SELECT COUNT(*) FROM tickers").fetchone()[0]
    sectors = conn.execute("SELECT COUNT(*) FROM sectors WHERE sector IS NOT NULL").fetchone()[0]

    # AUM coverage improvement
    latest = get_latest_quarter(conn)
    if latest:
        total_aum = conn.execute(
            "SELECT SUM(h.market_value_usd) FROM holdings_13f h WHERE h.report_period=? AND h.put_call=''",
            (latest,)
        ).fetchone()[0] or 0
        sector_aum = conn.execute("""
            SELECT SUM(h.market_value_usd)
            FROM holdings_13f h
            JOIN tickers t ON h.ticker = t.ticker
            WHERE h.report_period = ?
              AND h.put_call = ''
              AND t.sector IS NOT NULL AND t.sector != ''
        """, (latest,)).fetchone()[0] or 0
        coverage = sector_aum / total_aum * 100 if total_aum else 0
        print(f"  AUM coverage ({latest}): ${sector_aum:,.0f} / ${total_aum:,.0f} = {coverage:.1f}%")

    print(f"\n✓ Done! {total_updated} tickers enriched.")
    print(f"  tickers table: {final}/{total_tickers} ({final/total_tickers*100:.1f}% with sector)")
    print(f"  sectors table: {sectors} rows")

    conn.close()


if __name__ == "__main__":
    main()

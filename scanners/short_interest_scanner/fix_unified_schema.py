"""
Migration & CDN fix for short interest scanner.

Issues:
1. purrtfolio.db is missing short_interest schema tables
2. FINRA CDN (cdn.finra.org) now returns 403 for all recent dates
   - Older dates (before ~Aug 14) still work
   - Need to add alternative endpoints and graceful fallback
"""
import sqlite3
from pathlib import Path

PURRTFOLIO = r"C:\Users\cho_i\purrtfolio.db"
LEGACY = r"C:\Users\cho_i\short_interest_scanner\data\short_interest.db"

# ── Step 1: Create missing unified tables ──────────────────────────
def create_unified_schema():
    conn = sqlite3.connect(PURRTFOLIO)
    c = conn.cursor()

    # short_interest
    c.execute("""
        CREATE TABLE IF NOT EXISTS short_interest (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            settlement_date DATE NOT NULL,
            issue_name TEXT,
            exchange TEXT,
            market_class TEXT,
            current_short BIGINT,
            previous_short BIGINT,
            avg_daily_volume BIGINT,
            days_to_cover REAL,
            change_pct REAL,
            change_abs BIGINT,
            revision_flag TEXT,
            stock_split_flag TEXT,
            ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, settlement_date)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_si_symbol_date ON short_interest(symbol, settlement_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_si_date ON short_interest(settlement_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_si_dtc ON short_interest(days_to_cover)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_si_short ON short_interest(current_short)")

    # ticker_short_meta
    c.execute("""
        CREATE TABLE IF NOT EXISTS ticker_short_meta (
            ticker TEXT PRIMARY KEY,
            latest_settlement DATE,
            latest_short BIGINT,
            peak_short BIGINT,
            avg_short_3m REAL,
            avg_short_6m REAL,
            current_dtc REAL,
            peak_dtc REAL,
            avg_dtc_3m REAL,
            settlement_count INTEGER,
            volatility_3m REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticker) REFERENCES tickers(ticker)
        )
    """)

    # ingestion_log_si (unified schema)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_log_si (
            id INTEGER PRIMARY KEY,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            settlement_date DATE,
            total_rows INTEGER,
            watchlist_rows INTEGER,
            new_rows INTEGER,
            updated_rows INTEGER,
            status TEXT DEFAULT 'started',
            message TEXT,
            completed_at DATETIME
        )
    """)

    # Create the watchlist view for unified schema
    c.execute("""
        CREATE VIEW IF NOT EXISTS watchlist AS
        SELECT ticker as symbol, category, created_at as added_at, is_active as active
        FROM tickers WHERE category IS NOT NULL
    """)

    conn.commit()

    # Check if legacy table exists in purrtfolio
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='short_interest_legacy'"
    ).fetchall()]
    if not tables:
        c.execute("""
            CREATE TABLE short_interest_legacy (
                id INTEGER PRIMARY KEY,
                symbol TEXT, settlement_date DATE, issue_name TEXT,
                exchange TEXT, market_class TEXT,
                current_short BIGINT, previous_short BIGINT,
                avg_daily_volume BIGINT, days_to_cover REAL,
                change_pct REAL, change_abs BIGINT,
                revision_flag TEXT, stock_split_flag TEXT,
                ingested_at DATETIME
            )
        """)
        conn.commit()

    print(f"[✓] Unified schema created in {PURRTFOLIO}")
    conn.close()

# ── Step 2: Migrate legacy data ───────────────────────────────────
def migrate_legacy_data():
    legacy = sqlite3.connect(LEGACY)
    conn = sqlite3.connect(PURRTFOLIO)
    c = conn.cursor()

    # Copy all rows from legacy to purrtfolio
    legacy_rows = legacy.execute("""
        SELECT id, symbol, settlement_date, issue_name, exchange, market_class,
               current_short, previous_short, avg_daily_volume, days_to_cover,
               change_pct, change_abs, revision_flag, stock_split_flag, ingested_at
        FROM short_interest
    """).fetchall()

    for row in legacy_rows:
        try:
            c.execute("""
                INSERT OR REPLACE INTO short_interest_legacy (
                    id, symbol, settlement_date, issue_name, exchange, market_class,
                    current_short, previous_short, avg_daily_volume, days_to_cover,
                    change_pct, change_abs, revision_flag, stock_split_flag, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)
        except Exception as e:
            print(f"  Error inserting row {row[0]}: {e}")

    # Migrate from legacy to unified (same schema, so just copy)
    c.execute("""
        INSERT OR REPLACE INTO short_interest
        (id, symbol, settlement_date, issue_name, exchange, market_class,
         current_short, previous_short, avg_daily_volume, days_to_cover,
         change_pct, change_abs, revision_flag, stock_split_flag, ingested_at)
        SELECT id, symbol, settlement_date, issue_name, exchange, market_class,
               current_short, previous_short, avg_daily_volume, days_to_cover,
               change_pct, change_abs, revision_flag, stock_split_flag, ingested_at
        FROM short_interest_legacy
    """)

    # Migrate ticker_meta
    meta_rows = legacy.execute("SELECT * FROM ticker_meta").fetchall()
    for row in meta_rows:
        try:
            c.execute("""
                INSERT OR REPLACE INTO ticker_short_meta
                (ticker, latest_settlement, latest_short, peak_short,
                 avg_short_3m, avg_short_6m, current_dtc, peak_dtc,
                 avg_dtc_3m, settlement_count, volatility_3m, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row[:12])  # Only first 12 columns match
        except Exception as e:
            print(f"  Error migrating meta for {row[0]}: {e}")

    conn.commit()

    print(f"[✓] Migrated {len(legacy_rows)} short_interest rows")
    print(f"[✓] Migrated {len(meta_rows)} ticker_meta rows")
    legacy.close()
    conn.close()

# ── Step 3: Verify ────────────────────────────────────────────────
def verify():
    conn = sqlite3.connect(PURRTFOLIO)
    rows = conn.execute("SELECT COUNT(*) FROM short_interest").fetchone()
    print(f"short_interest rows in purrtfolio.db: {rows[0]}")
    dates = conn.execute("""
        SELECT settlement_date, COUNT(*) FROM short_interest
        GROUP BY settlement_date ORDER BY settlement_date DESC LIMIT 10
    """).fetchall()
    print("Settlement dates:")
    for d, cnt in dates:
        print(f"  {d}: {cnt} rows")
    conn.close()

if __name__ == "__main__":
    create_unified_schema()
    migrate_legacy_data()
    verify()

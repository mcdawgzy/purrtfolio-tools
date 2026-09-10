"""Fix ticker_short_meta migration with correct column mapping."""
import sqlite3

PURRTFOLIO = r"C:\Users\cho_i\purrtfolio.db"
LEGACY = r"C:\Users\cho_i\short_interest_scanner\data\short_interest.db"

legacy = sqlite3.connect(LEGACY)
conn = sqlite3.connect(PURRTFOLIO)
c = conn.cursor()

# Unified ticker_short_meta columns:
# symbol, latest_settlement, latest_short, latest_dtc, latest_change_pct,
# peak_short, peak_short_date, peak_dtc, avg_short_12m, updated_at
# Legacy ticker_meta columns:
# symbol, name, exchange, market_class, category, latest_settlement, latest_short,
# latest_dtc, latest_change_pct, updated_at
# Map by position with NULLs for missing unified columns

legacy_rows = legacy.execute("""
    SELECT symbol, latest_settlement, latest_short, latest_dtc, latest_change_pct,
           NULL as peak_short, NULL as peak_short_date, NULL as peak_dtc,
           NULL as avg_short_12m, updated_at
    FROM ticker_meta
""").fetchall()

migrated = 0
for row in legacy_rows:
    c.execute("""
        INSERT OR REPLACE INTO ticker_short_meta
        (symbol, latest_settlement, latest_short, latest_dtc, latest_change_pct,
         peak_short, peak_short_date, peak_dtc, avg_short_12m, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
    migrated += 1

conn.commit()
print(f"[✓] Migrated {migrated} ticker_meta rows")

# Verify
verified = conn.execute("SELECT COUNT(*) FROM ticker_short_meta").fetchone()[0]
print(f"[✓] ticker_short_meta now has {verified} rows")

# Check sample
sample = conn.execute("SELECT * FROM ticker_short_meta LIMIT 3").fetchall()
print("\nSample rows:")
for row in sample:
    print(f"  {row[0]}: settlement={row[1]} short={row[2]} dtc={row[3]}")

legacy.close()
conn.close()

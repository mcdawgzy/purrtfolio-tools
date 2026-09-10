"""Check current short interest DB state."""
import sqlite3, os
from datetime import date, timedelta

db = os.path.join(os.environ['LOCALAPPDATA'], 'purrtfolio.db')
conn = sqlite3.connect(db)

# Settlement dates
rows = conn.execute(
    "SELECT settlement_date, COUNT(*) FROM short_interest "
    "GROUP BY settlement_date ORDER BY settlement_date DESC"
).fetchall()
print("Settlement dates in DB:")
for r in rows:
    print(f"  {r[0]}: {r[1]} rows")

r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM short_interest").fetchone()
print(f"\nDistinct symbols: {r[0]}")

r = conn.execute(
    "SELECT id, settlement_date, status, new_rows, updated_rows, message "
    "FROM ingestion_log_si ORDER BY id DESC LIMIT 10"
).fetchall()
print("\nRecent ingestion logs:")
for r in r:
    print(f"  #{r[0]} {r[1]} status={r[2]} new={r[3]} updated={r[4]} msg={r[5]}")

# Next expected settlement date
today = date.today()
print(f"\nToday: {today}")
# FINRA settlement: 15th or month-end (business day adjusted)
candidates = []
for m in range(today.month, today.month + 3):
    y = today.year + (m // 12)
    mo = (m % 12) + 1
    # 15th
    d15 = date(y, mo, 15)
    if d15.weekday() >= 5:
        d15 -= timedelta(days=d15.weekday() - 4)
    if d15 >= date(today.year, today.month, 1) and d15 <= date(today.year, today.month + 2 if mo == 12 else mo, 28):
        candidates.append(d15)
    # Month end
    if mo == 12:
        next_m = date(y + 1, 1, 1)
    else:
        next_m = date(y, mo + 1, 1)
    me = next_m - timedelta(days=1)
    if me.weekday() >= 5:
        me -= timedelta(days=me.weekday() - 4)
    candidates.append(me)
candidates = sorted(set(d for d in candidates if d > today))
if candidates:
    print(f"Next expected settlement date: {candidates[0]}")

conn.close()

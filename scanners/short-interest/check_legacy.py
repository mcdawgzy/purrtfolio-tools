"""Check legacy short interest DB state."""
import sqlite3
db = r'C:\Users\cho_i\short_interest_scanner\data\short_interest.db'
conn = sqlite3.connect(db)
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Legacy DB tables:', [t[0] for t in tables])

# Try both table names
for tbl in ('short_interest', 'short_interest_old'):
    try:
        rows = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
        print(f'{tbl} rows: {rows[0]}')
        # Check columns
        cols = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
        print(f'  Columns: {[c[1] for c in cols]}')
        # Latest date
        try:
            dates = conn.execute(f"SELECT settlement_date, COUNT(*) FROM {tbl} GROUP BY settlement_date ORDER BY settlement_date DESC LIMIT 5").fetchall()
            print(f'  Dates: {dates}')
        except Exception as e:
            print(f'  Date query error: {e}')
    except Exception as e:
        print(f'{tbl} error: {e}')

conn.close()

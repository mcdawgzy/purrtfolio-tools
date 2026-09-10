import sqlite3

conn = sqlite3.connect('C:/Users/cho_i/purrtfolio.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", tables)

cursor.execute("SELECT cik, name FROM funds")
funds = cursor.fetchall()
print(f"Funds: {len(funds)}")
for f in funds[:15]:
    print(f)

cursor.execute("SELECT COUNT(*) FROM holdings")
holdings_count = cursor.fetchone()[0]
print(f"Holdings count: {holdings_count}")

cursor.execute("SELECT COUNT(*) FROM filings")
filings_count = cursor.fetchone()[0]
print(f"Filings count: {filings_count}")

cursor.execute("SELECT * FROM holding_changes LIMIT 5")
changes = cursor.fetchall()
print(f"Holding changes sample: {changes}")

conn.close()
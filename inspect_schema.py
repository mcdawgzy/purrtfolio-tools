import urllib.request, tempfile, sqlite3, os
url = "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-05/purrtfolio.db"
tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
print("Downloading from:", url)
urllib.request.urlretrieve(url, tmp)
print("Downloaded size:", os.path.getsize(tmp))
conn = sqlite3.connect(tmp)
c = conn.cursor()
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)
for t in ['short_interest', 'tickers', 'ticker_short_meta', 'ingestion_log_si', 'alerts']:
    if t in tables:
        cols = c.execute(f'PRAGMA table_info({t})').fetchall()
        print(f'\n=== {t} ===')
        for col in cols:
            print(f'  {col[1]} {col[2]}')
# samples
for t in ['short_interest', 'tickers', 'ticker_short_meta']:
    if t in tables:
        rows = c.execute(f'SELECT * FROM {t} LIMIT 1').fetchall()
        cols = [d[0] for d in c.description]
        print(f'\n--- {t} sample --- cols:', cols)
conn.close()
os.unlink(tmp)

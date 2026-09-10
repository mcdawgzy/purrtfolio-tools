import sqlite3
conn = sqlite3.connect('C:/Users/cho_i/purrtfolio.db')
conn.row_factory = sqlite3.Row

q = '''
SELECT f.name, f.cik, f.strategy, COUNT(fil.accession_number) as filing_count, 
       GROUP_CONCAT(fil.report_period) as periods
FROM funds f
LEFT JOIN filings fil ON f.cik = fil.fund_cik
GROUP BY f.name, f.cik, f.strategy
ORDER BY filing_count DESC, f.name
'''

for row in conn.execute(q):
    if row['filing_count'] > 0:
        print(f"{row['name']:50s} {row['cik']:15s} {row['strategy']:20s} {row['filing_count']} filings  {row['periods']}")

conn.close()
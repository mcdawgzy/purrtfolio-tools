import sqlite3
conn = sqlite3.connect('C:/Users/cho_i/purrtfolio.db')
conn.row_factory = sqlite3.Row

star_funds = ['Berkshire Hathaway Inc', 'Baupost Group LLC', 'Renaissance Technologies LLC', 'Citadel Advisors LLC', 'Bridgewater Associates LP', 'D. E. Shaw & Co LP']
ph = ','.join('?' * len(star_funds))

q = f'''
SELECT f.name, hc.ticker, hc.issuer_name, hc.curr_value_usd
FROM holding_changes hc
JOIN funds f ON hc.fund_cik = f.cik
WHERE hc.curr_report_period = '2026-06-30'
  AND hc.prev_report_period = '2026-03-31'
  AND hc.status = 'NEW'
  AND f.name IN ({ph})
ORDER BY hc.curr_value_usd DESC
'''

for row in conn.execute(q, star_funds):
    print(f'{row["name"]} | {row["ticker"]} | {row["issuer_name"]} | ${row["curr_value_usd"]/1e9:.1f}B')
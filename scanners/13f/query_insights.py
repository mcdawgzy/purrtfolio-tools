import sqlite3

conn = sqlite3.connect('C:/Users/cho_i/purrtfolio.db')
c = conn.cursor()

notable = ['0001067983','0001336528','0001061768','0001037389','0001423053','0001350694','0001167483','0001584941','0001471057','0001627049']
placeholders = ','.join('?'*len(notable))

# NEW positions by notable funds (>$50M)
query = f'''
SELECT f.name, hc.ticker, hc.issuer_name, hc.curr_value_usd, hc.curr_shares
FROM holding_changes hc
JOIN funds f ON f.cik = hc.fund_cik
WHERE hc.curr_report_period = "2026-06-30" 
  AND hc.prev_report_period = "2026-03-31"
  AND hc.status = "NEW"
  AND hc.fund_cik IN ({placeholders})
  AND hc.curr_value_usd >= 50000000
ORDER BY hc.curr_value_usd DESC
LIMIT 40
'''
c.execute(query, notable)
results = c.fetchall()
print('=== NOTABLE FUNDS: NEW POSITIONS >$50M (Q2 2026) ===')
for r in results:
    print(f'{r[0]:30} {r[1]:8} {r[2][:40]:40} ${r[3]/1e6:.0f}M ({r[4]:,} sh)')

print()

# CLOSED positions by notable funds (>$50M)
query2 = f'''
SELECT f.name, hc.ticker, hc.issuer_name, hc.prev_value_usd, hc.prev_shares
FROM holding_changes hc
JOIN funds f ON f.cik = hc.fund_cik
WHERE hc.curr_report_period = "2026-06-30" 
  AND hc.prev_report_period = "2026-03-31"
  AND hc.status = "CLOSED"
  AND hc.fund_cik IN ({placeholders})
  AND hc.prev_value_usd >= 50000000
ORDER BY hc.prev_value_usd DESC
LIMIT 40
'''
c.execute(query2, notable)
results = c.fetchall()
print('=== NOTABLE FUNDS: FULL EXITS >$50M (Q2 2026) ===')
for r in results:
    print(f'{r[0]:30} {r[1]:8} {r[2][:40]:40} ${r[3]/1e6:.0f}M ({r[4]:,} sh)')

print()

# Largest INCREASED positions (>50% increase, >$100M value)
query3 = f'''
SELECT f.name, hc.ticker, hc.issuer_name, hc.prev_value_usd, hc.curr_value_usd,
       (hc.curr_value_usd - hc.prev_value_usd) / hc.prev_value_usd * 100 as pct_change
FROM holding_changes hc
JOIN funds f ON f.cik = hc.fund_cik
WHERE hc.curr_report_period = "2026-06-30" 
  AND hc.prev_report_period = "2026-03-31"
  AND hc.status = "INCREASED"
  AND hc.fund_cik IN ({placeholders})
  AND hc.prev_value_usd >= 100000000
  AND hc.curr_value_usd >= 100000000
  AND (hc.curr_value_usd - hc.prev_value_usd) / hc.prev_value_usd > 0.5
ORDER BY pct_change DESC
LIMIT 20
'''
c.execute(query3, notable)
results = c.fetchall()
print('=== NOTABLE FUNDS: LARGE INCREASES >50% (Q2 2026) ===')
for r in results:
    print(f'{r[0]:30} {r[1]:8} {r[2][:35]:35} ${r[3]/1e6:.0f}M -> ${r[4]/1e6:.0f}M (+{r[5]:.1f}%)')

print()

# Largest DECREASED positions (>50% decrease, >$100M prev value)
query4 = f'''
SELECT f.name, hc.ticker, hc.issuer_name, hc.prev_value_usd, hc.curr_value_usd,
       (hc.prev_value_usd - hc.curr_value_usd) / hc.prev_value_usd * 100 as pct_change
FROM holding_changes hc
JOIN funds f ON f.cik = hc.fund_cik
WHERE hc.curr_report_period = "2026-06-30" 
  AND hc.prev_report_period = "2026-03-31"
  AND hc.status = "DECREASED"
  AND hc.fund_cik IN ({placeholders})
  AND hc.prev_value_usd >= 100000000
  AND (hc.prev_value_usd - hc.curr_value_usd) / hc.prev_value_usd > 0.5
ORDER BY pct_change DESC
LIMIT 20
'''
c.execute(query4, notable)
results = c.fetchall()
print('=== NOTABLE FUNDS: LARGE DECREASES >50% (Q2 2026) ===')
for r in results:
    print(f'{r[0]:30} {r[1]:8} {r[2][:35]:35} ${r[3]/1e6:.0f}M -> ${r[4]/1e6:.0f}M (-{r[5]:.1f}%)')

conn.close()
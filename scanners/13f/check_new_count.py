import sqlite3
conn = sqlite3.connect('C:/Users/cho_i/purrtfolio.db')
q = "SELECT COUNT(*) FROM holding_changes WHERE curr_report_period = '2026-06-30' AND prev_report_period = '2026-03-31' AND status = 'NEW'"
print(conn.execute(q).fetchone())
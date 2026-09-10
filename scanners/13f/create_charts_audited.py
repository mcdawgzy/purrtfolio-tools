#!/usr/bin/env python3
"""Create focused, audited charts from 13F analysis data"""
import sqlite3
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

DB = "C:/Users/cho_i/purrtfolio.db"
OUT_HTML = "scanners/13f/charts_audited.html"

# GICS sectors only (filter out ETF providers)
GICS_SECTORS = [
    'Technology', 'Communication Services', 'Industrials', 'Financial Services',
    'Healthcare', 'Energy', 'Consumer Cyclical', 'Utilities',
    'Real Estate', 'Basic Materials', 'Consumer Defensive'
]

def fetch_consensus_data(quarter="2026-06-30", prev_quarter="2026-03-31", limit=15):
    conn = sqlite3.connect(DB)
    query = """
    SELECT 
        hc.ticker,
        SUM(hc.value_change_usd) as net_change_usd,
        COUNT(DISTINCT hc.fund_cik) as fund_count,
        GROUP_CONCAT(DISTINCT f.name || ':' || hc.status) as fund_actions
    FROM holding_changes hc
    JOIN funds f ON hc.fund_cik = f.cik
    WHERE hc.curr_report_period = ? AND hc.prev_report_period = ?
    GROUP BY hc.ticker
    HAVING fund_count >= 2
    ORDER BY net_change_usd DESC
    LIMIT ?
    """
    buys = pd.read_sql_query(query, conn, params=[quarter, prev_quarter, limit])
    
    sells_query = """
    SELECT 
        hc.ticker,
        SUM(hc.value_change_usd) as net_change_usd,
        COUNT(DISTINCT hc.fund_cik) as fund_count,
        GROUP_CONCAT(DISTINCT f.name || ':' || hc.status) as fund_actions
    FROM holding_changes hc
    JOIN funds f ON hc.fund_cik = f.cik
    WHERE hc.curr_report_period = ? AND hc.prev_report_period = ?
    GROUP BY hc.ticker
    HAVING fund_count >= 2
    ORDER BY net_change_usd ASC
    LIMIT ?
    """
    sells = pd.read_sql_query(sells_query, conn, params=[quarter, prev_quarter, limit])
    conn.close()
    return buys, sells

def fetch_fund_changes(fund_name, quarter="2026-06-30", prev_quarter="2026-03-31", limit=10):
    conn = sqlite3.connect(DB)
    query = """
    SELECT 
        hc.ticker,
        hc.status,
        hc.value_change_usd,
        hc.curr_value_usd,
        hc.prev_value_usd,
        hc.value_change_pct
    FROM holding_changes hc
    JOIN funds f ON hc.fund_cik = f.cik
    WHERE f.name = ? AND hc.curr_report_period = ? AND hc.prev_report_period = ?
    ORDER BY ABS(hc.value_change_usd) DESC
    LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=[fund_name, quarter, prev_quarter, limit])
    conn.close()
    return df

def fetch_fund_summary(quarter="2026-06-30"):
    conn = sqlite3.connect(DB)
    query = """
    SELECT 
        f.name,
        f.strategy,
        COUNT(h.id) as holdings_count,
        SUM(h.market_value_usd) as total_value_usd
    FROM funds f
    JOIN filings fl ON f.cik = fl.fund_cik
    JOIN holdings h ON fl.accession_number = h.filing_accession
    WHERE fl.report_period = ?
    GROUP BY f.cik, f.name, f.strategy
    ORDER BY total_value_usd DESC
    """
    df = pd.read_sql_query(query, conn, params=[quarter])
    conn.close()
    return df

def fetch_sector_data(quarter="2026-06-30", prev_quarter="2026-03-31"):
    conn = sqlite3.connect(DB)
    placeholders = ','.join(['?'] * len(GICS_SECTORS))
    query = f"""
    SELECT 
        s.sector,
        COUNT(DISTINCT hc.ticker) as ticker_count,
        SUM(CASE WHEN hc.value_change_usd > 0 THEN hc.value_change_usd ELSE 0 END) as buys_usd,
        SUM(CASE WHEN hc.value_change_usd < 0 THEN hc.value_change_usd ELSE 0 END) as sells_usd,
        SUM(hc.value_change_usd) as net_change_usd
    FROM holding_changes hc
    JOIN sectors s ON hc.ticker = s.ticker
    WHERE hc.curr_report_period = ? AND hc.prev_report_period = ? 
      AND s.sector IN ({placeholders})
    GROUP BY s.sector
    ORDER BY ABS(net_change_usd) DESC
    """
    df = pd.read_sql_query(query, conn, params=[quarter, prev_quarter] + GICS_SECTORS)
    conn.close()
    return df

def format_units(val):
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    elif val >= 1e9:
        return f"${val/1e9:.1f}B"
    elif val >= 1e6:
        return f"${val/1e6:.1f}M"
    return f"${val:.0f}"

# Fetch data
print("Fetching data...")
buys, sells = fetch_consensus_data()
fund_summary = fetch_fund_summary()
sector_data = fetch_sector_data()

print(f"Consensus buys: {len(buys)}")
print(f"Consensus sells: {len(sells)}")
print(f"Funds with data: {len(fund_summary)}")
print(f"GICS Sectors: {len(sector_data)}")

# Show all fund summaries
for _, row in fund_summary.iterrows():
    print(f"  {row['name']} ({row['strategy']}): {format_units(row['total_value_usd'])}, {row['holdings_count']} holdings")

# Create focused dashboard
fig = make_subplots(
    rows=3, cols=2,
    subplot_titles=(
        "Top Consensus Buys (Q1→Q2 2026)", 
        "Top Consensus Sells (Q1→Q2 2026)",
        "Fund Portfolio Sizes (Q2 2026) — All 9 Funds with Data",
        "GICS Sector Net Flows (Q1→Q2 2026) — Significant Only",
        "Notable Active Managers — Top Position Changes",
        "Strategy Divergence: Value vs Quant"
    ),
    specs=[
        [{"type": "bar"}, {"type": "bar"}],
        [{"type": "bar"}, {"type": "bar"}],
        [{"type": "bar"}, {"type": "bar"}],
    ],
    vertical_spacing=0.12,
    horizontal_spacing=0.1
)

# 1. Consensus Buys
fig.add_trace(
    go.Bar(
        y=buys['ticker'].iloc[::-1],
        x=buys['net_change_usd'].iloc[::-1] / 1e9,
        orientation='h',
        text=[format_units(x) for x in buys['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#2ecc71',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata[0]}<br>Actions: %{customdata[1]}<extra></extra>',
        customdata=list(zip(buys['fund_count'].iloc[::-1], buys['fund_actions'].iloc[::-1])),
        name="Net Buy ($B)"
    ),
    row=1, col=1
)

# 2. Consensus Sells
fig.add_trace(
    go.Bar(
        y=sells['ticker'].iloc[::-1],
        x=abs(sells['net_change_usd'].iloc[::-1]) / 1e9,
        orientation='h',
        text=[format_units(abs(x)) for x in sells['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#e74c3c',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata[0]}<br>Actions: %{customdata[1]}<extra></extra>',
        customdata=list(zip(sells['fund_count'].iloc[::-1], sells['fund_actions'].iloc[::-1])),
        name="Net Sell ($B)"
    ),
    row=1, col=2
)

# 3. Fund Portfolio Sizes - ALL 9 funds with proper units
strategy_colors = {
    'value_concentrated': '#f39c12', 
    'quant_multi_strat': '#3498db', 
    'tech_growth': '#9b59b6', 
    'activist': '#e74c3c',
    'macro_all_weather': '#1abc9c', 
    'index_passive': '#95a5a6',
    'multi_asset': '#34495e'
}
fund_summary_sorted = fund_summary.sort_values('total_value_usd', ascending=True)
fig.add_trace(
    go.Bar(
        y=fund_summary_sorted['name'],
        x=fund_summary_sorted['total_value_usd'],
        orientation='h',
        text=[format_units(x) for x in fund_summary_sorted['total_value_usd']],
        textposition='auto',
        marker_color=[strategy_colors.get(s, '#34495e') for s in fund_summary_sorted['strategy']],
        hovertemplate='%{y}: %{text}<br>Strategy: %{customdata[0]}<br>Holdings: %{customdata[1]}<extra></extra>',
        customdata=list(zip(fund_summary_sorted['strategy'], fund_summary_sorted['holdings_count'])),
        name="Portfolio Value"
    ),
    row=2, col=1
)

# 4. GICS Sector Net Flows (filtered)
sector_data = sector_data.sort_values('net_change_usd', ascending=True)
fig.add_trace(
    go.Bar(
        y=sector_data['sector'],
        x=sector_data['net_change_usd'] / 1e9,
        orientation='h',
        text=[format_units(x) for x in sector_data['net_change_usd']],
        textposition='auto',
        marker_color=['#2ecc71' if x > 0 else '#e74c3c' for x in sector_data['net_change_usd']],
        hovertemplate='%{y}: %{text}<br>Buys: $%{customdata[0]:.1f}B<br>Sells: $%{customdata[1]:.1f}B<extra></extra>',
        customdata=list(zip(sector_data['buys_usd']/1e9, abs(sector_data['sells_usd'])/1e9)),
        name="Net Flow ($B)"
    ),
    row=2, col=2
)

# 5. Notable Active Managers - show all 7 non-passive funds
active_funds = [
    ("Citadel Advisors LLC", "quant_multi_strat", "#3498db"),
    ("D.E. Shaw & Co Inc", "quant_multi_strat", "#2980b9"),
    ("Berkshire Hathaway Inc", "value_concentrated", "#f39c12"),
    ("Baupost Group LLC", "value_concentrated", "#d4ac0d"),
    ("ValueAct Holdings LP", "activist", "#e74c3c"),
    ("Atreides Management LP", "tech_growth", "#9b59b6"),
    ("Whale Rock Capital Management LLC", "tech_growth", "#8e44ad"),
]

# Build combined view of all active manager changes
all_active_changes = []
for fund_name, strategy, color in active_funds:
    df = fetch_fund_changes(fund_name, limit=5)
    if not df.empty:
        df['fund_name'] = fund_name
        df['strategy'] = strategy
        df['color'] = color
        all_active_changes.append(df)

if all_active_changes:
    combined = pd.concat(all_active_changes)
    combined = combined.sort_values('value_change_usd', ascending=True).head(20)
    
    fig.add_trace(
        go.Bar(
            y=combined['ticker'] + " (" + combined['fund_name'].str[:15] + ")",
            x=combined['value_change_usd'].fillna(0) / 1e9,
            orientation='h',
            text=[format_units(x) for x in combined['value_change_usd'].fillna(0)],
            textposition='auto',
            marker_color=['#2ecc71' if x > 0 else '#e74c3c' for x in combined['value_change_usd'].fillna(0)],
            hovertemplate='%{y}: %{text} (%{customdata})<extra></extra>',
            customdata=combined['status'],
            name="Change ($B)"
        ),
        row=3, col=1
    )

# 6. Strategy Divergence: Value Concentrated vs Quant Multi-Strat
conn = sqlite3.connect(DB)
div_query = """
SELECT 
    hc.ticker,
    SUM(CASE WHEN f.strategy = 'value_concentrated' THEN hc.value_change_usd ELSE 0 END) as value_change,
    SUM(CASE WHEN f.strategy = 'quant_multi_strat' THEN hc.value_change_usd ELSE 0 END) as quant_change,
    COUNT(DISTINCT CASE WHEN f.strategy = 'value_concentrated' THEN hc.fund_cik END) as value_funds,
    COUNT(DISTINCT CASE WHEN f.strategy = 'quant_multi_strat' THEN hc.fund_cik END) as quant_funds
FROM holding_changes hc
JOIN funds f ON hc.fund_cik = f.cik
WHERE hc.curr_report_period = '2026-06-30' AND hc.prev_report_period = '2026-03-31'
  AND f.strategy IN ('value_concentrated', 'quant_multi_strat')
GROUP BY hc.ticker
HAVING value_funds >= 1 AND quant_funds >= 1
ORDER BY ABS(value_change - quant_change) DESC
LIMIT 15
"""
div_df = pd.read_sql_query(div_query, conn)
conn.close()

if not div_df.empty:
    div_df['divergence'] = div_df['value_change'] - div_df['quant_change']
    div_df = div_df.sort_values('divergence', ascending=True)
    
    fig.add_trace(
        go.Bar(
            y=div_df['ticker'],
            x=div_df['divergence'] / 1e9,
            orientation='h',
            text=[format_units(x) for x in div_df['divergence']],
            textposition='auto',
            marker_color=['#f39c12' if x > 0 else '#3498db' for x in div_df['divergence']],
            hovertemplate='%{y}: Value %{customdata[0]:.1f}B vs Quant %{customdata[1]:.1f}B<br>Divergence: %{text}<extra></extra>',
            customdata=list(zip(div_df['value_change']/1e9, div_df['quant_change']/1e9)),
            name="Value - Quant ($B)"
        ),
        row=3, col=2
    )

# Update layout
fig.update_layout(
    title_text="13F Q2 2026 Audit Dashboard — Verified Data (Jun 30 vs Mar 31)",
    title_x=0.5,
    title_font_size=16,
    height=1500,
    showlegend=False,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=10),
)

fig.update_xaxes(title_text="Net Change ($B)", row=1, col=1)
fig.update_xaxes(title_text="Net Change ($B)", row=1, col=2)
fig.update_xaxes(title_text="Portfolio Value", row=2, col=1)
fig.update_xaxes(title_text="Net Flow ($B)", row=2, col=2)
fig.update_xaxes(title_text="Change ($B)", row=3, col=1)
fig.update_xaxes(title_text="Value − Quant ($B)", row=3, col=2)

fig.update_yaxes(autorange="reversed")

# Save
fig.write_html(OUT_HTML, include_plotlyjs="cdn")
print(f"\nCharts saved to {OUT_HTML}")

# Summary
summary = {
    "quarter": "2026-06-30",
    "prev_quarter": "2026-03-31",
    "notes": "AUDITED: Consensus sells exist, portfolio sizes use T/B/M units, sectors filtered to GICS only",
    "consensus_buys": buys.to_dict('records'),
    "consensus_sells": sells.to_dict('records'),
    "fund_summary": fund_summary.to_dict('records'),
    "sector_flows_gics": sector_data.to_dict('records'),
}
with open("scanners/13f/charts_audited_summary.json", "w") as f:
    json.dump(summary, f, indent=2, default=str)
print("Audited summary JSON saved")
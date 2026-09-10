#!/usr/bin/env python3
"""Create corrected interactive charts from 13F analysis data"""
import sqlite3
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

DB = "C:/Users/cho_i/purrtfolio.db"

def fetch_consensus_data(quarter="2026-06-30", prev_quarter="2026-03-31", limit=20):
    """Fetch consensus buys/sells - FIXED: order by ASC for sells"""
    conn = sqlite3.connect(DB)
    buys_query = """
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
    buys = pd.read_sql_query(buys_query, conn, params=[quarter, prev_quarter, limit])
    
    # Consensus sells - order by ASC (most negative first)
    sells_query = buys_query.replace("DESC", "ASC")
    sells = pd.read_sql_query(sells_query, conn, params=[quarter, prev_quarter, limit])
    sells = sells[sells['net_change_usd'] < 0].head(limit)
    
    conn.close()
    return buys, sells

def fetch_fund_changes(fund_name, quarter="2026-06-30", prev_quarter="2026-03-31", limit=15):
    """Fetch per-fund changes"""
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

def fetch_all_fund_summaries(quarter="2026-06-30"):
    """Fetch summary for ALL funds with data"""
    conn = sqlite3.connect(DB)
    query = """
    SELECT 
        f.name,
        f.strategy,
        COUNT(h.id) as holdings_count,
        SUM(h.market_value_usd) as total_value_usd,
        fl.filing_date
    FROM funds f
    JOIN filings fl ON f.cik = fl.fund_cik
    JOIN holdings h ON fl.accession_number = h.filing_accession
    WHERE fl.report_period = ?
    GROUP BY f.cik, f.name, f.strategy, fl.filing_date
    ORDER BY total_value_usd DESC
    """
    df = pd.read_sql_query(query, conn, params=[quarter])
    conn.close()
    return df

def fetch_sector_data(quarter="2026-06-30", prev_quarter="2026-03-31"):
    """Fetch sector-level changes - GROUP main sectors, not ETF sub-categories"""
    conn = sqlite3.connect(DB)
    query = """
    SELECT 
        CASE 
            WHEN s.sector LIKE 'ETF -%' THEN 'ETFs & Funds'
            ELSE s.sector
        END as sector_group,
        COUNT(DISTINCT hc.ticker) as ticker_count,
        SUM(CASE WHEN hc.value_change_usd > 0 THEN hc.value_change_usd ELSE 0 END) as buys_usd,
        SUM(CASE WHEN hc.value_change_usd < 0 THEN hc.value_change_usd ELSE 0 END) as sells_usd,
        SUM(hc.value_change_usd) as net_change_usd
    FROM holding_changes hc
    JOIN sectors s ON hc.ticker = s.ticker
    WHERE hc.curr_report_period = ? AND hc.prev_report_period = ? AND s.sector IS NOT NULL
    GROUP BY sector_group
    ORDER BY ABS(net_change_usd) DESC
    """
    df = pd.read_sql_query(query, conn, params=[quarter, prev_quarter])
    conn.close()
    return df

def format_value(val):
    """Format in billions or trillions"""
    if val >= 1e12:
        return "${:.2f}T".format(val/1e12)
    return "${:.1f}B".format(val/1e9)

def format_billions(val):
    return "${:.1f}B".format(val/1e9)

# Fetch ALL data
print("Fetching data...")
buys, sells = fetch_consensus_data()
fund_summary = fetch_all_fund_summaries()
sector_data = fetch_sector_data()

# Get all 9 funds with data
funds_with_data = fund_summary['name'].tolist()
fund_changes = {}
for fund in funds_with_data:
    fund_changes[fund] = fetch_fund_changes(fund, limit=15)

print("Consensus buys: {}, sells: {}".format(len(buys), len(sells)))
print("Funds with Q2 2026 data: {}".format(len(fund_summary)))
print("Sector groups: {}".format(len(sector_data)))

# Strategy colors
strategy_colors = {
    'value_concentrated': '#f39c12', 
    'quant_multi_strat': '#3498db', 
    'tech_growth': '#9b59b6', 
    'activist': '#e74c3c',
    'macro_all_weather': '#1abc9c', 
    'index_passive': '#95a5a6',
    'multi_asset': '#34495e',
    'active_index': '#2c3e50',
    'sovereign': '#16a085',
    'concentrated': '#e67e22'
}

# ===== CHART 1: Consensus Buys & Sells =====
fig1 = make_subplots(
    rows=1, cols=2,
    subplot_titles=("Top Consensus Buys (Q1->Q2 2026)", "Top Consensus Sells (Q1->Q2 2026)"),
    horizontal_spacing=0.1
)

fig1.add_trace(
    go.Bar(
        y=buys['ticker'].iloc[::-1],
        x=buys['net_change_usd'].iloc[::-1] / 1e9,
        orientation='h',
        text=[format_billions(x) for x in buys['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#2ecc71',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata}<br>Actions: %{customdata2}<extra></extra>',
        customdata=buys['fund_count'].iloc[::-1],
        name="Net Buy ($B)"
    ),
    row=1, col=1
)

fig1.add_trace(
    go.Bar(
        y=sells['ticker'].iloc[::-1],
        x=abs(sells['net_change_usd'].iloc[::-1]) / 1e9,
        orientation='h',
        text=[format_billions(abs(x)) for x in sells['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#e74c3c',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata}<br>Actions: %{customdata2}<extra></extra>',
        customdata=sells['fund_count'].iloc[::-1],
        name="Net Sell ($B)"
    ),
    row=1, col=2
)

fig1.update_layout(
    title_text="Consensus Position Changes - Q2 2026 vs Q1 2026 (2+ funds)",
    title_x=0.5,
    height=600,
    showlegend=False,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=11),
)
fig1.update_xaxes(title_text="Net Change ($B)")
fig1.update_yaxes(autorange="reversed")

fig1.write_html("scanners/13f/charts_consensus.html", include_plotlyjs="cdn")
print("Saved: charts_consensus.html")

# ===== CHART 2: Fund Portfolio Sizes (ALL 9 funds) =====
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    y=fund_summary['name'].iloc[::-1],
    x=fund_summary['total_value_usd'].iloc[::-1] / 1e9,
    orientation='h',
    text=[format_value(x) for x in fund_summary['total_value_usd'].iloc[::-1]],
    textposition='auto',
    marker_color=[strategy_colors.get(s, '#34495e') for s in fund_summary['strategy'].iloc[::-1]],
    hovertemplate='%{y}: %{text}<br>Strategy: %{customdata[0]}<br>Holdings: %{customdata[1]}<extra></extra>',
    customdata=list(zip(fund_summary['strategy'].iloc[::-1], fund_summary['holdings_count'].iloc[::-1])),
    name="13F Portfolio ($B)"
))

fig2.update_layout(
    title_text="13F-Reported Portfolio Sizes - Q2 2026 (Jun 30)",
    title_x=0.5,
    title_font_size=16,
    height=500,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=11),
    xaxis_title="Portfolio Value ($B)",
    yaxis=dict(autorange="reversed")
)

fig2.write_html("scanners/13f/charts_portfolios.html", include_plotlyjs="cdn")
print("Saved: charts_portfolios.html")

# ===== CHART 3: Sector Net Flows (Aggregated) =====
fig3 = go.Figure()
sector_data = sector_data.sort_values('net_change_usd', ascending=True)
colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in sector_data['net_change_usd']]

fig3.add_trace(go.Bar(
    y=sector_data['sector_group'],
    x=sector_data['net_change_usd'] / 1e9,
    orientation='h',
    text=[format_billions(x) for x in sector_data['net_change_usd']],
    textposition='auto',
    marker_color=colors,
    hovertemplate='%{y}: %{text}<br>Buys: $%{customdata[0]:.1f}B<br>Sells: $%{customdata[1]:.1f}B<br>Tickers: %{customdata[2]}<extra></extra>',
    customdata=list(zip(sector_data['buys_usd']/1e9, abs(sector_data['sells_usd'])/1e9, sector_data['ticker_count'])),
    name="Net Flow ($B)"
))

fig3.update_layout(
    title_text="Sector Net Flows (Aggregated) - Q1->Q2 2026",
    title_x=0.5,
    title_font_size=16,
    height=600,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=11),
    xaxis_title="Net Flow ($B)",
    yaxis=dict(autorange="reversed")
)

fig3.write_html("scanners/13f/charts_sectors.html", include_plotlyjs="cdn")
print("Saved: charts_sectors.html")

# ===== CHART 4: Per-Fund Top Changes (ALL 9 funds) =====
n_funds = len(funds_with_data)
n_cols = 3
n_rows = (n_funds + n_cols - 1) // n_cols

fig4 = make_subplots(
    rows=n_rows, cols=n_cols,
    subplot_titles=["{} ({})".format(f, fund_summary[fund_summary['name']==f]['strategy'].values[0]) for f in funds_with_data],
    vertical_spacing=0.1,
    horizontal_spacing=0.08
)

for idx, fund in enumerate(funds_with_data):
    row = idx // n_cols + 1
    col = idx % n_cols + 1
    df = fund_changes[fund].head(10).sort_values('value_change_usd', ascending=True)
    
    fig4.add_trace(
        go.Bar(
            y=df['ticker'],
            x=df['value_change_usd'].fillna(0) / 1e9,
            orientation='h',
            text=[format_billions(x) for x in df['value_change_usd'].fillna(0)],
            textposition='auto',
            marker_color=['#2ecc71' if x > 0 else '#e74c3c' for x in df['value_change_usd'].fillna(0)],
            hovertemplate='%{y}: %{text} (%{customdata})<extra></extra>',
            customdata=df['status'],
            showlegend=False
        ),
        row=row, col=col
    )
    fig4.update_xaxes(title_text="Change ($B)", row=row, col=col)
    fig4.update_yaxes(autorange="reversed", row=row, col=col)

fig4.update_layout(
    title_text="Top Position Changes by Fund - Q1->Q2 2026",
    title_x=0.5,
    title_font_size=16,
    height=350 * n_rows,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=10),
)

fig4.write_html("scanners/13f/charts_fund_changes.html", include_plotlyjs="cdn")
print("Saved: charts_fund_changes.html")

# ===== CHART 5: Combined Dashboard =====
fig5 = make_subplots(
    rows=3, cols=2,
    subplot_titles=(
        "Top Consensus Buys", 
        "Top Consensus Sells",
        "Fund Portfolio Sizes (All 9 Funds)",
        "Sector Net Flows (Aggregated)",
        "Net Flow by Strategy",
        "Activity Heatmap (Fund vs Ticker)"
    ),
    specs=[
        [{"type": "bar"}, {"type": "bar"}],
        [{"type": "bar"}, {"type": "bar"}],
        [{"type": "bar"}, {"type": "heatmap"}],
    ],
    vertical_spacing=0.12,
    horizontal_spacing=0.1,
    row_heights=[0.3, 0.35, 0.35]
)

# 1. Consensus Buys
fig5.add_trace(
    go.Bar(
        y=buys['ticker'].iloc[::-1],
        x=buys['net_change_usd'].iloc[::-1] / 1e9,
        orientation='h',
        text=[format_billions(x) for x in buys['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#2ecc71',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata}<extra></extra>',
        customdata=buys['fund_count'].iloc[::-1],
        name="Net Buy"
    ),
    row=1, col=1
)

# 2. Consensus Sells
fig5.add_trace(
    go.Bar(
        y=sells['ticker'].iloc[::-1],
        x=abs(sells['net_change_usd'].iloc[::-1]) / 1e9,
        orientation='h',
        text=[format_billions(abs(x)) for x in sells['net_change_usd'].iloc[::-1]],
        textposition='auto',
        marker_color='#e74c3c',
        hovertemplate='%{y}: %{text}<br>Funds: %{customdata}<extra></extra>',
        customdata=sells['fund_count'].iloc[::-1],
        name="Net Sell"
    ),
    row=1, col=2
)

# 3. Fund Portfolio Sizes (spans both cols)
fig5.add_trace(
    go.Bar(
        y=fund_summary['name'].iloc[::-1],
        x=fund_summary['total_value_usd'].iloc[::-1] / 1e9,
        orientation='h',
        text=[format_value(x) for x in fund_summary['total_value_usd'].iloc[::-1]],
        textposition='auto',
        marker_color=[strategy_colors.get(s, '#34495e') for s in fund_summary['strategy'].iloc[::-1]],
        hovertemplate='%{y}: %{text}<br>Strategy: %{customdata[0]}<br>Holdings: %{customdata[1]}<extra></extra>',
        customdata=list(zip(fund_summary['strategy'].iloc[::-1], fund_summary['holdings_count'].iloc[::-1])),
        name="Portfolio"
    ),
    row=2, col=1
)

# 4. Sector Net Flows
sector_data_sorted = sector_data.sort_values('net_change_usd', ascending=True)
fig5.add_trace(
    go.Bar(
        y=sector_data_sorted['sector_group'],
        x=sector_data_sorted['net_change_usd'] / 1e9,
        orientation='h',
        text=[format_billions(x) for x in sector_data_sorted['net_change_usd']],
        textposition='auto',
        marker_color=['#2ecc71' if x > 0 else '#e74c3c' for x in sector_data_sorted['net_change_usd']],
        hovertemplate='%{y}: %{text}<extra></extra>',
        name="Sector Net"
    ),
    row=2, col=2
)

# 5. Net Flow by Strategy
conn = sqlite3.connect(DB)
strategy_query = """
SELECT 
    f.strategy,
    SUM(hc.value_change_usd) as net_change_usd
FROM holding_changes hc
JOIN funds f ON hc.fund_cik = f.cik
WHERE hc.curr_report_period = '2026-06-30' AND hc.prev_report_period = '2026-03-31'
GROUP BY f.strategy
ORDER BY net_change_usd DESC
"""
strategy_flows = pd.read_sql_query(strategy_query, conn)
conn.close()

fig5.add_trace(
    go.Bar(
        x=strategy_flows['strategy'],
        y=strategy_flows['net_change_usd'] / 1e9,
        text=[format_billions(x) for x in strategy_flows['net_change_usd']],
        textposition='auto',
        marker_color=[strategy_colors.get(s, '#34495e') for s in strategy_flows['strategy']],
        name="Strategy Net"
    ),
    row=3, col=1
)

# 6. Activity Heatmap - Top 20 tickers by total activity across funds
conn = sqlite3.connect(DB)
heatmap_query = """
SELECT 
    hc.ticker,
    f.name as fund,
    hc.value_change_usd
FROM holding_changes hc
JOIN funds f ON hc.fund_cik = f.cik
WHERE hc.curr_report_period = '2026-06-30' AND hc.prev_report_period = '2026-03-31'
"""
hm_df = pd.read_sql_query(heatmap_query, conn)
conn.close()

# Get top 20 tickers by total absolute change
ticker_totals = hm_df.groupby('ticker')['value_change_usd'].apply(lambda x: x.abs().sum()).sort_values(ascending=False).head(20)
top_tickers = ticker_totals.index.tolist()
hm_df = hm_df[hm_df['ticker'].isin(top_tickers)]

pivot = hm_df.pivot_table(index='fund', columns='ticker', values='value_change_usd', fill_value=0)
pivot = pivot[top_tickers]
# Only keep funds that actually have data in the pivot
funds_in_pivot = [f for f in funds_with_data if f in pivot.index]
pivot = pivot.loc[funds_in_pivot]

fig5.add_trace(
    go.Heatmap(
        z=pivot.values / 1e9,
        x=pivot.columns,
        y=pivot.index,
        colorscale='RdYlGn',
        zmid=0,
        text=[[format_billions(v) for v in row] for row in pivot.values],
        texttemplate="%{text}",
        textfont={"size": 9},
        hovertemplate='%{y} - %{x}: %{z:.1f}B<extra></extra>',
        name="Activity"
    ),
    row=3, col=2
)

fig5.update_layout(
    title_text="13F Q2 2026 Complete Dashboard - 9 Funds, 24,933 Position Changes",
    title_x=0.5,
    title_font_size=18,
    height=1400,
    showlegend=False,
    template="plotly_white",
    font=dict(family="Inter, sans-serif", size=10),
)

fig5.update_xaxes(title_text="Net Change ($B)", row=1, col=1)
fig5.update_xaxes(title_text="Net Change ($B)", row=1, col=2)
fig5.update_xaxes(title_text="Portfolio ($B)", row=2, col=1)
fig5.update_xaxes(title_text="Net Flow ($B)", row=2, col=2)
fig5.update_xaxes(title_text="Net Flow ($B)", row=3, col=1)
fig5.update_yaxes(autorange="reversed", row=1, col=1)
fig5.update_yaxes(autorange="reversed", row=1, col=2)
fig5.update_yaxes(autorange="reversed", row=2, col=1)

fig5.write_html("scanners/13f/charts_dashboard.html", include_plotlyjs="cdn")
print("Saved: charts_dashboard.html")

# Save summary JSON
summary = {
    "quarter": "2026-06-30",
    "prev_quarter": "2026-03-31",
    "consensus_buys": buys.to_dict('records'),
    "consensus_sells": sells.to_dict('records'),
    "fund_summary": fund_summary.to_dict('records'),
    "sector_flows": sector_data.to_dict('records'),
    "strategy_flows": strategy_flows.to_dict('records'),
    "fund_changes": {k: v.head(10).to_dict('records') for k, v in fund_changes.items()},
}
with open("scanners/13f/charts_summary.json", "w") as f:
    json.dump(summary, f, indent=2, default=str)
print("Summary JSON saved")

# Print key findings
buy_lines = []
for _, r in buys.head(5).iterrows():
    buy_lines.append("{} (+${:.1f}B)".format(r['ticker'], r['net_change_usd']/1e9))
sell_lines = []
for _, r in sells.head(5).iterrows():
    sell_lines.append("{} (-${:.1f}B)".format(r['ticker'], abs(r['net_change_usd'])/1e9))

print("\n=== KEY FINDINGS ===")
print("Consensus BUYS (top 5): {}".format(", ".join(buy_lines)))
print("Consensus SELLS (top 5): {}".format(", ".join(sell_lines)))
print("Largest portfolio: {} - {}".format(fund_summary.iloc[0]['name'], format_value(fund_summary.iloc[0]['total_value_usd'])))

tech_val = sector_data[sector_data['sector_group']=='Technology']['net_change_usd'].values[0]
energy_val = sector_data[sector_data['sector_group']=='Energy']['net_change_usd'].values[0]
print("Sector leaders: Tech (+${:.1f}B), Energy (-${:.1f}B)".format(tech_val/1e9, abs(energy_val)/1e9))
print("Strategy leaders: {} (+${:.1f}B)".format(strategy_flows.iloc[0]['strategy'], strategy_flows.iloc[0]['net_change_usd']/1e9))
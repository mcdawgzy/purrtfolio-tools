"""
Export functionality for short interest data
"""
import json
import csv
from pathlib import Path
from datetime import date
from typing import List, Dict, Any, Optional
import pandas as pd

from .config import EXPORTS_DIR, DB_PATH
from .db import export_to_dataframe, get_db, get_latest_settlement_date

EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

def export_latest_csv(output_path: Optional[Path] = None) -> Path:
    """Export latest settlement date data to CSV"""
    if output_path is None:
        latest = get_latest_settlement_date()
        date_str = latest.strftime("%Y%m%d") if latest else "latest"
        output_path = EXPORTS_DIR / f"short_interest_{date_str}.csv"
    
    query = """
        SELECT si.symbol, t.name, t.category, t.exchange, t.market_class,
               si.settlement_date, si.current_short, si.previous_short,
               si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume
        FROM short_interest si
        JOIN tickers t ON si.symbol = t.ticker
        WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
        ORDER BY si.current_short DESC
    """
    df = export_to_dataframe(query)
    df.to_csv(output_path, index=False)
    print(f"Exported {len(df)} rows to {output_path}")
    return output_path

def export_full_history_csv(output_path: Optional[Path] = None) -> Path:
    """Export full history to CSV"""
    if output_path is None:
        output_path = EXPORTS_DIR / "short_interest_full_history.csv"
    
    query = """
        SELECT si.symbol, t.name, t.category, t.exchange, t.market_class,
               si.settlement_date, si.current_short, si.previous_short,
               si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume
        FROM short_interest si
        JOIN tickers t ON si.symbol = t.ticker
        ORDER BY si.symbol, si.settlement_date
    """
    df = export_to_dataframe(query)
    df.to_csv(output_path, index=False)
    print(f"Exported {len(df)} rows to {output_path}")
    return output_path

def export_ticker_csv(symbol: str, output_path: Optional[Path] = None) -> Path:
    """Export single ticker history to CSV"""
    if output_path is None:
        output_path = EXPORTS_DIR / f"{symbol.upper()}_history.csv"
    
    query = """
        SELECT si.symbol, t.name, t.category, t.exchange, t.market_class,
               si.settlement_date, si.current_short, si.previous_short,
               si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume
        FROM short_interest si
        JOIN tickers t ON si.symbol = t.ticker
        WHERE si.symbol = ?
        ORDER BY si.settlement_date
    """
    df = export_to_dataframe(query, (symbol.upper(),))
    df.to_csv(output_path, index=False)
    print(f"Exported {len(df)} rows to {output_path}")
    return output_path

def export_signals_json(output_path: Optional[Path] = None) -> Path:
    """Export all signals to JSON"""
    from .analyze import get_all_signals, get_market_summary
    
    if output_path is None:
        latest = get_latest_settlement_date()
        date_str = latest.strftime("%Y%m%d") if latest else "latest"
        output_path = EXPORTS_DIR / f"signals_{date_str}.json"
    
    signals = get_all_signals()
    summary = get_market_summary()
    
    output = {
        'generated_at': str(date.today()),
        'latest_settlement': summary['latest_settlement'],
        'market_summary': summary,
        'signals': signals
    }
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    total_signals = sum(len(v) for v in signals.values())
    print(f"Exported {total_signals} signals to {output_path}")
    return output_path

def export_signals_csv(output_path: Optional[Path] = None) -> Dict[str, Path]:
    """Export each signal type to separate CSV"""
    from .analyze import get_all_signals
    
    if output_path is None:
        latest = get_latest_settlement_date()
        date_str = latest.strftime("%Y%m%d") if latest else "latest"
        base = EXPORTS_DIR / f"signals_{date_str}"
    else:
        base = Path(output_path).with_suffix("")
    
    signals = get_all_signals()
    paths = {}
    
    for signal_type, data in signals.items():
        if not data:
            continue
        signal_path = base.parent / f"{base.name}_{signal_type}.csv"
        df = pd.DataFrame(data)
        df.to_csv(signal_path, index=False)
        paths[signal_type] = signal_path
        print(f"  {signal_type}: {len(data)} rows -> {signal_path}")
    
    return paths

def export_category_csv(category: str, output_path: Optional[Path] = None) -> Path:
    """Export category summary to CSV"""
    if output_path is None:
        output_path = EXPORTS_DIR / f"category_{category}.csv"
    
    query = """
        SELECT si.symbol, t.name, t.category, t.exchange, t.market_class,
               si.settlement_date, si.current_short, si.previous_short,
               si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume
        FROM short_interest si
        JOIN tickers t ON si.symbol = t.ticker
        WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
          AND t.category = ?
        ORDER BY si.current_short DESC
    """
    df = export_to_dataframe(query, (category,))
    df.to_csv(output_path, index=False)
    print(f"Exported {len(df)} rows to {output_path}")
    return output_path

def export_all_categories(output_dir: Optional[Path] = None) -> Dict[str, Path]:
    """Export all categories to separate CSVs"""
    from .db import get_categories
    
    if output_dir is None:
        output_dir = EXPORTS_DIR / "categories"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    categories = get_categories()
    paths = {}
    
    for cat in categories:
        cat_path = output_dir / f"{cat}.csv"
        paths[cat] = export_category_csv(cat, cat_path)
    
    return paths

def create_summary_report(output_path: Optional[Path] = None) -> Path:
    """Create a comprehensive summary report (HTML)"""
    from .analyze import get_market_summary, get_all_signals
    
    if output_path is None:
        latest = get_latest_settlement_date()
        date_str = latest.strftime("%Y%m%d") if latest else "latest"
        output_path = EXPORTS_DIR / f"report_{date_str}.html"
    
    summary = get_market_summary()
    signals = get_all_signals()
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Short Interest Report - {summary['latest_settlement']}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; }}
        h1, h2, h3 {{ color: #1a1a1a; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f5f5f5; }}
        .metric {{ display: inline-block; margin: 10px 20px; padding: 10px; background: #f9f9f9; border-radius: 4px; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
        .metric-label {{ font-size: 12px; color: #666; }}
        .signal-row {{ cursor: pointer; }}
        .signal-row.high-dtc {{ background: #fef3c7; }}
        .signal-row.spike {{ background: #fee2e2; }}
        .signal-row.covering {{ background: #dcfce7; }}
    </style>
</head>
<body>
    <h1>Short Interest Report</h1>
    <p>Settlement Date: <strong>{summary['latest_settlement']}</strong></p>
    <p>Generated: {date.today()}</p>
    
    <h2>Market Summary</h2>
    <div class="metric">
        <div class="metric-value">{summary['ticker_count']:,}</div>
        <div class="metric-label">Tracked Tickers</div>
    </div>
    <div class="metric">
        <div class="metric-value">{summary['total_short_interest']:,}</div>
        <div class="metric-label">Total Short Shares</div>
    </div>
    
    <h3>By Exchange</h3>
    <table>
        <tr><th>Exchange</th><th>Total Short</th><th>Tickers</th></tr>
        {''.join(f"<tr><td>{r['exchange']}</td><td>{r['total']:,}</td><td>{r['count']}</td></tr>" for r in summary['by_exchange'])}
    </table>
    
    <h3>By Category</h3>
    <table>
        <tr><th>Category</th><th>Total Short</th><th>Tickers</th></tr>
        {''.join(f"<tr><td>{r['category']}</td><td>{r['total']:,}</td><td>{r['count']}</td></tr>" for r in summary['by_category'])}
    </table>
    
    <h2>Signal Counts</h2>
    <table>
        <tr><th>Signal Type</th><th>Count</th></tr>
        {''.join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in summary['signal_counts'].items())}
    </table>
    
    <h2>Top Signals</h2>
"""
    
    for signal_type, data in signals.items():
        if not data:
            continue
        html += f"<h3>{signal_type.replace('_', ' ').title()} ({len(data)})</h3>"
        html += "<table><tr>"
        html += "".join(f"<th>{col}</th>" for col in data[0].keys())
        html += "</tr>"
        for row in data[:20]:
            html += "<tr class='signal-row " + signal_type + "'>"
            html += "".join(f"<td>{row[col]}</td>" for col in row.keys())
            html += "</tr>"
        html += "</table>"
    
    html += "</body></html>"
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    print(f"Report saved to {output_path}")
    return output_path

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m short_interest_scanner.export <command> [args]")
        print("Commands:")
        print("  latest              - Export latest settlement data to CSV")
        print("  history             - Export full history to CSV")
        print("  ticker SYMBOL       - Export single ticker history")
        print("  signals             - Export all signals to JSON")
        print("  signals-csv         - Export signals to separate CSVs")
        print("  category CAT        - Export category to CSV")
        print("  all-categories      - Export all categories to CSVs")
        print("  report              - Create HTML summary report")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "latest":
        export_latest_csv()
    elif cmd == "history":
        export_full_history_csv()
    elif cmd == "ticker":
        export_ticker_csv(sys.argv[2])
    elif cmd == "signals":
        export_signals_json()
    elif cmd == "signals-csv":
        export_signals_csv()
    elif cmd == "category":
        export_category_csv(sys.argv[2])
    elif cmd == "all-categories":
        export_all_categories()
    elif cmd == "report":
        create_summary_report()
    else:
        print(f"Unknown command: {cmd}")
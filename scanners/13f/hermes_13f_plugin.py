#!/usr/bin/env python3
"""
Hermes Plugin: 13F Scanner Slash Commands
Registers 13F scanner commands with Hermes gateway for Discord slash command support.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional, List, Callable
import sys

# Add 13f-scanner to path
SCANNER_DIR = Path(__file__).parent
sys.path.insert(0, str(SCANNER_DIR))

from export import ExcelExporter
from compare import ChangeComparator
from ingest import EdgartoolsIngestor
from db_init import init_database, get_tracked_funds

DB_PATH = Path(r"C:\Users\cho_i\purrtfolio.db")


class ScannerBot:
    """13F Scanner Discord Bot logic (adapted from bot.py)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.exporter = ExcelExporter(db_path)
        self.comparator = ChangeComparator(db_path)
        self.ingestor = EdgartoolsIngestor(db_path)

    def close(self):
        self.conn.close()
        self.exporter.close()
        self.comparator.close()
        self.ingestor.close()

    def _resolve_fund(self, name_or_cik: str) -> Optional[str]:
        if name_or_cik.isdigit() and len(name_or_cik) == 10:
            return name_or_cik
        row = self.conn.execute(
            "SELECT cik FROM funds WHERE name LIKE ? OR cik = ? LIMIT 1",
            (f"%{name_or_cik}%", name_or_cik)
        ).fetchone()
        return row['cik'] if row else None

    def _get_latest_quarter(self, fund_cik: str = None) -> Optional[date]:
        if fund_cik:
            row = self.conn.execute("""
                SELECT MAX(report_period) as latest FROM filings
                WHERE fund_cik = ? AND has_infotable = 1
            """, (fund_cik,)).fetchone()
        else:
            row = self.conn.execute("""
                SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
            """).fetchone()
        return date.fromisoformat(row['latest']) if row and row['latest'] else None


# Global bot instance (lazy initialized)
_bot_instance: Optional[ScannerBot] = None


def get_bot() -> ScannerBot:
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = ScannerBot(str(DB_PATH))
    return _bot_instance


# ──────────────────────────────────────────────────────────────
# Slash Command Handlers
# ──────────────────────────────────────────────────────────────

def fund_holdings(raw_args: str) -> str:
    """Show fund's top holdings for a quarter. Usage: fund holdings <fund> [quarter] [top]"""
    parts = raw_args.strip().split()
    if not parts:
        return "Usage: /13f-fund-holdings <fund> [quarter] [top]"

    fund = parts[0]
    quarter = parts[1] if len(parts) > 1 else None
    top = int(parts[2]) if len(parts) > 2 else 20

    bot = get_bot()
    fund_cik = bot._resolve_fund(fund)
    if not fund_cik:
        return f"❌ Fund not found: {fund}"

    if quarter:
        report_period = date.fromisoformat(quarter)
    else:
        report_period = bot._get_latest_quarter(fund_cik)
        if not report_period:
            return f"❌ No filings found for {fund}"

    rows = bot.conn.execute("""
        SELECT ticker, issuer_name, market_value_usd, shares,
               ROUND(market_value_usd * 100.0 / SUM(market_value_usd) OVER (), 2) as weight_pct
        FROM holdings
        WHERE fund_cik = ? AND report_period = ? AND put_call = ''
        ORDER BY market_value_usd DESC
        LIMIT ?
    """, (fund_cik, report_period, top)).fetchall()

    if not rows:
        return f"❌ No holdings data for {fund} in {report_period}"

    fund_info = bot.conn.execute("SELECT name FROM funds WHERE cik = ?", (fund_cik,)).fetchone()
    fund_name = fund_info['name'] if fund_info else fund_cik

    total_value = sum(r['market_value_usd'] for r in rows)
    lines = [f"📊 **{fund_name} Holdings — {report_period}**", f"Top {len(rows)} positions (long equity only):", ""]

    for i, row in enumerate(rows[:10], 1):
        lines.append(f"{i}. **{row['ticker']}** — {row['issuer_name'][:40]}")
        lines.append(f"   ${row['market_value_usd']:,.0f} ({row['weight_pct']:.1f}%) • {row['shares']:,.0f} shares")

    if len(rows) > 10:
        lines.append(f"\n... and {len(rows) - 10} more positions")

    lines.append(f"\nTotal tracked value: ${total_value:,.0f}")
    return "\n".join(lines)


def fund_changes(raw_args: str) -> str:
    """Show QoQ changes for a fund. Usage: fund changes <fund> [quarter]"""
    parts = raw_args.strip().split()
    if not parts:
        return "Usage: /13f-fund-changes <fund> [quarter]"

    fund = parts[0]
    quarter = parts[1] if len(parts) > 1 else None

    bot = get_bot()
    fund_cik = bot._resolve_fund(fund)
    if not fund_cik:
        return f"❌ Fund not found: {fund}"

    if quarter:
        curr_period = date.fromisoformat(quarter)
    else:
        curr_period = bot._get_latest_quarter(fund_cik)
        if not curr_period:
            return f"❌ No filings found for {fund}"

    prev_period = bot.comparator.get_previous_quarter(curr_period)

    summary = bot.conn.execute("""
        SELECT status, COUNT(*) as cnt, SUM(ABS(value_change_usd)) as impact
        FROM holding_changes
        WHERE fund_cik = ? AND curr_report_period = ?
        GROUP BY status
    """, (fund_cik, curr_period)).fetchall()

    if not summary:
        return f"❌ No changes computed for {fund} in {curr_period}. Run `/13f-admin-compute-changes {curr_period}` first."

    fund_info = bot.conn.execute("SELECT name FROM funds WHERE cik = ?", (fund_cik,)).fetchone()
    fund_name = fund_info['name'] if fund_info else fund_cik

    status_emoji = {"NEW": "🟢", "INCREASED": "🔵", "DECREASED": "🟠", "CLOSED": "🔴", "UNCHANGED": "⚪"}

    lines = [f"📈 **{fund_name} QoQ Changes — {prev_period} → {curr_period}**", ""]

    for row in summary:
        emoji = status_emoji.get(row['status'], "⚪")
        lines.append(f"{emoji} **{row['status']}**: {row['cnt']} positions • ${row['impact']:,.0f} value impact")

    # Top new
    top_new = bot.conn.execute("""
        SELECT ticker, issuer_name, curr_value_usd
        FROM holding_changes
        WHERE fund_cik = ? AND curr_report_period = ? AND status = 'NEW'
        ORDER BY curr_value_usd DESC LIMIT 3
    """, (fund_cik, curr_period)).fetchall()

    if top_new:
        lines.append("\n🟢 **Top New Positions**")
        for r in top_new:
            lines.append(f"• {r['ticker']} ({r['issuer_name'][:30]}) — ${r['curr_value_usd']:,.0f}")

    # Top exits
    top_exits = bot.conn.execute("""
        SELECT ticker, issuer_name, prev_value_usd
        FROM holding_changes
        WHERE fund_cik = ? AND curr_report_period = ? AND status = 'CLOSED'
        ORDER BY prev_value_usd DESC LIMIT 3
    """, (fund_cik, curr_period)).fetchall()

    if top_exits:
        lines.append("\n🔴 **Top Exits**")
        for r in top_exits:
            lines.append(f"• {r['ticker']} ({r['issuer_name'][:30]}) — was ${r['prev_value_usd']:,.0f}")

    lines.append("\n💡 Use `/13f-export-fund-changes <fund> <quarter>` for full Excel breakdown")
    return "\n".join(lines)


def market_consensus(raw_args: str) -> str:
    """Show tickers with multi-fund conviction. Usage: market consensus [quarter] [min_funds]"""
    parts = raw_args.strip().split()
    quarter = parts[0] if parts else None
    min_funds = int(parts[1]) if len(parts) > 1 else 3

    bot = get_bot()

    if quarter:
        report_period = date.fromisoformat(quarter)
    else:
        row = bot.conn.execute("""
            SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
        """).fetchone()
        report_period = date.fromisoformat(row['latest']) if row else None

    if not report_period:
        return "❌ No data available"

    rows = bot.conn.execute("""
        SELECT
            hc.ticker, hc.issuer_name,
            COUNT(*) as funds_total,
            SUM(CASE WHEN hc.status IN ('NEW','INCREASED') THEN 1 ELSE 0 END) as funds_adding,
            SUM(CASE WHEN hc.status IN ('CLOSED','DECREASED') THEN 1 ELSE 0 END) as funds_reducing,
            SUM(hc.curr_value_usd) as total_value,
            SUM(hc.value_change_usd) as net_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ? AND hc.put_call = ''
        GROUP BY hc.ticker, hc.issuer_name
        HAVING funds_total >= ?
        ORDER BY funds_adding DESC, net_change DESC
        LIMIT 20
    """, (report_period, min_funds)).fetchall()

    if not rows:
        return f"❌ No consensus data for {report_period} (min_funds={min_funds})"

    lines = [f"🎯 **Institutional Consensus — {report_period}**", f"Tickers held by ≥{min_funds} tracked funds", ""]

    for i, row in enumerate(rows[:15], 1):
        sentiment = "🟢" if row['funds_adding'] > row['funds_reducing'] else "🔴" if row['funds_reducing'] > row['funds_adding'] else "⚪"
        lines.append(f"{i}. {sentiment} **{row['ticker']}** — {row['issuer_name'][:35]}")
        lines.append(f"   📊 {row['funds_total']} funds • 🟢{row['funds_adding']} adding 🔴{row['funds_reducing']} reducing • Net ${row['net_change']:,.0f}")

    lines.append("\n💡 Use `/13f-export-consensus <quarter> [min_funds]` for full Excel with fund-level detail")
    return "\n".join(lines)


def market_buys(raw_args: str) -> str:
    """Top new positions across all funds. Usage: market buys [quarter] [limit]"""
    parts = raw_args.strip().split()
    quarter = parts[0] if parts else None
    limit = int(parts[1]) if len(parts) > 1 else 15

    bot = get_bot()

    if quarter:
        report_period = date.fromisoformat(quarter)
    else:
        row = bot.conn.execute("""
            SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
        """).fetchone()
        report_period = date.fromisoformat(row['latest']) if row else date.today()

    rows = bot.conn.execute("""
        SELECT hc.ticker, hc.issuer_name, COUNT(*) as fund_count,
               SUM(hc.curr_value_usd) as total_value,
               GROUP_CONCAT(DISTINCT f.name) as funds
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ? AND hc.status = 'NEW' AND hc.put_call = ''
        GROUP BY hc.ticker, hc.issuer_name
        ORDER BY total_value DESC
        LIMIT ?
    """, (report_period, limit)).fetchall()

    if not rows:
        return f"❌ No new positions for {report_period}"

    lines = [f"🟢 **Top New Positions — {report_period}**", ""]

    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. **{row['ticker']}** — {row['issuer_name'][:40]}")
        lines.append(f"   {row['fund_count']} funds • ${row['total_value']:,.0f} • {row['funds'][:80]}")

    return "\n".join(lines)


def market_sells(raw_args: str) -> str:
    """Top exits across all funds. Usage: market sells [quarter] [limit]"""
    parts = raw_args.strip().split()
    quarter = parts[0] if parts else None
    limit = int(parts[1]) if len(parts) > 1 else 15

    bot = get_bot()

    if quarter:
        report_period = date.fromisoformat(quarter)
    else:
        row = bot.conn.execute("""
            SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
        """).fetchone()
        report_period = date.fromisoformat(row['latest']) if row else date.today()

    rows = bot.conn.execute("""
        SELECT hc.ticker, hc.issuer_name, COUNT(*) as fund_count,
               SUM(hc.prev_value_usd) as total_value,
               GROUP_CONCAT(DISTINCT f.name) as funds
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ? AND hc.status = 'CLOSED' AND hc.put_call = ''
        GROUP BY hc.ticker, hc.issuer_name
        ORDER BY total_value DESC
        LIMIT ?
    """, (report_period, limit)).fetchall()

    if not rows:
        return f"❌ No exits for {report_period}"

    lines = [f"🔴 **Top Full Exits — {report_period}**", ""]

    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. **{row['ticker']}** — {row['issuer_name'][:40]}")
        lines.append(f"   {row['fund_count']} funds • was ${row['total_value']:,.0f} • {row['funds'][:80]}")

    return "\n".join(lines)


def export_fund_changes(raw_args: str) -> str:
    """Export QoQ changes Excel for a fund. Usage: export fund-changes <fund> <quarter>"""
    parts = raw_args.strip().split()
    if len(parts) < 2:
        return "Usage: /13f-export-fund-changes <fund> <quarter>"

    fund = parts[0]
    quarter = parts[1]

    bot = get_bot()
    fund_cik = bot._resolve_fund(fund)
    if not fund_cik:
        return f"❌ Fund not found: {fund}"

    curr = date.fromisoformat(quarter)
    prev = bot.comparator.get_previous_quarter(curr)

    import tempfile
    path = f"{tempfile.gettempdir()}/changes_{fund_cik}_{quarter}.xlsx"

    try:
        bot.exporter.export_fund_changes(fund_cik, curr, prev, path)
        return f"✅ Excel generated: {path}\n(Use `/13f-export-quarterly-package {quarter}` for full ZIP package)"
    except Exception as e:
        return f"❌ Export failed: {e}"


def export_consensus(raw_args: str) -> str:
    """Export market consensus Excel. Usage: export consensus <quarter> [min_funds]"""
    parts = raw_args.strip().split()
    if not parts:
        return "Usage: /13f-export-consensus <quarter> [min_funds]"

    quarter = parts[0]
    min_funds = int(parts[1]) if len(parts) > 1 else 2

    bot = get_bot()
    report_period = date.fromisoformat(quarter)

    import tempfile
    path = f"{tempfile.gettempdir()}/consensus_{quarter}.xlsx"

    try:
        bot.exporter.export_consensus_report(report_period, path, min_funds)
        return f"✅ Excel generated: {path}"
    except Exception as e:
        return f"❌ Export failed: {e}"


def export_quarterly_package(raw_args: str) -> str:
    """Generate complete quarterly analysis package (ZIP). Usage: export quarterly-package <quarter>"""
    parts = raw_args.strip().split()
    if not parts:
        return "Usage: /13f-export-quarterly-package <quarter>"

    quarter = parts[0]

    bot = get_bot()
    report_period = date.fromisoformat(quarter)

    import tempfile
    output_dir = f"{tempfile.gettempdir()}/quarterly_package_{quarter}"

    try:
        results = bot.exporter.generate_quarterly_package(report_period, output_dir)
        zip_path = results['zip']
        return f"✅ Quarterly package generated: {zip_path}"
    except Exception as e:
        return f"❌ Package generation failed: {e}"


def admin_ingest(raw_args: str) -> str:
    """Ingest latest 13F filings. Usage: admin ingest [max_filings]"""
    parts = raw_args.strip().split()
    max_filings = int(parts[0]) if parts else 4

    bot = get_bot()

    try:
        summary = bot.ingestor.ingest_all_tracked_funds(max_filings)
        lines = [
            "📥 **Ingestion Complete**",
            f"Funds Tracked: {summary['total_funds']}",
            f"Funds Updated: {summary['processed_funds']}",
            f"New Filings: {summary['total_filings']}",
            f"Total Holdings: {summary['total_holdings']:,}",
        ]
        if summary['errors']:
            lines.append(f"⚠️ Errors: {len(summary['errors'])} (check logs)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Ingestion failed: {e}"


def admin_compute_changes(raw_args: str) -> str:
    """Compute QoQ changes. Usage: admin compute-changes [quarter] [backfill]"""
    parts = raw_args.strip().split()
    quarter = parts[0] if parts else None
    backfill = "backfill" in parts or "true" in parts

    bot = get_bot()

    try:
        if backfill:
            result = bot.comparator.compute_historical_changes()
            return f"✅ Backfill complete: {result['quarters_processed']} quarter pairs processed"
        elif quarter:
            curr = date.fromisoformat(quarter)
            result = bot.comparator.compute_changes_all_funds(curr)
            return (
                f"✅ Changes computed for {quarter}: {result['funds_compared']} funds, "
                f"{result['total_changes']} total changes\n"
                f"NEW: {result['aggregate_status'].get('NEW',0)} • "
                f"INCREASED: {result['aggregate_status'].get('INCREASED',0)} • "
                f"DECREASED: {result['aggregate_status'].get('DECREASED',0)} • "
                f"CLOSED: {result['aggregate_status'].get('CLOSED',0)}"
            )
        else:
            quarters = bot.comparator.get_available_quarters()
            if quarters:
                result = bot.comparator.compute_changes_all_funds(quarters[-1])
                return f"✅ Changes computed for {quarters[-1]}: {result['funds_compared']} funds"
            else:
                return "❌ No filings in database"
    except Exception as e:
        return f"❌ Computation failed: {e}"


def admin_list_funds(raw_args: str) -> str:
    """List all tracked funds."""
    bot = get_bot()
    funds = get_tracked_funds(bot.conn)

    by_strategy = {}
    for f in funds:
        strat = f['strategy'] or 'other'
        if strat not in by_strategy:
            by_strategy[strat] = []
        by_strategy[strat].append(f)

    lines = ["📋 **Tracked Funds**", ""]
    for strat, flist in sorted(by_strategy.items()):
        lines.append(f"**{strat.replace('_', ' ').title()}**")
        for f in flist[:10]:
            lines.append(f"• {f['name']} (`{f['cik']}`)")
        if len(flist) > 10:
            lines.append(f"  ... and {len(flist)-10} more")
        lines.append("")

    return "\n".join(lines)


def admin_status(raw_args: str) -> str:
    """Show database status."""
    bot = get_bot()

    stats = {}
    stats['funds'] = bot.conn.execute("SELECT COUNT(*) FROM funds WHERE is_active=1").fetchone()[0]
    stats['filings'] = bot.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
    stats['holdings'] = bot.conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    stats['changes'] = bot.conn.execute("SELECT COUNT(*) FROM holding_changes").fetchone()[0]
    stats['quarters'] = bot.conn.execute("SELECT COUNT(DISTINCT report_period) FROM filings WHERE has_infotable=1").fetchone()[0]

    latest = bot.conn.execute("SELECT MAX(report_period) FROM filings WHERE has_infotable=1").fetchone()[0]

    lines = [
        "📊 **Database Status**",
        f"Tracked Funds: {stats['funds']}",
        f"Filings Stored: {stats['filings']}",
        f"Holdings Rows: {stats['holdings']:,}",
        f"Change Records: {stats['changes']:,}",
        f"Quarters Covered: {stats['quarters']}",
        f"Latest Quarter: {latest or 'None'}",
    ]
    return "\n".join(lines)


def help_13f(raw_args: str) -> str:
    """Show available 13F commands."""
    return """📊 **13F Scanner Bot Commands**

**Fund Queries**
`/13f-fund-holdings <fund> [quarter] [top]` — Top positions
`/13f-fund-changes <fund> [quarter]` — QoQ changes summary

**Market Trends**
`/13f-market-consensus [quarter] [min_funds]` — Multi-fund conviction
`/13f-market-buys [quarter] [limit]` — Top new positions
`/13f-market-sells [quarter] [limit]` — Top exits

**Exports**
`/13f-export-fund-changes <fund> <quarter>` — Fund QoQ Excel
`/13f-export-consensus <quarter> [min_funds]` — Consensus Excel
`/13f-export-quarterly-package <quarter>` — Full ZIP package

**Admin (authorized only)**
`/13f-admin-ingest [max_filings]` — Fetch latest filings
`/13f-admin-compute-changes [quarter] [backfill]` — Compute QoQ diffs
`/13f-admin-list-funds` — Show tracked funds
`/13f-admin-status` — Database stats

**Help**
`/13f-help` — This message

*Data source: SEC EDGAR via edgartools (free, no API key)*"""


# ──────────────────────────────────────────────────────────────
# Plugin Registration
# ──────────────────────────────────────────────────────────────

COMMANDS = [
    ("13f-fund-holdings", fund_holdings, "Show fund's top holdings for a quarter", "<fund> [quarter] [top]"),
    ("13f-fund-changes", fund_changes, "Show QoQ changes for a fund", "<fund> [quarter]"),
    ("13f-market-consensus", market_consensus, "Show tickers with multi-fund conviction", "[quarter] [min_funds]"),
    ("13f-market-buys", market_buys, "Top new positions across all funds", "[quarter] [limit]"),
    ("13f-market-sells", market_sells, "Top exits across all funds", "[quarter] [limit]"),
    ("13f-export-fund-changes", export_fund_changes, "Export QoQ changes Excel for a fund", "<fund> <quarter>"),
    ("13f-export-consensus", export_consensus, "Export market consensus Excel", "<quarter> [min_funds]"),
    ("13f-export-quarterly-package", export_quarterly_package, "Generate complete quarterly analysis package (ZIP)", "<quarter>"),
    ("13f-admin-ingest", admin_ingest, "Ingest latest 13F filings for all tracked funds", "[max_filings]"),
    ("13f-admin-compute-changes", admin_compute_changes, "Compute QoQ changes for a quarter", "[quarter] [backfill]"),
    ("13f-admin-list-funds", admin_list_funds, "List all tracked funds", ""),
    ("13f-admin-status", admin_status, "Show database status", ""),
    ("13f-help", help_13f, "Show available 13F scanner commands", ""),
]


def register(ctx) -> None:
    """Plugin entry point - called by Hermes plugin system."""
    for name, handler, description, args_hint in COMMANDS:
        ctx.register_command(
            name=name,
            handler=handler,
            description=description,
            args_hint=args_hint,
        )
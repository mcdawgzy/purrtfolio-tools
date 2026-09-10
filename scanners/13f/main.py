#!/usr/bin/env python3
"""
13F Scanner - Main Entry Point
Unified CLI for all operations: init, ingest, compare, export, bot.
"""
import argparse
import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from db_init import init_database, get_tracked_funds
from ingest import run_ingestion, EdgartoolsIngestor
from compare import run_comparison, ChangeComparator
from export import run_export, ExcelExporter
from bot import run_bot, setup_bot_commands, create_bot
import asyncio


def cmd_init(args):
    """Initialize database and seed funds."""
    print(f"Initializing database: {args.db}")
    conn = init_database(args.db, args.seed)
    conn.row_factory = sqlite3.Row
    funds = get_tracked_funds(conn)
    print(f"✅ Database ready with {len(funds)} tracked funds")
    for f in funds[:5]:
        print(f"  • {f['name']} ({f['cik']}) — {f['strategy']}")
    if len(funds) > 5:
        print(f"  ... and {len(funds) - 5} more")
    conn.close()


def cmd_ingest(args):
    """Ingest 13F filings."""
    if args.fund and args.quarter:
        from datetime import date
        ingestor = EdgartoolsIngestor(args.db, args.email)
        result = ingestor.ingest_by_quarter(date.fromisoformat(args.quarter), [args.fund])
        print(result)
        ingestor.close()
    elif args.fund:
        ingestor = EdgartoolsIngestor(args.db, args.email)
        result = ingestor.ingest_fund_latest(args.fund, args.max_filings)
        print(result)
        ingestor.close()
    else:
        run_ingestion(args.db, args.email, args.max_filings)


def cmd_compare(args):
    """Compute QoQ changes."""
    run_comparison(args.db, args.quarter, args.fund, args.backfill)


def cmd_export(args):
    """Export Excel reports."""
    run_export(args.db, args.quarter, args.fund, args.package, args.output_dir)


def cmd_bot(args):
    """Run Discord bot."""
    allowed = [int(x) for x in args.admins.split(",")] if args.admins else None
    asyncio.run(run_bot(args.db, args.token, allowed))


def cmd_status(args):
    """Show database status."""
    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    
    stats = {}
    stats['funds'] = conn.execute("SELECT COUNT(*) FROM funds WHERE is_active=1").fetchone()[0]
    stats['filings'] = conn.execute("SELECT COUNT(*) FROM filings_13f").fetchone()[0]
    stats['holdings'] = conn.execute("SELECT COUNT(*) FROM holdings_13f").fetchone()[0]
    stats['changes'] = conn.execute("SELECT COUNT(*) FROM holding_changes_13f").fetchone()[0]
    stats['quarters'] = conn.execute("SELECT COUNT(DISTINCT report_period) FROM filings_13f WHERE has_infotable=1").fetchone()[0]
    latest = conn.execute("SELECT MAX(report_period) FROM filings_13f WHERE has_infotable=1").fetchone()[0]
    
    print("=== DATABASE STATUS ===")
    print(f"Tracked Funds:     {stats['funds']}")
    print(f"Filings Stored:    {stats['filings']}")
    print(f"Holdings Rows:     {stats['holdings']:,}")
    print(f"Change Records:    {stats['changes']:,}")
    print(f"Quarters Covered:  {stats['quarters']}")
    print(f"Latest Quarter:    {latest or 'None'}")
    
    # Show quarters
    quarters = conn.execute("""
        SELECT report_period, COUNT(DISTINCT fund_cik) as funds, COUNT(*) as filings
        FROM filings_13f WHERE has_infotable=1
        GROUP BY report_period ORDER BY report_period DESC
    """).fetchall()
    
    print("\nQuarters:")
    for q in quarters:
        print(f"  {q['report_period']}: {q['funds']} funds, {q['filings']} filings")
    
    conn.close()


def cmd_list_funds(args):
    """List tracked funds."""
    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    funds = get_tracked_funds(conn)
    
    print(f"=== TRACKED FUNDS ({len(funds)}) ===")
    by_strategy = {}
    for f in funds:
        strat = f['strategy'] or 'other'
        if strat not in by_strategy:
            by_strategy[strat] = []
        by_strategy[strat].append(f)
    
    for strat, flist in sorted(by_strategy.items()):
        print(f"\n{strat.replace('_', ' ').title()}:")
        for f in flist:
            print(f"  • {f['name']} ({f['cik']}) — ${f['aum_estimate']:,.0f} AUM")
    
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="13F Scanner - Institutional Holdings Tracker")
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db", help="SQLite database path (defaults to unified purrtfolio.db)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # init
    p_init = subparsers.add_parser("init", help="Initialize database with schema and seed funds")
    p_init.add_argument("--seed", default="funds_seed.json", help="Seed JSON file")
    p_init.set_defaults(func=cmd_init)
    
    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest 13F filings via edgartools")
    p_ingest.add_argument("--email", default="13f-scanner@example.com", help="SEC identity email")
    p_ingest.add_argument("--max-filings", type=int, default=4, help="Max filings per fund")
    p_ingest.add_argument("--fund", help="Single fund CIK (optional)")
    p_ingest.add_argument("--quarter", help="Specific quarter YYYY-MM-DD (optional)")
    p_ingest.set_defaults(func=cmd_ingest)
    
    # compare
    p_compare = subparsers.add_parser("compare", help="Compute QoQ holding changes")
    p_compare.add_argument("--quarter", help="Quarter end YYYY-MM-DD (default: latest)")
    p_compare.add_argument("--fund", help="Single fund CIK (optional)")
    p_compare.add_argument("--backfill", action="store_true", help="Compute all historical quarters")
    p_compare.set_defaults(func=cmd_compare)
    
    # export
    p_export = subparsers.add_parser("export", help="Generate Excel analysis files")
    p_export.add_argument("--quarter", help="Quarter end YYYY-MM-DD")
    p_export.add_argument("--fund", help="Fund name or CIK")
    p_export.add_argument("--package", action="store_true", help="Generate full quarterly ZIP package")
    p_export.add_argument("--output-dir", default="exports", help="Output directory")
    p_export.set_defaults(func=cmd_export)
    
    # bot
    p_bot = subparsers.add_parser("bot", help="Run Discord bot")
    p_bot.add_argument("--token", required=True, help="Discord bot token")
    p_bot.add_argument("--admins", help="Comma-separated Discord user IDs for admin commands")
    p_bot.set_defaults(func=cmd_bot)
    
    # status
    p_status = subparsers.add_parser("status", help="Show database status")
    p_status.set_defaults(func=cmd_status)
    
    # list-funds
    p_list = subparsers.add_parser("list-funds", help="List all tracked funds")
    p_list.set_defaults(func=cmd_list_funds)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
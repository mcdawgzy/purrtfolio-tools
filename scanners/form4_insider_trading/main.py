"""
Form 4 Insider Trading Scanner — Main CLI Entry Point

Usage:
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db init
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db ingest latest
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db ingest backfill 2024Q1 2026Q2
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db analyze ticker AAPL
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db analyze signals
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db analyze summary
  python -m form4_insider_trading --db C:/Users/cho_i/purrtfolio.db status
"""
import argparse
import sys
import json
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Allow --db BEFORE subcommand (like 13f scanner's main.py)
def main():
    parser = argparse.ArgumentParser(
        description="Form 4 Insider Trading Scanner — SEC Forms 3/4/5 tracker"
    )
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db",
                        help="SQLite database path (defaults to unified purrtfolio.db)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize insider trading schema")
    p_init.set_defaults(func=cmd_init)

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Ingest SEC insider transaction data")
    p_ingest.add_argument("subcommand", choices=["latest", "backfill"],
                          help="'latest' for most recent quarter, 'backfill' for date range")
    p_ingest.add_argument("start_quarter", nargs="?", help="Start quarter (for backfill, e.g. 2024Q1)")
    p_ingest.add_argument("end_quarter", nargs="?", help="End quarter (for backfill, e.g. 2026Q2)")
    p_init.set_defaults(func=cmd_init)
    p_ingest.set_defaults(func=cmd_ingest)

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze insider data")
    p_analyze.add_argument("subcommand", choices=["ticker", "signals", "summary", "aggregation"],
                           help="Analysis type")
    p_analyze.add_argument("ticker_or_arg", nargs="?", help="Ticker symbol (for ticker analysis)")
    p_analyze.set_defaults(func=cmd_analyze)

    # status
    p_status = subparsers.add_parser("status", help="Show database status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()

    # Override DB_PATH for the scanner modules
    from . import config
    config.DB_PATH = Path(args.db)
    # Re-import db to pick up new DB_PATH
    import importlib
    from . import db
    importlib.reload(db)

    args.func(args)


def cmd_init(args):
    """Initialize insider trading schema."""
    from .db import init_insider_schema
    init_insider_schema()
    print("✅ Insider trading schema initialized")

    from .db import get_db
    with get_db() as conn:
        c = conn.cursor()
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'insider_%' ORDER BY name"
        ).fetchall()]
        print(f"Tables: {', '.join(tables)}")


def cmd_ingest(args):
    """Ingest SEC insider data."""
    from .ingest import ingest_quarter, backfill_quarters
    from .db import init_insider_schema

    init_insider_schema()

    if args.subcommand == "latest":
        from .ingest import _get_latest_available_quarter
        latest_q = _get_latest_available_quarter()
        print(f"Ingesting latest available quarter: {latest_q}")
        result = ingest_quarter(latest_q)
        print(json.dumps(result, indent=2, default=str))
    elif args.subcommand == "backfill":
        start = args.start_quarter
        end = args.end_quarter
        if not start or not end:
            print("Usage: ingest backfill START_QUARTER END_QUARTER (e.g. 2024Q1 2026Q2)")
            sys.exit(1)
        results = backfill_quarters(start, end)
        for r in results:
            print(json.dumps(r, indent=2, default=str))


def cmd_analyze(args):
    """Run analysis."""
    from .analyze import analyze_ticker, get_all_signals, get_market_summary, detect_aggregation_signals

    if args.subcommand == "ticker":
        if not args.ticker_or_arg:
            print("Usage: analyze ticker SYMBOL")
            sys.exit(1)
        print(json.dumps(analyze_ticker(args.ticker_or_arg.upper()), indent=2, default=str))
    elif args.subcommand == "signals":
        print(json.dumps(get_all_signals(), indent=2, default=str))
    elif args.subcommand == "summary":
        print(json.dumps(get_market_summary(), indent=2, default=str))
    elif args.subcommand == "aggregation":
        print(json.dumps(detect_aggregation_signals(), indent=2, default=str))


def cmd_status(args):
    """Show database status."""
    from .db import get_insider_meta
    meta = get_insider_meta()

    conn = sqlite3.connect(str(Path(args.db)))
    conn.row_factory = sqlite3.Row

    counts = {
        "submissions": conn.execute(
            "SELECT COUNT(*) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0],
        "owners": conn.execute("SELECT COUNT(*) FROM insider_owners").fetchone()[0],
        "transactions": conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0],
        "deriv_trans": conn.execute("SELECT COUNT(*) FROM insider_deriv_trans").fetchone()[0],
        "holdings": conn.execute("SELECT COUNT(*) FROM insider_holdings").fetchone()[0],
        "deriv_holdings": conn.execute("SELECT COUNT(*) FROM insider_deriv_holdings").fetchone()[0],
        "footnotes": conn.execute("SELECT COUNT(*) FROM insider_footnotes").fetchone()[0],
        "signatures": conn.execute("SELECT COUNT(*) FROM insider_signatures").fetchone()[0],
        "quarters": conn.execute(
            "SELECT COUNT(DISTINCT quarter) FROM insider_submissions WHERE quarter IS NOT NULL"
        ).fetchone()[0],
    }

    print("=== INSIDER TRADING DATABASE STATUS ===")
    print(f"DB: {args.db}")
    print(f"Form 4 filings:  {counts['submissions']:,}")
    print(f"Insiders:        {counts['owners']:,}")
    print(f"Transactions:    {counts['transactions']:,}")
    print(f"Derivative trans:{counts['deriv_trans']:,}")
    print(f"Quarters loaded: {counts['quarters']}")
    print(f"Latest filing:   {meta['latest_filing_date']}")
    print(f"Tickers covered: {meta['tickers_covered']}")
    print(f"Quarters:        {meta['quarters_available']}")

    conn.close()


def run() -> dict:
    """Main pipeline for cron execution.

    Returns a dict with status and results.
    Called by scripts/run_form4_insider_daily.py
    """
    from .db import init_insider_schema, sync_watchlist, get_insider_meta
    from .ingest import ingest_latest_quarter

    result = {"status": "ok", "results": []}

    try:
        init_insider_schema()
        sync_watchlist()

        meta = get_insider_meta()
        result["latest_data"] = meta

        ing = ingest_latest_quarter()
        result["processed_tickers"] = len(ing.get("tickers_ingested", []))
        result["new_records"] = ing.get("new_count", 0) or ing.get("new_rows", 0)
        result["updated_records"] = ing.get("updated_count", 0) or ing.get("updated_rows", 0)
        result["quarter"] = ing.get("quarter", "unknown")
        result["results"] = ing.get("ticker_results", [])
        result["status"] = "completed" if (result["new_records"] > 0 or result["updated_records"] > 0) else "no_new_data"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


if __name__ == "__main__":
    main()

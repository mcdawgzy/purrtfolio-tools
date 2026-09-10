"""
Main CLI entry point for Short Interest Scanner
"""
import sys
import json
from datetime import date

from .config import DB_PATH
from .db import init_db, get_ingestion_log
from .ingest import backfill, ingest_latest, sync_watchlist, get_finra_settlement_dates
from .analyze import analyze_ticker, get_all_signals, get_market_summary, get_category_summary, get_watchlist_performance
from .export import export_latest_csv, export_full_history_csv, export_ticker_csv, export_signals_json, export_signals_csv, export_category_csv, export_all_categories, create_summary_report
from .scheduler import run_once, start_scheduler


def print_usage():
    print("""
Short Interest Scanner - FINRA Bi-Weekly Short Interest Tracker

Usage: python -m short_interest_scanner <command> [args]

Commands:
  init-db                    Initialize database schema
  sync-watchlist             Sync ticker watchlist to database
  
  # Ingestion
  ingest latest              Ingest latest available settlement date
  ingest backfill START END  Backfill historical data (YYYY-MM-DD)
  ingest dates START END     List FINRA settlement dates in range
  
  # Scheduler
  schedule run-once          Run ingestion check once
  schedule start             Start daily scheduler (6 AM ET)
  
  # Analysis
  analyze ticker SYMBOL      Analyze single ticker
  analyze signals            Show all signal types
  analyze summary            Market summary
  analyze category CAT       Category summary
  analyze watchlist [CAT]    Watchlist performance
  
  # Export
  export latest              Export latest data to CSV
  export history             Export full history to CSV
  export ticker SYMBOL       Export single ticker history
  export signals             Export all signals to JSON
  export signals-csv         Export signals to separate CSVs
  export category CAT        Export category to CSV
  export all-categories      Export all categories to CSVs
  export report              Create HTML summary report
  
  # Utility
  log                        Show ingestion log
  help                       Show this help
""")


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "help":
        print_usage()
    
    elif cmd == "init-db":
        init_db()
        sync_watchlist()
    
    elif cmd == "sync-watchlist":
        init_db()
        sync_watchlist()
    
    elif cmd == "ingest":
        if len(sys.argv) < 3:
            print("Usage: python -m short_interest_scanner ingest <latest|backfill|dates> [args]")
            sys.exit(1)
        
        subcmd = sys.argv[2]
        
        if subcmd == "latest":
            init_db()
            sync_watchlist()
            import asyncio
            result = asyncio.run(ingest_latest())
            print(json.dumps(result, indent=2, default=str))
        
        elif subcmd == "backfill":
            if len(sys.argv) < 5:
                print("Usage: python -m short_interest_scanner ingest backfill START END")
                sys.exit(1)
            start = date.fromisoformat(sys.argv[3])
            end = date.fromisoformat(sys.argv[4])
            init_db()
            sync_watchlist()
            import asyncio
            asyncio.run(backfill(start, end))
        
        elif subcmd == "dates":
            if len(sys.argv) < 5:
                print("Usage: python -m short_interest_scanner ingest dates START END")
                sys.exit(1)
            start = date.fromisoformat(sys.argv[3])
            end = date.fromisoformat(sys.argv[4])
            dates = get_finra_settlement_dates(start, end)
            for d in dates:
                print(d)
        
        else:
            print(f"Unknown ingest command: {subcmd}")
    
    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: python -m short_interest_scanner schedule <run-once|start>")
            sys.exit(1)
        
        subcmd = sys.argv[2]
        
        if subcmd == "run-once":
            init_db()
            result = run_once()
            print(json.dumps(result, indent=2, default=str))
        
        elif subcmd == "start":
            start_scheduler()
        
        else:
            print(f"Unknown schedule command: {subcmd}")
    
    elif cmd == "analyze":
        if len(sys.argv) < 3:
            print("Usage: python -m short_interest_scanner analyze <ticker|signals|summary|category|watchlist> [args]")
            sys.exit(1)
        
        subcmd = sys.argv[2]
        
        if subcmd == "ticker":
            if len(sys.argv) < 4:
                print("Usage: python -m short_interest_scanner analyze ticker SYMBOL")
                sys.exit(1)
            result = analyze_ticker(sys.argv[3].upper())
            print(json.dumps(result, indent=2, default=str))
        
        elif subcmd == "signals":
            result = get_all_signals()
            for k, v in result.items():
                print(f"\n=== {k.upper()} ({len(v)}) ===")
                for item in v[:15]:
                    key_val = item.get('change_pct', item.get('days_to_cover', item.get('current_short', 'N/A')))
                    print(f"  {item['symbol']}: {key_val}")
        
        elif subcmd == "summary":
            result = get_market_summary()
            print(json.dumps(result, indent=2, default=str))
        
        elif subcmd == "category":
            if len(sys.argv) < 4:
                print("Usage: python -m short_interest_scanner analyze category CAT")
                sys.exit(1)
            result = get_category_summary(sys.argv[3])
            print(json.dumps(result, indent=2, default=str))
        
        elif subcmd == "watchlist":
            cat = sys.argv[3] if len(sys.argv) > 3 else None
            result = get_watchlist_performance(cat)
            print(json.dumps(result, indent=2, default=str))
        
        else:
            print(f"Unknown analyze command: {subcmd}")
    
    elif cmd == "export":
        if len(sys.argv) < 3:
            print("Usage: python -m short_interest_scanner export <command> [args]")
            sys.exit(1)
        
        subcmd = sys.argv[2]
        
        if subcmd == "latest":
            export_latest_csv()
        elif subcmd == "history":
            export_full_history_csv()
        elif subcmd == "ticker":
            if len(sys.argv) < 4:
                print("Usage: python -m short_interest_scanner export ticker SYMBOL")
                sys.exit(1)
            export_ticker_csv(sys.argv[3])
        elif subcmd == "signals":
            export_signals_json()
        elif subcmd == "signals-csv":
            export_signals_csv()
        elif subcmd == "category":
            if len(sys.argv) < 4:
                print("Usage: python -m short_interest_scanner export category CAT")
                sys.exit(1)
            export_category_csv(sys.argv[3])
        elif subcmd == "all-categories":
            export_all_categories()
        elif subcmd == "report":
            create_summary_report()
        else:
            print(f"Unknown export command: {subcmd}")
    
    elif cmd == "log":
        logs = get_ingestion_log(20)
        for log in logs:
            print(f"{log['settlement_date']}: {log['watchlist_rows']} watchlist, {log['new_rows']} new, {log['updated_rows']} updated - {log['status']}")
    
    else:
        print(f"Unknown command: {cmd}")
        print_usage()


if __name__ == "__main__":
    main()
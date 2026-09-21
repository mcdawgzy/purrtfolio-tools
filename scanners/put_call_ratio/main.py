"""
Main CLI entry point for Put/Call Ratio Scanner
"""
import sys
import json
import asyncio
from datetime import date

from .config import DB_PATH
from .db import init_db, get_latest_date, get_latest_series, get_history, get_signals, get_ingestion_log
from .ingest import ingest_date_async, ingest_latest, backfill, get_latest_available_date
from .scheduler import run_once, start_scheduler


def print_usage():
    print("""
Put/Call Ratio Scanner — CBOE Daily Market Sentiment

Usage: python -m put_call_ratio <command> [args]

Commands:
  init-db                   Initialize database schema

  # Ingestion
  ingest latest             Ingest most recent available date from CBOE
  ingest date YYYY-MM-DD    Ingest a specific date
  ingest backfill START END  Backfill date range (YYYY-MM-DD YYYY-MM-DD)

  # Scheduler
  schedule run-once         Run ingestion check once (cron mode)
  schedule start            Start daily scheduler (6 AM ET)

  # Query
  latest                    Show latest data for all series
  history SERIES [N]        Show N days of history (default 60)
  signals                   Show extreme readings
  log [N]                   Show ingestion log (default 20)

  help                      Show this help
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
    elif cmd == "ingest":
        if len(sys.argv) < 3:
            print("Usage: python -m put_call_ratio ingest <latest|date|backfill> [args]")
            sys.exit(1)
        subcmd = sys.argv[2]

        if subcmd == "latest":
            init_db()
            result = asyncio.run(ingest_latest())
            print(json.dumps(result, indent=2, default=str))

        elif subcmd == "date":
            if len(sys.argv) < 4:
                print("Usage: python -m put_call_ratio ingest date YYYY-MM-DD")
                sys.exit(1)
            init_db()
            d = date.fromisoformat(sys.argv[3])
            result = asyncio.run(ingest_date_async(d))
            print(json.dumps(result, indent=2, default=str))

        elif subcmd == "backfill":
            if len(sys.argv) < 5:
                print("Usage: python -m put_call_ratio ingest backfill START END")
                sys.exit(1)
            init_db()
            start = date.fromisoformat(sys.argv[3])
            end = date.fromisoformat(sys.argv[4])
            results = asyncio.run(backfill(start, end))
            print(json.dumps(results, indent=2, default=str))

        else:
            print(f"Unknown ingest command: {subcmd}")

    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: python -m put_call_ratio schedule <run-once|start>")
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

    elif cmd == "latest":
        latest = get_latest_date()
        if latest:
            print(f"Latest date in DB: {latest}")
        else:
            print("No data in DB yet")
        for s in get_latest_series():
            print(f"  {s['series']:12s} ratio={s['ratio']:.3f}  signal={s['signal']}  "
                  f"vol={s['total_volume']:,}  OI={s['total_oi']:,}")

    elif cmd == "history":
        if len(sys.argv) < 3:
            print("Usage: python -m put_call_ratio history <SERIES> [N]")
            sys.exit(1)
        series = sys.argv[2].upper()
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        rows = get_history(series, days)
        print(f"History for {series} ({len(rows)} rows):")
        for r in reversed(rows):  # oldest first
            print(f"  {r['date']}  ratio={r['ratio']:.3f}  ma5={r['ma5']:.3f}  "
                  f"ma20={r['ma20']:.3f}  z={r['z_score']:.2f}  signal={r['signal']}")

    elif cmd == "signals":
        signals = get_signals()
        if not signals:
            print("No extreme readings")
        else:
            for s in signals:
                print(f"  {s['series']:12s} ratio={s['ratio']:.3f}  z={s['z_score']:.2f}  "
                      f"signal={s['signal']}  (date={s['date']})")

    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        logs = get_ingestion_log(n)
        for log in logs:
            print(f"  {log['date']}  {log['status']}  rows={log['rows_inserted']}  "
                  f"started={log['started_at']}  err={log.get('error_message') or ''}")

    else:
        print(f"Unknown command: {cmd}")
        print_usage()


if __name__ == "__main__":
    main()

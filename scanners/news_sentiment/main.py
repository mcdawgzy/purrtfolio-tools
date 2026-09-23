"""
Main CLI entry point for News Sentiment Scanner

Usage:
  python -m news_sentiment <command> [args]

Commands:
  init-db              Initialize database schema
  ingest latest        Fetch latest headlines from all RSS feeds
  ingest date YYYY-MM-DD  Fetch headlines (filter by date where possible)
  schedule run-once    Run ingestion check once (cron mode)
  schedule start       Start daily scheduler (7 AM ET)
  latest [N]           Show N most recent headlines
  signals              Show top bullish/bearish tickers
  meta                 Show metadata
  log [N]              Show ingestion log (default 20)
  watchlist            Show loaded tickers
  help                 Show this help
"""
import sys
import json
import asyncio
from datetime import date

from .config import DB_PATH
from .db import init_db, get_latest_headlines, get_signals, get_meta, get_ingestion_log
from .ingest import ingest_date, ingest_latest, load_watchlist


def print_usage():
    print(__doc__)


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
            print("Usage: python -m news_sentiment ingest <latest|date YYYY-MM-DD>")
            sys.exit(1)
        subcmd = sys.argv[2]
        init_db()
        if subcmd == "latest":
            result = asyncio.run(ingest_latest())
            print(json.dumps(result, indent=2, default=str))
        elif subcmd == "date":
            if len(sys.argv) < 4:
                print("Usage: python -m news_sentiment ingest date YYYY-MM-DD")
                sys.exit(1)
            d = date.fromisoformat(sys.argv[3])
            result = ingest_date(d, load_watchlist())
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Unknown ingest command: {subcmd}")
            sys.exit(1)
    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: python -m news_sentiment schedule <run-once|start>")
            sys.exit(1)
        subcmd = sys.argv[2]
        if subcmd == "run-once":
            from .scheduler import run_once
            result = run_once()
            print(json.dumps(result, indent=2, default=str))
        elif subcmd == "start":
            from .scheduler import start_scheduler
            start_scheduler()
        else:
            print(f"Unknown schedule command: {subcmd}")
            sys.exit(1)
    elif cmd == "latest":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        headlines = get_latest_headlines(n)
        for h in headlines:
            print(f"  [{h['sentiment_label']:+.0>8}] {h['sentiment_score']:+.3f}  "
                  f"{h['source'][:12]:<12}  {h['title'][:100]}")
        print(f"\n{len(headlines)} headlines")
    elif cmd == "signals":
        sigs = get_signals(limit=50)
        if not sigs.get("bullish") and not sigs.get("bearish"):
            print("No signal data available yet")
        else:
            print(f"Latest date: {sigs.get('latest_date', '—')}")
            print("\n▲ BULLISH:")
            for r in sigs["bullish"][:15]:
                print(f"  {r['ticker']:>6}  avg={r['avg_sentiment']:+.3f}  "
                      f"n={r['headline_count']}  B:{r['bullish_count']} "
                      f"b:{r['bearish_count']} n:{r['neutral_count']}")
            print("\n▼ BEARISH:")
            for r in sigs["bearish"][:15]:
                print(f"  {r['ticker']:>6}  avg={r['avg_sentiment']:+.3f}  "
                      f"n={r['headline_count']}  B:{r['bullish_count']} "
                      f"b:{r['bearish_count']} n:{r['neutral_count']}")
    elif cmd == "meta":
        m = get_meta()
        print(json.dumps(m, indent=2, default=str))
    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for entry in get_ingestion_log(n):
            print(f"  {entry['started_at']}  {entry['status']}  "
                  f"feeds={entry['urls_checked']}  found={entry['headlines_found']}  "
                  f"stored={entry['headlines_stored']}  err={entry.get('error_message') or ''}")
    elif cmd == "watchlist":
        tickers = load_watchlist()
        print(f"{len(tickers)} tickers in watchlist:")
        print("  " + " ".join(tickers))
    else:
        print(f"Unknown command: {cmd}")
        print_usage()


if __name__ == "__main__":
    main()

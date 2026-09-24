"""
Main CLI entry point for IV Rank & IV Percentile Scanner.
"""
import sys
import json
from datetime import date

from .config import WATCHLIST, LOOKBACK_DAYS
from .db import init_db, get_latest_date, get_latest_iv, get_history, get_signals, get_ingestion_log
from .ingest import ingest_daily, get_atm_iv, fetch_all_ivs
from .scheduler import run_once


def print_usage():
    print(f"""
IV Rank & IV Percentile Scanner
Fetches ATM implied volatility via yfinance, computes 52-week IV Rank and IV Percentile.

Usage: python -m implied_volatility <command> [args]

Commands:
  init-db                   Initialize database schema
  ingest latest             Ingest today's IV data for all watchlist tickers ({len(WATCHLIST)} tickers)
  ingest date YYYY-MM-DD    Ingest IV data for a specific date
  fetch TICKER              Fetch current IV for a single ticker (debug)
  schedule run-once         Run ingestion check once (cron mode)
  latest                    Show latest IV Rank data for all tickers
  history TICKER [N]        Show N days of history for a ticker (default 30)
  signals                   Show HIGH_IV / LOW_IV signals
  log [N]                   Show ingestion log (default 20)
  watchlist                 Show configured watchlist
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
            print("Usage: python -m implied_volatility ingest <latest|date YYYY-MM-DD>")
            sys.exit(1)
        sub = sys.argv[2]
        if sub == "latest":
            init_db()
            result = ingest_daily(date.today())
            print(json.dumps(result, indent=2, default=str))
        elif sub == "date":
            if len(sys.argv) < 4:
                print("Usage: python -m implied_volatility ingest date YYYY-MM-DD")
                sys.exit(1)
            init_db()
            d = date.fromisoformat(sys.argv[3])
            result = ingest_daily(d)
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Unknown ingest command: {sub}")

    elif cmd == "fetch":
        if len(sys.argv) < 3:
            print("Usage: python -m implied_volatility fetch TICKER")
            sys.exit(1)
        ticker = sys.argv[2]
        iv = get_atm_iv(ticker)
        print(f"{ticker}: IV = {iv}%" if iv else f"{ticker}: no IV data")

    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: python -m implied_volatility schedule run-once")
            sys.exit(1)
        if sys.argv[2] == "run-once":
            init_db()
            result = run_once()
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Unknown schedule command: {sys.argv[2]}")

    elif cmd == "latest":
        latest = get_latest_date()
        if latest:
            print(f"Latest date in DB: {latest}")
        else:
            print("No data in DB yet")
        for r in get_latest_iv():
            print(f"  {r['ticker']:8s}  IV={r['iv']:.1f}%  Rank={str(r['iv_rank'] or '--'):>6}  "
                  f"Pctile={str(r['iv_pctile'] or '--'):>6}  signal={r['signal']}")

    elif cmd == "history":
        if len(sys.argv) < 3:
            print("Usage: python -m implied_volatility history <TICKER> [N]")
            sys.exit(1)
        ticker = sys.argv[2]
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        rows = get_history(ticker, days)
        print(f"History for {ticker.upper()} ({len(rows)} rows):")
        for r in rows:
            print(f"  {r['date']}  IV={r['iv']:.1f}  Rank={str(r['iv_rank'] or '--'):>6}  "
                  f"Pctile={str(r['iv_pctile'] or '--'):>6}  signal={r['signal']}")

    elif cmd == "signals":
        signals = get_signals()
        if not signals:
            print("No extreme readings")
        else:
            for s in signals:
                print(f"  {s['ticker']:8s}  IV={s['iv']:.1f}  Pctile={s['iv_pctile']:.1f}  "
                      f"signal={s['signal']}  (date={s['date']})")

    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for log in get_ingestion_log(n):
            print(f"  {log['date']}  {log['status']}  rows={log['rows_inserted']}  "
                  f"started={log['started_at']}  err={log.get('error_message') or ''}")

    elif cmd == "watchlist":
        print(f"Watchlist ({len(WATCHLIST)} tickers, {LOOKBACK_DAYS}-day lookback):")
        for t in WATCHLIST:
            print(f"  {t}")

    else:
        print(f"Unknown command: {cmd}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

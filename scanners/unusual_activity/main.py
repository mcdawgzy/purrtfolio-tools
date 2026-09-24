"""Main CLI entry point for Unusual Activity scanner."""
import sys
import json
from datetime import date

from .config import WATCHLIST
from .db import init_db, get_latest_date, get_latest_activity, get_signals, get_history, get_ingestion_log
from .ingest import scan_unusual_options, scan_volume_spikes, ingest_daily
from .scheduler import run_once


def print_usage():
    print(f"""
Unusual Activity / Dark Pool Scanner
Detects unusual options activity (high volume/OI ratio, large notional) and
volume spikes (dark-pool proxy) via yfinance for {len(WATCHLIST)} watchlist tickers.

Usage: python -m unusual_activity <command> [args]

Commands:
  init-db                   Initialize database schema
  ingest latest             Ingest today's activity for all watchlist tickers ({len(WATCHLIST)} tickers)
  ingest date YYYY-MM-DD    Ingest activity for a specific date
  scan TICKER               Scan a single ticker (debug)
  schedule run-once         Run ingestion check once (cron mode)
  latest                    Show latest activity for all tickers
  signals                   Show HIGH / EXTREME signals
  history TICKER [N]        Show N recent activities for a ticker (default 30)
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
            print("Usage: python -m unusual_activity ingest <latest|date YYYY-MM-DD>")
            sys.exit(1)
        sub = sys.argv[2]
        if sub == "latest":
            init_db()
            result = ingest_daily(date.today())
            print(json.dumps(result, indent=2, default=str))
        elif sub == "date":
            if len(sys.argv) < 4:
                print("Usage: python -m unusual_activity ingest date YYYY-MM-DD")
                sys.exit(1)
            init_db()
            d = date.fromisoformat(sys.argv[3])
            result = ingest_daily(d)
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Unknown ingest command: {sub}")

    elif cmd == "scan":
        if len(sys.argv) < 3:
            print("Usage: python -m unusual_activity scan TICKER")
            sys.exit(1)
        ticker = sys.argv[2]
        opts = scan_unusual_options(ticker)
        vol = scan_volume_spikes(ticker)
        print(f"\n=== Unusual Options for {ticker} ({len(opts)} results) ===")
        for a in opts[:10]:
            print(f"  {a['call_put']:4s} Strike={a['strike']:>8.2f} Vol={a['volume']:>6d} "
                  f"VOI={str(a['voi_ratio'] or '--'):>6} Notnl=${a['notional_usd']:,.0f} "
                  f"IV={str(a['iv_pct'] or '--'):>5} Sever={a['severity_score']:>5.1f} {a['signal']}")
        if vol:
            print(f"\n=== Volume Spike for {ticker} ===")
            print(f"  Vol={vol['volume']} Avg20d={vol['avg_vol_20d']:.0f} "
                  f"Ratio={vol['vol_ratio']} Notnl=${vol['notional_usd']:,.0f} {vol['signal']}")

    elif cmd == "schedule":
        if len(sys.argv) < 3:
            print("Usage: python -m unusual_activity schedule run-once")
            sys.exit(1)
        if sys.argv[2] == "run-once":
            init_db()
            result = run_once()
            print(json.dumps(result, indent=2, default=str))

    elif cmd == "latest":
        latest = get_latest_date()
        if latest:
            print(f"Latest date in DB: {latest}")
        else:
            print("No data in DB yet")
        for r in get_latest_activity():
            cp = r['call_put'] if r['call_put'] else "-"
            exp = r['expiry'] or "-"
            stk = f"{r['strike']:.0f}" if r['strike'] else "-"
            print(f"  {r['ticker']:8s} [{r['activity_type']:7s}] {cp:6s} {exp:>12s} K={stk:>6s} "
                  f"Vol={r['volume']:>8d} Notnl=${r['notional_usd']:,.0f} "
                  f"{r['signal']:8s} score={r['severity_score']}")

    elif cmd == "signals":
        signals = get_signals()
        if not signals:
            print("No HIGH/EXTREME signals")
        else:
            print(f"{len(signals)} HIGH/EXTREME signals:")
            for s in signals:
                print(f"  {s['ticker']:8s} [{s['activity_type']:7s}] {s['call_put'] or '-':6s} "
                      f"Notnl=${s['notional_usd']:,.0f} score={s['severity_score']:.1f} {s['signal']}")

    elif cmd == "history":
        if len(sys.argv) < 3:
            print("Usage: python -m unusual_activity history <TICKER> [N]")
            sys.exit(1)
        ticker = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        rows = get_history(ticker, n)
        print(f"History for {ticker.upper()} ({len(rows)} rows):")
        for r in rows:
            print(f"  {r['date']} [{r['activity_type']:7s}] {r['call_put'] or '-':6s} "
                  f"Vol={r['volume']:>8d} Notnl=${r['notional_usd']:,.0f} "
                  f"score={r['severity_score']:.1f} {r['signal']}")

    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for log in get_ingestion_log(n):
            print(f"  {log['date']}  {log['status']:>12s}  rows={log['rows_inserted']:>5d}  "
                  f"started={log['started_at']}  err={log.get('error_message') or ''}")

    elif cmd == "watchlist":
        print(f"Watchlist ({len(WATCHLIST)} tickers):")
        for t in WATCHLIST:
            print(f"  {t}")

    else:
        print(f"Unknown command: {cmd}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

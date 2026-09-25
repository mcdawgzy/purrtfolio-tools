"""Main CLI entry point for Crowded Trades Scanner.

Usage: python -m crowded_trades <command> [args]

Commands:
  analyze                    Run full crowded-trades analysis and print summary
  analyze ticker SYMBOL      Score a single ticker
  analyze signals            Show top crowded trades (score >= 30)
  analyze direction DIR      Filter by direction (long|short|bilateral|neutral)
  analyze summary            Market-level summary (signal counts, directions)
  analyze history TICKER     Show historical crowdedness for a ticker
  log [N]                    Show analysis log (default 20)
  help                       Show this help
"""
import sys
import json

from .config import DB_PATH
from .db import (
    init_db, get_top_crowded, get_by_direction, get_ticker_history,
    get_signal_summary, get_ingestion_log,
)
from .analyzer import analyze_all, score_single_ticker
from .scheduler import run_once


def print_usage():
    print(__doc__.strip())


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "help":
        print_usage()

    elif cmd == "analyze":
        if len(sys.argv) < 3:
            print("Usage: python -m crowded_trades analyze <ticker|signals|summary|history|direction> [args]")
            sys.exit(1)
        sub = sys.argv[2]

        if sub == "ticker":
            if len(sys.argv) < 4:
                print("Usage: python -m crowded_trades analyze ticker SYMBOL")
                sys.exit(1)
            init_db()
            sym = sys.argv[3].upper()
            from .analyzer import score_single_ticker
            result = score_single_ticker(sym)
            if result:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"No data for {sym}")

        elif sub == "signals":
            init_db()
            top = get_top_crowded(limit=30)
            if not top:
                print("No crowded trades data. Run 'analyze' first.")
                print("Run: python -m crowded_trades run")
                sys.exit(1)
            print(f"Top {len(top)} Crowded Trades (Score >= 30)\n")
            print(f"{'Ticker':<8s} {'Score':>6s} {'Direction':<10s} {'Signal':<8s} {'Short%':>6s} {'Long%':>6s} {'IV%':>6s} {'Opt%':>6s} {'Mom%':>6s}")
            print("-" * 75)
            for r in top:
                print(f"{r['ticker']:<8s} {r['crowdedness_score']:>6.1f} {r['crowd_direction']:<10s} {r['signal']:<8s} "
                      f"{r['short_crowd']:>6.1f} {r['long_crowd']:>6.1f} {r['iv_crowd']:>6.1f} {r['options_crowd']:>6.1f} {r['momentum_crowd']:>6.1f}")

        elif sub == "direction":
            if len(sys.argv) < 4:
                print("Usage: python -m crowded_trades analyze direction <long|short|bilateral|neutral>")
                sys.exit(1)
            init_db()
            d = sys.argv[3]
            results = get_by_direction(d)
            print(f"Crowded Trades — Direction: {d} ({len(results)} tickers)\n")
            for r in results:
                print(f"  {r['ticker']:<8s} Score={r['crowdedness_score']:.1f}  {r['signal']:<8s}  {r['short_crowd']:.1f}S / {r['long_crowd']:.1f}L")

        elif sub == "summary":
            init_db()
            summary = get_signal_summary()
            print(json.dumps(summary, indent=2, default=str))

        elif sub == "history":
            if len(sys.argv) < 4:
                print("Usage: python -m crowded_trades analyze history SYMBOL")
                sys.exit(1)
            init_db()
            hist = get_ticker_history(sys.argv[3].upper())
            print(f"History for {sys.argv[3].upper()}:")
            for r in reversed(hist):
                print(f"  {r['date']}  score={r['crowdedness_score']:.1f}  {r['crowd_direction']:<10s}  {r['signal']}")

        else:
            print(f"Unknown analyze command: {sub}")

    elif cmd == "run":
        init_db()
        result = run_once()
        if result.get("status") == "completed":
            print(f"Status: {result['status']}")
            print(f"Date: {result.get('date')}")
            print(f"Tickers scanned: {result.get('tickers_scanned', 0)}")
            print(f"Tickers with signals: {result.get('tickers_with_signals', 0)}")
            print(f"Signals found: {result.get('signals_found', 0)}")
            print(f"By signal: {result.get('by_signal', {})}")
            print(f"By direction: {result.get('by_direction', {})}")
            print("\nTop 10 Crowded Trades:")
            for r in result.get("top_crowded", []):
                print(f"  {r['ticker']:<8s} Score={r['score']:.1f}  {r['signal']:<8s}  {r['direction']}")
        else:
            print(json.dumps(result, indent=2, default=str))

    elif cmd == "dry-run":
        init_db()
        result = run_once(dry_run=True)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        init_db()
        logs = get_ingestion_log(n)
        for log in logs:
            print(f"  {log['date']}: {log['status']} — "
                  f"scanned={log['tickers_scanned']}, signals={log['signals_found']} "
                  f"({log.get('error_message') or 'OK'})")

    else:
        print(f"Unknown command: {cmd}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

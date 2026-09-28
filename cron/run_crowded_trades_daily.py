#!/usr/bin/env python
"""Hermes cron entry point: run Crowded Trades analysis daily.

Delegates to crowded_trades.scheduler.run_once(), which:
  1. Initializes the DB schema (idempotent)
  2. Loads the latest data from all upstream scanner tables:
     short_interest, put_call_latest, unusual_activity, iv_rank,
     price_momentum_signals, corr_matrices
  3. Computes a per-ticker crowdedness score (0-100) from six
     component signals (short, options, IV, momentum, PCR, correlation)
  4. Persists results to the crowded_trades table in purrtfolio.db
  5. Returns a summary dict with top crowded trades

Runs at 6:30 AM UTC+10 — after upstream scanners (5:00–6:15 AM).
The --script flag in the Hermes cron engine resolves this file by name
via a shim in ~/AppData/Local/hermes/scripts/ (see cron/README.md).

Usage:
  python run_crowded_trades_daily.py        # run via Hermes cron
  python run_crowded_trades_daily.py --json  # print full JSON result
  python run_crowded_trades_daily.py --dry   # dry run, no DB writes
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json

# Make the scanners package importable when run from any cwd
# (Hermes runs from its own workdir, not 13f-scanner-web/)
sys.path.insert(0, str(REPO / "scanners"))

from crowded_trades.scheduler import run_once  # noqa: E402


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    dry_run = "--dry" in sys.argv[1:]

    try:
        result = run_once(dry_run=dry_run)
    except Exception as e:  # pragma: no cover - surfaced to cron delivery
        print("Status: error")
        print(f"Error: {e}")
        return 1

    status = result.get("status", "unknown")

    if emit_json or dry_run:
        print(json.dumps(result, indent=2, default=str))
    else:
        if status == "no_data":
            print("Status: no_data")
            print(result.get("message", "No data available"))
            return 0

        if status == "error":
            print("Status: error")
            print(f"Error: {result.get('error')}")
            return 1

        # ── Human-readable Discord-friendly summary ──
        src = result.get("source_dates", {})
        print("=" * 60)
        print("🚨 CROWDED TRADES DAILY — " + result.get("date", "N/A"))
        print("=" * 60)

        print("\n📊 DATA BACKDROP")
        print(f"  Short Interest:   {src.get('short_interest', 'N/A')}")
        print(f"  Put/Call Ratio:   {src.get('put_call', 'N/A')}")
        print(f"  Unusual Activity: {src.get('unusual_activity', 'N/A')}")
        print(f"  IV Rank:          {src.get('iv_rank', 'N/A')}")
        print(f"  Price Momentum:   {src.get('momentum', 'N/A')}")
        print(f"  Correlation:      {src.get('correlation', 'N/A')}")

        by_sig = result.get("by_signal", {})
        by_dir = result.get("by_direction", {})
        ext = by_sig.get("EXTREME", 0)
        hi = by_sig.get("HIGH", 0)
        med = by_sig.get("MEDIUM", 0)
        neu = by_sig.get("NEUTRAL", 0)

        print("\n📈 SIGNAL SUMMARY")
        print(f"  Tickers scanned: {result.get('tickers_scanned', 0)}")
        print(f"  With signals:    {result.get('tickers_with_signals', 0)}")
        print(f"  EXTREME: {ext} | HIGH: {hi} | MEDIUM: {med} | NEUTRAL: {neu}")
        if by_dir:
            dir_str = " | ".join(f"{k}: {v}" for k, v in sorted(by_dir.items()))
            print(f"  Direction: {dir_str}")

        print("\n🔥 TOP 10 CROWDED TRADES")
        for r in result.get("top_crowded", []):
            print(f"  {r['ticker']:<6s}  Score={r['score']:>5.1f}  {r['signal']:<8s}  {r['direction']}")

        print("\n" + "=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

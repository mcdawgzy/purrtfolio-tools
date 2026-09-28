#!/usr/bin/env python
"""Hermes cron entry point: enrich tickers with factor classification.

Wraps `13f-scanner/enrich_factors.py` and uses the unified `purrtfolio.db`
so factor data is available for the web dashboard's Factor Exposure +
Crowded Trades views.

Runs weekly (same cadence as Sector Enrichment) to keep style-drift data
fresh between quarterly 13F ingestions.  Staleness-based --stale-days logic
means only tickers whose last classification is older than the threshold are
re-fetched, keeping each run fast and within yfinance rate limits.

Usage:
    python enrich_factors_cron.py
    python enrich_factors_cron.py --limit 200
    python enrich_factors_cron.py --refresh   # force full re-enrich
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import argparse
import subprocess
import sys


SCRIPTS_DIR = Path(__file__).parent
WORKDIR = REPO  # run as a module from the repo root
PURRTFOLIO_DB = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))
ENRICH_SCRIPT = REPO / "scanners" / "thirteen_f" / "enrich_factors.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron: enrich tickers with factor classification")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max tickers to (re)classify by AUM (default: all due)")
    parser.add_argument("--stale-days", type=int, default=30,
                        help="Re-enrich rows older than this (default: 30)")
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore staleness — re-enrich everything")
    args = parser.parse_args()

    if not ENRICH_SCRIPT.exists():
        print(f"ERROR: enrich script missing: {ENRICH_SCRIPT}", file=sys.stderr)
        return 2
    if not PURRTFOLIO_DB.exists():
        print(f"ERROR: unified DB missing: {PURRTFOLIO_DB}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PURRTFOLIO_DB"] = str(PURRTFOLIO_DB)

    cmd = [sys.executable, "-m", "scanners.thirteen_f.enrich_factors", "--db", str(PURRTFOLIO_DB)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    cmd += ["--stale-days", str(args.stale_days)]
    if args.refresh:
        cmd.append("--refresh")

    print(f"Enriching factors: {' '.join(cmd)}")
    print(f"Workdir: {WORKDIR}")
    print(f"Unified DB: {PURRTFOLIO_DB} ({PURRTFOLIO_DB.stat().st_size:,} bytes)")

    proc = subprocess.run(
        cmd, cwd=str(WORKDIR), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

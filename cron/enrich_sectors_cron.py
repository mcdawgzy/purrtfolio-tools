#!/usr/bin/env python
"""Hermes cron entry point: enrich tickers with GICS sector data.

Wraps `13f-scanner/enrich_sectors.py` and uses the unified `purrtfolio.db`
so sector data is available for the web dashboard's rotation view.

Usage:
    python enrich_sectors_cron.py
    python enrich_sectors_cron.py --limit 200   # override batch size for testing
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
ENRICH_SCRIPT = REPO / "scanners" / "thirteen_f" / "enrich_sectors.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron: enrich tickers with GICS sectors")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max tickers to process per run (default: 500)")
    args = parser.parse_args()

    if not ENRICH_SCRIPT.exists():
        print(f"ERROR: enrich script missing: {ENRICH_SCRIPT}", file=sys.stderr)
        return 2
    if not PURRTFOLIO_DB.exists():
        print(f"ERROR: unified DB missing: {PURRTFOLIO_DB}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PURRTFOLIO_DB"] = str(PURRTFOLIO_DB)

    print(f"Enriching sectors: {ENRICH_SCRIPT}")
    print(f"Workdir: {WORKDIR}")
    print(f"Unified DB: {PURRTFOLIO_DB} ({PURRTFOLIO_DB.stat().st_size:,} bytes)")

    proc = subprocess.run(
        [sys.executable, "-m", "scanners.thirteen_f.enrich_sectors",
         "--db", str(PURRTFOLIO_DB),
         "--limit", str(args.limit)],
        cwd=str(WORKDIR),
        env=env,
        capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

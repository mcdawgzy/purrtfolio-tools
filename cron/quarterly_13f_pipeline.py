#!/usr/bin/env python
"""Hermes cron entry point: run the 13F scanner quarterly pipeline.

Wraps `13f-scanner/quarterly_pipeline.py` and routes the database to the
unified `purrtfolio.db` so ingestion, comparison, and export all use the
canonical store (the legacy `13f_scanner.db` is mirrored + read-only).

Usage:
    python quarterly_13f_pipeline.py
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import subprocess
import sys


WORKDIR = REPO  # run as a module from the repo root
PIPELINE = REPO / "scanners" / "thirteen_f" / "quarterly_pipeline.py"
PURRTFOLIO_DB = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))


def main() -> int:
    if not PIPELINE.exists():
        print(f"ERROR: pipeline script missing: {PIPELINE}", file=sys.stderr)
        return 2
    if not PURRTFOLIO_DB.exists():
        print(f"ERROR: unified DB missing: {PURRTFOLIO_DB}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    # The pipeline / main.py read the DB path from --db or hardcoded constants.
    # Point both at the unified store so ingest/compare/export see the same data.
    env["PURRTFOLIO_DB"] = str(PURRTFOLIO_DB)

    print(f"Running quarterly pipeline: {PIPELINE}")
    print(f"Workdir: {WORKDIR}")
    print(f"Unified DB: {PURRTFOLIO_DB} ({PURRTFOLIO_DB.stat().st_size:,} bytes)")

    proc = subprocess.run(
        [sys.executable, "-m", "scanners.thirteen_f.quarterly_pipeline"],
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

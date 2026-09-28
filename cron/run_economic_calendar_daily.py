#!/usr/bin/env python3
"""Hermes cron entry point: economic calendar daily ingestion.

Follows the exact pattern of run_short_interest_daily.py:
  - Puts the repo root on sys.path (scanners is a package)
  - Delegates to main.py ingest --days 30
  - Prints Status/Error for cron delivery
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import json


# Make the scanner package importable when run from any cwd
sys.path.insert(0, str(REPO))

WORK_DIR = str(REPO / "snapshots" / "macro")


def main() -> int:
    emit_json = "--json" in sys.argv[1:]
    try:
        # Import after sys.path is set
        from scanners.economic_calendar.main import ingest

        result = ingest(days_ahead=30)

        if emit_json:
            print(json.dumps({"status": "ok", "exit_code": 0}, indent=2))
        else:
            print(f"Status: ok")
        return 0 if result == 0 else 1

    except Exception as e:
        if emit_json:
            print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        else:
            print(f"Status: error")
            print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

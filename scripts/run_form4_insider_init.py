#!/usr/bin/env python3
"""
DB initialization entry point for Form 4 insider trading scanner.

Creates tables in the unified purrtfolio.db if they don't exist.
"""
import sys
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SCANNER_DIR = PROJECT_ROOT / "scanners" / "form4_insider_trading"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCANNER_DIR))

from form4_insider_trading import config
from form4_insider_trading.db import init_insider_schema

if __name__ == "__main__":
    # DB path comes from PURRTFOLIO_DB (default ~/purrtfolio.db) via config
    init_insider_schema()
    print(f"Form 4 schema initialized in {config.DB_PATH}")

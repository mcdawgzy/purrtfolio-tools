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

from form4_insider_trading.main import init_db

if __name__ == "__main__":
    db_path = os.environ.get("PURRTFOLIO_DB", os.path.expanduser("c:\\Users\\cho_i\\purrtfolio.db"))
    init_db(db_path)
    print(f"Form 4 schema initialized in {db_path}")

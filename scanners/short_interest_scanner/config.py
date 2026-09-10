"""
Configuration for Short Interest Scanner
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
REFERENCES_DIR = BASE_DIR / "references"

DB_PATH = Path("C:/Users/cho_i/purrtfolio.db")
WATCHLIST_PATH = BASE_DIR / "ticker_watchlist.json"

# FINRA CDN
FINRA_CDN_BASE = "https://cdn.finra.org/equity/otcmarket/biweekly"

# Default analysis thresholds
SPIKE_THRESHOLD_PCT = 50.0      # % increase WoW to flag as spike
HIGH_DTC_THRESHOLD = 10.0       # Days to cover threshold
MIN_SHORT_POSITION = 1_000_000  # Minimum short for signal detection
COVERING_THRESHOLD_PCT = -30.0  # % decrease to flag as covering
NEW_SHORT_MULTIPLIER = 5.0      # 5x previous short = new short position

# Settlement date schedule
# FINRA publishes ~7 business days after settlement date
# Settlement dates: 15th and month-end (adjusted for weekends)

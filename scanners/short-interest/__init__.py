"""
Short Interest Scanner - FINRA Bi-Weekly Short Interest Tracker

Tracks short interest data for a curated watchlist of important tickers
from FINRA's bi-weekly consolidated short interest reports.
"""
__version__ = "0.1.0"
__author__ = "Hermes Agent"

from .config import (
    DB_PATH, DATA_DIR, EXPORTS_DIR, REFERENCES_DIR,
    FINRA_CDN_BASE, WATCHLIST_PATH,
    SPIKE_THRESHOLD_PCT, HIGH_DTC_THRESHOLD, MIN_SHORT_POSITION,
    COVERING_THRESHOLD_PCT, NEW_SHORT_MULTIPLIER
)

__all__ = [
    "DB_PATH", "DATA_DIR", "EXPORTS_DIR", "REFERENCES_DIR",
    "FINRA_CDN_BASE", "WATCHLIST_PATH",
    "SPIKE_THRESHOLD_PCT", "HIGH_DTC_THRESHOLD", "MIN_SHORT_POSITION",
    "COVERING_THRESHOLD_PCT", "NEW_SHORT_MULTIPLIER",
]
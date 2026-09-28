"""Configuration for Unusual Activity / Dark Pool scanner."""
import os
from pathlib import Path

from ..common import DB_PATH as COMMON_DB_PATH

DB_PATH = COMMON_DB_PATH  # PURRTFOLIO_DB, else ~/purrtfolio.db (scanners/common.py)

WATCHLIST = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "NVDA", "GOOGL", "META",
    "AMZN", "TSLA", "AVGO", "ASML", "AMD",
    "JPM", "BAC", "GS",
    "XOM", "CVX",
    "KO", "WMT", "MCD",
    "JNJ", "PFE",
    "CAT", "BA",
]

# Options anomaly thresholds
MIN_VOLUME = 200          # min contracts traded to flag
MIN_VOI_RATIO = 0.5       # min volume/openInterest ratio
MIN_NOTIONAL = 200_000    # min dollar notional to flag
MIN_SEVERITY = 20         # min composite severity score to store

# Volume-spike thresholds (dark-pool proxy)
MIN_VOL_RATIO = 3.0       # current vol / 20-day avg vol
MIN_VOL_SPIKE_NOTIONAL = 1_000_000  # min dollar volume to flag ($)

# Volume lookback for averages
VOL_LOOKBACK = 20         # days for volume average
PRICE_WINDOW_DAYS = 25    # yfinance history window

# Parallelism
MAX_WORKERS = 8

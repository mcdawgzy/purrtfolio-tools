"""Configuration for Earnings Revision Momentum scanner."""
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(Path.home() / "purrtfolio.db")))

# Same watchlist as Unusual Activity / Dark Pool scanner
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

# Minimum quarters of earnings history required for momentum score
MIN_QUARTERS = 4
# Parallelism
MAX_WORKERS = 8

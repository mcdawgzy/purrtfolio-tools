"""
Configuration for Implied Volatility (IV) Rank / Percentile Scanner.
Fetches ATM implied volatility via yfinance options chains.
Computes 52-week IV Rank and IV Percentile.
"""
import os
from pathlib import Path

# ── Database ──────────────────────────────────────────────
DB_DEFAULT = Path.home() / "purrtfolio.db"
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(DB_DEFAULT)))

# ── Curated watchlist: large-cap tickers with liquid options ──
WATCHLIST = [
    "^VIX", "^VXN",
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "NVDA", "GOOGL", "META",
    "AMZN", "TSLA", "AVGO", "ASML", "AMD",
    "JPM", "BAC", "GS",
    "XOM", "CVX",
    "KO", "WMT", "MCD",
    "JNJ", "PFE",
    "CAT", "BA",
]

# ── Lookback for IV Rank / Percentile ──────────────────────
LOOKBACK_DAYS = 252  # ~52 weeks of trading days

# ── IV Percentile thresholds (sell-side / buy-side signal) ───
IVP_HIGH_THRESHOLD = 70   # sell premium — IV is expensive
IVP_LOW_THRESHOLD = 30    # buy premium — IV is cheap

# ── Moving averages (days) for the history chart ───────────
MA_SHORT = 5
MA_MEDIUM = 20
MA_LONG = 52

# ── Parallel fetching ───────────────────────────────────────
MAX_WORKERS = 8

# ── Sanity bounds for IV (%) ───────────────────────────────
IV_MIN = 0.5     # 0.5 % — filter out zero / negative / glitch values
IV_MAX = 500.0   # 500 % — cap on sanity

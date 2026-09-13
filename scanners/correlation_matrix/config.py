"""Configuration for Correlation Matrix Scanner"""
import os
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
WATCHLIST_PATH = BASE_DIR / "ticker_watchlist.json"

# Canonical DB — same unified store as 13F / SI / insider
# Override with MOMENTUM_DB env var (used on Render — slim DB)
DB_PATH = Path(os.environ.get("MOMENTUM_DB", "C:/Users/cho_i/purrtfolio.db"))

# ─── Correlation windows (trading days) ──────────────────────────────
# 20d  ≈ 1 month, 60d ≈ 3 months, 120d ≈ 6 months, 252d ≈ 1 year
CORR_WINDOWS = {
    "1_month":   20,
    "3_month":   60,
    "6_month":   120,
    "12_month":  252,
}

# ─── Tickers used as correlation "pivot" columns ─────────────────────
# These are the broad asset-class anchors the user's macro snapshot tracks.
# The full watchlist rows are correlated against these pivot columns so
# the frontend can show "how does NVDA move with SPY / BTC / Gold / etc."
PIVOT_TICKERS = [
    "^GSPC",      # US large-cap
    "^NDX",       # US tech
    "^FTSE",      # Global
    "DX-Y.NYB",   # Dollar index
    "GC=F",       # Gold (safe haven)
    "CL=F",       # Oil (commodity)
    "HYG",        # High-yield credit (risk appetite)
    "^VIX",       # Volatility
    "BTC-USD",    # Crypto
    "TLT",        # Long-duration bonds
    "VNQ",        # REITs
]

# Full watchlist — same as price_momentum but we keep a reference for
# the correlation matrix rows (can be a superset for cross-checking).
# Import from the sibling module to avoid duplication.
try:
    from price_momentum.config import CURATED_TICKERS
    CORR_TICKERS = CURATED_TICKERS
except ImportError:
    CORR_TICKERS = []

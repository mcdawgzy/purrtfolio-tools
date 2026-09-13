"""
Price Momentum Scanner - Daily price history + momentum signals
for the curated Purrtfolio watchlist.

Reuses the yfinance price feed already used by the macro market snapshot
pipeline. Stores daily OHLCV in purrtfolio.db alongside the existing
13F / short-interest / insider data so correlation analysis can cross-join
everything in one place.
"""
__version__ = "0.1.0"
__author__ = "Hermes Agent"

from .config import (
    DB_PATH, DATA_DIR, EXPORTS_DIR, WATCHLIST_PATH,
    MOMENTUM_WINDOWS, VOLUME_SPIKE_THRESHOLD, MIN_PRICE_USD,
)

__all__ = [
    "DB_PATH", "DATA_DIR", "EXPORTS_DIR", "WATCHLIST_PATH",
    "MOMENTUM_WINDOWS", "VOLUME_SPIKE_THRESHOLD", "MIN_PRICE_USD",
]

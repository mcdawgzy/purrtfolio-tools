"""
Correlation Matrix - Cross-asset correlation analysis for the Purrtfolio watchlist.

Computes and stores rolling correlation matrices across the curated ticker
universe, enabling cross-referencing of price-momentum, 13F consensus,
short-interest, and insider-flow signals.

Uses the price_history table populated by the price_momentum scanner.
"""
__version__ = "0.1.0"
__author__ = "Hermes Agent"

from .config import (
    DB_PATH, DATA_DIR, EXPORTS_DIR, WATCHLIST_PATH,
    CORR_WINDOWS, PIVOT_TICKERS,
)

__all__ = [
    "DB_PATH", "DATA_DIR", "EXPORTS_DIR", "WATCHLIST_PATH",
    "CORR_WINDOWS", "PIVOT_TICKERS",
]

"""Configuration for Price Momentum Scanner"""
import json
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
WATCHLIST_PATH = BASE_DIR / "ticker_watchlist.json"

# Canonical DB (same unified store as 13F / SI / insider)
DB_PATH = Path("C:/Users/cho_i/purrtfolio.db")

# ─── Watchlist ─────────────────────────────────────────────────────
# Curated from the macro snapshot tickers + the SI watchlist overlap.
# Focus on large/important tickers per user preference.
CURATED_TICKERS = [
    # US Equities (indices + majors)
    "^GSPC", "^NDX", "^DJI", "^RUT",
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    "AVGO", "ASML", "AMD", "INTC", "CRM", "ADBE", "NFLX", "ORCL",
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW",
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY",
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY",
    "WMT", "HD", "PG", "KO", "PEP", "COST", "NKE", "MCD",
    # Global Equities
    "^N225", "^GDAXI", "^FTSE", "^STOXX", "^HSI",
    # FX
    "DX-Y.NYB", "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X",
    # Rates
    "^IRX", "^FVX", "^TNX", "^TYX",
    # Commodities
    "GC=F", "SI=F", "CL=F", "BZ=F", "HG=F",
    # Credit / Internals
    "HYG", "LQD", "TIP", "^VIX",
    # ETFs
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO",
    # Crypto
    "BTC-USD", "ETH-USD",
]

# Store the watchlist as JSON for downstream consumers
WATCHLIST_DATA = {
    "tickers": CURATED_TICKERS,
    "total": len(CURATED_TICKERS),
    "description": "Curated price-momentum watchlist (~50 tickers, large-cap focus)",
}

# ─── Momentum parameters ───────────────────────────────────────────
# Windows (in trading days) for rate-of-change / SMA cross signals.
MOMENTUM_WINDOWS = {
    "short": 10,   # ~2 weeks
    "medium": 20,  # ~1 month
    "long": 50,    # ~2-3 months
}

# Volume spike: flag if today's volume > median(volume_10d) * this
VOLUME_SPIKE_THRESHOLD = 2.0

# Minimum market cap filter (USD) — skip micro-caps
MIN_PRICE_USD = 5.0

# Daily price history retention (years)
HISTORY_RETENTION_YEARS = 5

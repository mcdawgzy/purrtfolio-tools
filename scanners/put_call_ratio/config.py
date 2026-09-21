"""
Configuration for Put/Call Ratio Scanner
Mirrors the pattern from scanners/short_interest_scanner/config.py.
CBOE data is free — no API keys required.
"""
import os
from pathlib import Path

# ── Database ──────────────────────────────────────────────
DB_DEFAULT = Path.home() / "purrtfolio.db"
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(DB_DEFAULT)))

# ── CBOE data source ────────────────────────────────────────
# Daily JSON feed: https://cdn.cboe.com/data/us/options/market_statistics/daily/{YYYY-MM-DD}_daily_options
# Returns: ratios[] (TOTAL, INDEX, EQUITY, ETP, VIX), volume/OI per category
CBOE_API_BASE = "https://cdn.cboe.com/data/us/options/market_statistics/daily"

# CBOE also publishes historical CSV archives (ending 2019-10-04):
#   https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{totalpc,equitypc,indexpc,vixpc,etppc}.csv
CBOE_CSV_BASE = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios"

# ── Series mapping ─────────────────────────────────────────
# JSON "ratios" name → canonical series key
SERIES_MAP = {
    "TOTAL PUT/CALL RATIO": "TOTAL",
    "INDEX PUT/CALL RATIO": "INDEX",
    "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO": "ETP",
    "EQUITY PUT/CALL RATIO": "EQUITY",
    "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO": "VIX",
    "SPX + SPXW PUT/CALL RATIO": "SPX_SPXW",
    "OEX PUT/CALL RATIO": "OEX",
    "MRUT PUT/CALL RATIO": "MRUT",
}

# JSON category section → canonical series key (for volume/OI lookup)
VOLUME_MAP = {
    "SUM OF ALL PRODUCTS": "TOTAL",
    "INDEX OPTIONS": "INDEX",
    "EXCHANGE TRADED PRODUCTS": "ETP",
    "EQUITY OPTIONS": "EQUITY",
    "CBOE VOLATILITY INDEX (VIX)": "VIX",
    "SPX + SPXW": "SPX_SPXW",
    "OEX": "OEX",
    "MRUT": "MRUT",
}

# ── Signal thresholds ──────────────────────────────────────
# High PCR = more puts (bearish sentiment / contrarian buy)
# Low PCR = more calls (bullish complacency / contrarian sell)
PCR_HIGH_THRESHOLD = 1.20     # bearish sentiment extreme
PCR_LOW_THRESHOLD = 0.60      # bullish sentiment extreme
MA_SHORT = 5                   # 5-day moving average
MA_MEDIUM = 20                 # 20-day moving average
MA_LONG = 50                   # 50-day moving average

# HTTP headers (CBOE CDN is fine with a basic UA, but be polite)
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}

# How many business days to look back when searching for latest data
MAX_LOOKBACK_DAYS = 10

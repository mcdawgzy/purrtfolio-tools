"""Configuration for Crowded Trades Scanner.

Mirrors the pattern from scanners/short_interest_scanner/config.py and
scanners/put_call_ratio/config.py: canonical DB path via PURRTFOLIO_DB
env var, analysis thresholds, and component weights.

Crowded Trades is an *analytics layer* — it does NOT download new data.
Instead it reads from the tables already populated by upstream cron jobs:
  - short_interest / ticker_short_meta  (Short Interest Daily, bi-weekly)
  - put_call_latest                     (Put/Call Ratio Daily)
  - unusual_activity                    (Unusual Activity Daily)
  - iv_rank                             (IV Rank Daily)
  - price_momentum_signals              (Price Momentum Daily)
  - corr_matrices                       (Correlation Matrix Daily)
"""
import os
from pathlib import Path
from typing import Dict, List

# ── Database ──────────────────────────────────────────────
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(Path.home() / "purrtfolio.db")))

# ── Watchlist ─────────────────────────────────────────────
# The crowded-trades universe is the curated short-interest watchlist
# (~120 large/important tickers with sector categories). We read it
# directly from the SI scanner's ticker_watchlist.json to avoid pulling
# the entire 13F universe (~12k tickers, mostly "uncategorized").
_SI_WATCHLIST = Path(__file__).parent.parent / "short_interest_scanner" / "ticker_watchlist.json"


def _load_watchlist() -> Dict[str, List[str]]:
    """Load the SI watchlist, returning {category: [tickers]}."""
    import json
    with open(_SI_WATCHLIST, "r") as f:
        wl = json.load(f)
    return wl["categories"]


# Pre-computed flat list of tickers + their categories
_WATCHLIST = _load_watchlist()
CURATED_TICKERS = sorted(
    {t for tickers in _WATCHLIST.values() for t in tickers}
)

# Map ticker → category for quick lookup
TICKER_CATEGORY = {t: cat for cat, ticks in _WATCHLIST.items() for t in ticks}

# ── Component weights (must sum to 1.0) ─────────────────────
# Short interest is the strongest single crowding signal, so it carries
# the highest weight. PCR and correlation are market-level backdrops.
COMPONENT_WEIGHTS = {
    "short":     0.25,   # short-interest crowding
    "options":   0.20,   # unusual options flow crowding
    "iv":        0.15,   # implied-volatility crowding
    "momentum":  0.20,   # price-momentum crowding
    "pcr":       0.10,   # put/call ratio market backdrop
    "corr":      0.10,   # cross-asset correlation (herding)
}

# ── Short crowding thresholds ──────────────────────────────
# Short interest ratio (short / float) thresholds
SIR_EXTREME = 0.20      # 20% of float short = extreme crowding
SIR_HIGH = 0.10         # 10% of float short = high crowding
# Days-to-cover thresholds
DTC_EXTREME = 10.0
DTC_HIGH = 5.0
# WoW change % thresholds (FINRA bi-weekly settlement)
SI_CHANGE_SPIKE = 30.0   # +30% WoW = new short crowding spike

# ── Options crowding thresholds ────────────────────────────
UA_SEVERITY_EXTREME = 80.0
UA_SEVERITY_HIGH = 60.0

# ── IV crowding thresholds ──────────────────────────────────
IVP_HIGH = 70.0   # 70th percentile IV = expensive options
IVP_LOW = 30.0    # 30th percentile IV = cheap options (not crowded)

# ── Momentum crowding thresholds ──────────────────────────
ROC_CROWDED = 0.15     # 15% 20-day ROC = crowded momentum
ROC_EXTREME = 0.30     # 30% 20-day ROC = extreme crowding

# ── PCR backdrop thresholds ────────────────────────────────
PCR_BEARISH = 0.85     # EQUITY PCR > 0.85 = bearish crowding
PCR_BULLISH = 0.50     # EQUITY PCR < 0.50 = bullish complacency

# ── Composite signal tiers ─────────────────────────────────
EXTREME_THRESHOLD = 70.0
HIGH_THRESHOLD = 50.0
MEDIUM_THRESHOLD = 30.0

# ── Correlation crowding ──────────────────────────────────
# Pivot tickers to check herding against
CORR_PIVOT = "^GSPC"    # S&P 500 as the broad-market reference
CORR_HERDING = 0.70     # |corr| >= 0.70 = significant herding

# ── Z-score significance for PCR ──────────────────────────
Z_SCORE_SIGNIFICANT = 1.5   # |z| >= 1.5 = statistically significant

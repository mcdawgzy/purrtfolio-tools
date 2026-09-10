"""Economic Calendar Scanner — Configuration.

Mirrors the pattern from scanners/short_interest_scanner/config.py.
All paths use the canonical purrtfolio.db location.
"""
import os
from pathlib import Path

# ── Database ──────────────────────────────────────────────
# Canonical unified DB — shared with 13F + Short Interest
_DB_DEFAULT = Path.home() / "purrtfolio.db"
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(_DB_DEFAULT)))

# ── Output ────────────────────────────────────────────────
EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Data sources ──────────────────────────────────────────
# Finnhub free-tier key (optional). When absent, a curated static
# list of high-impact US events is used instead.
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ── High-impact US economic events (fallback when Finnhub
#    key is unavailable).  Each: (event_name, month, day, time_et)
#    Updated quarterly alongside the macro snapshot schedule.
#    Source: Bureau of Labor Statistics, BEA, Census Bureau calendars.
HIGH_IMPACT_US_EVENTS_2026 = [
    # (name, month, day, time_et_24h)
    ("US Non-Farm Payrolls",        1,  8, "08:30"),  # Jan
    ("US CPI (MoM)",                1, 14, "08:30"),
    ("US PPI (MoM)",                1, 16, "08:30"),
    ("US Non-Farm Payrolls",        2,  5, "08:30"),
    ("US CPI (MoM)",                2, 11, "08:30"),
    ("US PPI (MoM)",                2, 13, "08:30"),
    ("US Non-Farm Payrolls",        3,  6, "08:30"),
    ("US CPI (MoM)",                3, 12, "08:30"),
    ("US PPI (MoM)",                3, 13, "08:30"),
    ("US GDP (QoQ)",                3, 27, "08:30"),  # Advance
    ("US Non-Farm Payrolls",        4,  3, "08:30"),
    ("US CPI (MoM)",                4, 10, "08:30"),
    ("US PPI (MoM)",                4, 11, "08:30"),
    ("US Non-Farm Payrolls",        5,  1, "08:30"),
    ("US CPI (MoM)",                5, 14, "08:30"),
    ("US PPI (MoM)",                5, 15, "08:30"),
    ("US Non-Farm Payrolls",        6,  5, "08:30"),
    ("US CPI (MoM)",                6, 11, "08:30"),
    ("US PPI (MoM)",                6, 12, "08:30"),
    ("US GDP (QoQ)",                6, 26, "08:30"),  # Advance
    ("US Non-Farm Payrolls",        7,  3, "08:30"),
    ("US CPI (MoM)",                7, 10, "08:30"),
    ("US PPI (MoM)",                7, 11, "08:30"),
    ("US Non-Farm Payrolls",        8,  7, "08:30"),
    ("US CPI (MoM)",                8, 13, "08:30"),
    ("US PPI (MoM)",                8, 14, "08:30"),
    ("US Non-Farm Payrolls",        9,  4, "08:30"),
    ("US CPI (MoM)",                9, 11, "08:30"),
    ("US PPI (MoM)",                9, 12, "08:30"),
    ("US GDP (QoQ)",                9, 25, "08:30"),  # Advance
    ("US Non-Farm Payrolls",       10,  2, "08:30"),
    ("US CPI (MoM)",               10, 14, "08:30"),
    ("US PPI (MoM)",               10, 15, "08:30"),
    ("US Non-Farm Payrolls",       11,  6, "08:30"),
    ("US CPI (MoM)",               11, 12, "08:30"),
    ("US PPI (MoM)",               11, 13, "08:30"),
    ("US Non-Farm Payrolls",       12,  4, "08:30"),
    ("US CPI (MoM)",               12, 10, "08:30"),
    ("US PPI (MoM)",               12, 11, "08:30"),
]

# ECB rate-decision dates (curated from ECB calendar page).
# Decision day = the day listed; time = 14:15 CET (typical).
ECB_RATE_DATES_2026 = [
    ("ECB Rate Decision", 6, 11),
    ("ECB Rate Decision", 7, 23),
    ("ECB Rate Decision", 9, 10),
    ("ECB Rate Decision", 10, 29),
    ("ECB Rate Decision", 12, 17),
]

# BOE MPC (Monetary Policy Committee) dates (curated from BOE website).
# Decision day = the day listed; time = 12:00 GMT (typical).
BOE_RATE_DATES_2026 = [
    ("BOE Rate Decision", 2,  6),
    ("BOE Rate Decision", 3, 20),
    ("BOE Rate Decision", 5,  8),
    ("BOE Rate Decision", 6, 19),
    ("BOE Rate Decision", 8,  7),
    ("BOE Rate Decision", 9, 18),
    ("BOE Rate Decision", 10, 29),
    ("BOE Rate Decision", 11,  5),
    ("BOE Rate Decision", 12, 17),
]

# BOJ monetary policy meeting dates (curated from BOJ website).
# Decision day = the last day of the range; time = 11:00 JST (typical).
BOJ_RATE_DATES_2026 = [
    ("BOJ Rate Decision", 1, 29),
    ("BOJ Rate Decision", 3, 19),
    ("BOJ Rate Decision", 5, 31),
    ("BOJ Rate Decision", 6, 16),
    ("BOJ Rate Decision", 7, 31),
    ("BOJ Rate Decision", 9, 18),
    ("BOJ Rate Decision", 10, 30),
    ("BOJ Rate Decision", 12, 18),
]

# ── Impact levels ──────────────────────────────────────────
IMPACT_HIGH = "high"
IMPACT_MEDIUM = "medium"
IMPACT_LOW = "low"

# ── Lookahead window ───────────────────────────────────────
# How many days ahead to keep events in the "upcoming" view.
UPCOMING_DAYS = 30

# ── HTTP headers (Fed sites require a real UA) ─────────────
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

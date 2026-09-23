"""
Configuration for News Sentiment Scanner.
Mirrors the pattern from scanners/put_call_ratio/config.py.

Data sources: free RSS feeds (no API keys required).
Sentiment analysis: VADER (NLTK) + financial-specific lexicon overlay.
"""
import os
from pathlib import Path

# ── Database (unified purrtfolio.db) ─────────────────────────────────
DB_DEFAULT = Path.home() / "purrtfolio.db"
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", str(DB_DEFAULT)))

# ── Watchlist ────────────────────────────────────────────────────────
# Reuse the short-interest watchlist (already curated, ~150 tickers).
# Falls back to a built-in list if the JSON file is missing.
WATCHLIST_PATH = (
    Path(__file__).parent.parent / "short_interest_scanner" / "ticker_watchlist.json"
)

# ── RSS feeds (free, no API key) ─────────────────────────────────────
# General financial market news feeds.  All return 200 with parseable
# RSS/Atom content as of 2026-09.
RSS_FEEDS = [
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/rss/",
        "category": "general",
    },
    {
        "name": "Yahoo Finance News",
        "url": "https://feeds.feedburner.com/yahoo/news",
        "category": "general",
    },
    {
        "name": "Seeking Alpha",
        "url": "https://seekingalpha.com/feed",
        "category": "general",
    },
    {
        "name": "Benzinga",
        "url": "https://www.benzinga.com/feed",
        "category": "general",
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories",
        "category": "general",
    },
    {
        "name": "Reddit r/investing",
        "url": "https://www.reddit.com/r/investing/.rss",
        "category": "discussion",
    },
]

# ── Sentiment thresholds ─────────────────────────────────────────────
# Map compound score → label
SENTIMENT_LABELS = [
    (-1.0, -0.15, "bearish"),
    (-0.15, 0.15, "neutral"),
    (0.15, 1.0, "bullish"),
]

# Signal thresholds for the signals tab
BULLISH_THRESHOLD = 0.3   # compound score ≥ 0.3 → notable bullish signal
BEARISH_THRESHOLD = -0.3  # compound score ≤ -0.3 → notable bearish signal

# Minimum headlines per ticker to compute an aggregate (avoid noise from 1 headline)
MIN_HEADLINES_FOR_AGGREGATE = 2

# How many recent headlines to keep per source in the latest view
LATEST_HEADLINES_LIMIT = 100

# How many days of history to show in ticker views
TICKER_HISTORY_DAYS = 30

# HTTP headers for RSS requests
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml;q=0.9,*/*;q=0.8",
}

# Max headlines to fetch per feed per run (to avoid stale data)
MAX_HEADLINES_PER_FEED = 30

# Max age of headlines to consider (hours)
MAX_HEADLINE_AGE_HOURS = 48

#!/usr/bin/env python3
"""
Hermes cron script: News Sentiment Daily Ingest
Scheduled daily via Hermes cron to fetch the latest financial headlines,
score sentiment, and aggregate per-ticker signals.
"""

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import sys
import subprocess


# ── locate the scanners directory ─────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCANNERS_DIR = os.path.join(SCRIPT_DIR, "..", "..", "13f-scanner-web", "scanners")
SCANNERS_DIR = os.path.normpath(SCANNERS_DIR)

# Also check the standard project location
if not os.path.isdir(SCANNERS_DIR):
    SCANNERS_DIR = str(REPO / "scanners")

# ── ensure nltk vader_lexicon is available ───────────────────────────
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    SentimentIntensityAnalyzer()
except LookupError:
    import nltk
    nltk.download("vader_lexicon", quiet=True)
except (ImportError, ModuleNotFoundError):
    pass  # NLTK not available — VADER disabled, financial lexicon will be used

# ── run the ingest ────────────────────────────────────────────────────
if __name__ == "__main__":
    if SCANNERS_DIR not in sys.path:
        sys.path.insert(0, SCANNERS_DIR)

    from news_sentiment.main import main as cli_main

    # news_sentiment ingest latest  →  uses argparse
    sys.argv = ["news_sentiment", "ingest", "latest"]
    cli_main()

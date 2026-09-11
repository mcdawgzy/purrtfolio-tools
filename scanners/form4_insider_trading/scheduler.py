"""
Scheduler for Form 4 insider trading data ingestion.

SEC publishes Insider Transactions Data Sets quarterly (~45 days after quarter end)
as ZIP files containing CSV chunk files, one per CIK (issuer).

This module determines whether a new dataset is available, downloads it,
and hands off to ingest.py for processing against the watchlist.
"""
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"


def get_latest_dataset_url() -> Optional[str]:
    """Check the SEC insider transactions page for the latest dataset URL.

    Returns the form4 ZIP download URL or None if the page structure changes.
    Falls back to a quarterly URL pattern if page scraping fails.
    """
    import urllib.request
    import urllib.error
    import re

    headers = {"User-Agent": "Hermes Agent (your@email.com)"}
    try:
        req = urllib.request.Request(BASE_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Look for href containing "form4.zip" or "insider-transactions" + ".zip"
        match = re.search(r'href="(https?://[^"]*(?:form4|insider-transactions)[^"]*\.zip)"', html, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning(f"Could not scrape SEC insider transactions page: {e}")

    # Fallback: construct expected quarterly URL
    # Format: https://www.sec.gov/files/insider_transactions/Q1_2024_form4.zip
    today = date.today()
    year = today.year
    # Determine current quarter
    quarter = (today.month - 1) // 3 + 1
    # The dataset for Q1 is usually available in Q2
    url = f"https://www.sec.gov/files/insider_transactions/Q{quarter}_{year}_form4.zip"
    logger.info(f"Falling back to constructed URL: {url}")
    return url


def is_new_dataset_available(data_dir: Path) -> bool:
    """Check if a new dataset should be downloaded by looking at the last run date.

    SEC data is published quarterly, so we run daily but only download when
    a new quarter's dataset is detected (or if we haven't run in 60+ days).
    """
    last_run_file = DATA_DIR / "last_run.txt" if False else data_dir / "last_run.txt"
    if not last_run_file.exists():
        return True
    try:
        last = datetime.fromisoformat(last_run_file.read_text().strip())
        if (datetime.now() - last).days >= 45:
            return True
    except Exception:
        return True
    return False


def record_run(data_dir: Path) -> None:
    """Record that this quarter's dataset has been processed."""
    (data_dir / "last_run.txt").write_text(datetime.now().isoformat())

"""
Scheduler for automatic News Sentiment ingestion.
Runs daily checks for new headlines from RSS feeds.
"""
import logging
from datetime import date
from typing import Optional

from .config import DB_PATH
from .db import init_db, get_latest_date
from .ingest import ingest_date, load_watchlist

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_once() -> dict:
    """Run ingestion once (for cron / Hermes engine).

    Fetches the latest headlines from all RSS feeds, scores sentiment,
    and stores results in the unified purrtfolio.db.
    """
    logger.info("Running scheduled News Sentiment ingestion check...")
    try:
        init_db()
        tickers = load_watchlist()
        logger.info(f"Watchlist: {len(tickers)} tickers")
        result = ingest_date(date.today(), tickers)
        logger.info(f"Ingested {result['headlines_stored']} new headlines from {result['urls_checked']} feeds")
        # The aggregation count is embedded in result
        return {
            "status": "completed",
            "date": str(date.today()),
            "urls_checked": result.get("urls_checked", 0),
            "headlines_found": result.get("headlines_found", 0),
            "headlines_stored": result.get("headlines_stored", 0),
        }
    except Exception as e:
        logger.error(f"Scheduled ingestion failed: {e}")
        return {"status": "error", "error": str(e)}


def start_scheduler():
    """Start the APScheduler for continuous mode (optional, not used by cron)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import asyncio

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.run(ingest_latest()),
        CronTrigger(hour=7, minute=0, timezone="US/Eastern"),
        id="daily_news_sentiment_check",
        name="Daily News Sentiment ingestion check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — will run daily at 7:00 AM ET")

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "once":
        result = run_once()
        print(result)
    else:
        start_scheduler()

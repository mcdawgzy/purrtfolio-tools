"""
Scheduler for automatic CBOE put/call ratio ingestion.
Runs daily checks for newly published daily data.
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import List, Optional

from .config import DB_PATH
from .ingest import get_latest_available_date, ingest_date_async, ingest_latest
from .db import init_db, get_latest_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_pending_date() -> Optional[date]:
    """Find the most recent business date that has CBOE data but isn't in our DB yet."""
    latest_in_db_str = get_latest_date()
    latest_available = get_latest_available_date()

    if latest_available is None:
        return None

    # If the latest available date is already in DB, check if there's a newer one
    if latest_in_db_str:
        from datetime import date as dt_date
        latest_in_db = dt_date.fromisoformat(latest_in_db_str)
        if latest_available <= latest_in_db:
            return None

    return latest_available


async def check_and_ingest() -> dict:
    """Check for new CBOE data and ingest if available."""
    logger.info("Running scheduled Put/Call Ratio ingestion check...")

    try:
        init_db()

        pending_date = get_pending_date()

        if pending_date is None:
            latest = get_latest_date() or "none"
            logger.info(f"No new data to ingest. Latest in DB: {latest}")
            return {
                "status": "no_new_data",
                "latest_in_db": latest,
            }

        logger.info(f"Found new data for {pending_date}")
        result = await ingest_date_async(pending_date)
        logger.info(f"Ingested {pending_date}: {result.get('rows_inserted', 0)} rows")

        return {
            "status": "completed",
            "date": str(pending_date),
            "result": result,
        }

    except Exception as e:
        logger.error(f"Scheduled ingestion failed: {e}")
        return {"status": "error", "error": str(e)}


def run_once() -> dict:
    """Run ingestion check once (for cron / Hermes engine)."""
    return asyncio.run(check_and_ingest())


def start_scheduler():
    """Start the APScheduler for continuous mode (optional, not used by cron)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    # Run daily at 6:00 AM ET (matches short interest schedule)
    scheduler.add_job(
        check_and_ingest,
        CronTrigger(hour=6, minute=0, timezone="US/Eastern"),
        id="daily_cboe_pcr_check",
        name="Daily CBOE Put/Call Ratio check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — will run daily at 6:00 AM ET")

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

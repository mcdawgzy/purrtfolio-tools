"""
Scheduler for automatic IV Rank ingestion.
Runs daily to fetch ATM implied volatility for all watchlist tickers
and compute IV Rank / IV Percentile.
"""
import logging
from datetime import date

from .config import DB_PATH
from .ingest import ingest_daily
from .db import init_db, get_latest_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_pending_date() -> date:
    """Return today's date if not yet ingested, else None."""
    latest_in_db = get_latest_date()
    today_str = date.today().isoformat()
    if latest_in_db and latest_in_db == today_str:
        return None
    return date.today()


async def check_and_ingest() -> dict:
    """Check for new data and ingest if needed."""
    logger.info("Running scheduled IV Rank ingestion check...")
    try:
        init_db()
        pending = get_pending_date()
        if pending is None:
            latest = get_latest_date() or "none"
            logger.info(f"No new data to ingest. Latest in DB: {latest}")
            return {"status": "no_new_data", "latest_in_db": latest}

        logger.info(f"Found new data for {pending}")
        result = ingest_daily(pending)
        logger.info(f"Ingested {pending}: {result.get('rows_inserted', 0)} rows")
        return {"status": "completed", "date": str(pending), "result": result}
    except Exception as e:
        logger.error(f"Scheduled ingestion failed: {e}")
        return {"status": "error", "error": str(e)}


def run_once() -> dict:
    """Run ingestion check once (for cron / Hermes engine)."""
    return asyncio_run(check_and_ingest())


def asyncio_run(coro):
    """Compatibility wrapper for asyncio.run."""
    import asyncio
    return asyncio.run(coro)

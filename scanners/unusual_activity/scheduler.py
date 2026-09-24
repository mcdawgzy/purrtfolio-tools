"""Scheduler for automatic Unusual Activity ingestion."""
import logging
from datetime import date

from .config import DB_PATH
from .ingest import ingest_daily
from .db import init_db, get_latest_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_pending_date() -> date:
    latest_in_db = get_latest_date()
    today_str = date.today().isoformat()
    if latest_in_db and latest_in_db == today_str:
        return None
    return date.today()


def check_and_ingest() -> dict:
    logger.info("Running scheduled Unusual Activity ingestion check...")
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
    """Run ingestion once (for cron / Hermes engine)."""
    return check_and_ingest()

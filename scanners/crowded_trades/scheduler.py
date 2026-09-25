"""Scheduler for Crowded Trades analysis.

Runs daily after upstream data scanners (SI, PCR, UA, IV, Momentum,
Correlation) have completed.  Reads the unified DB, computes crowding
scores, persists results, and returns a summary dict for the cron
delivery channel.

Unlike the upstream scanners (which download new data), this is a
pure analytics layer — it only reads existing tables.
"""
import logging
import json
from datetime import date
from typing import Optional

from .config import DB_PATH
from .db import init_db, get_db, get_ingestion_log, get_latest_ct_date
from .analyzer import analyze_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _log_run(date_str: str, status: str, tickers_scanned: int,
             signals_found: int, error: Optional[str] = None) -> None:
    """Write a row to ingestion_log_crowded."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ingestion_log_crowded
                (date, status, tickers_scanned, signals_found, error_message, completed_at)
            VALUES
                (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (date_str, status, tickers_scanned, signals_found, error),
        )


def run_once(dry_run: bool = False) -> dict:
    """Run the full crowded-trades analysis once (for cron / Hermes engine).

    Returns a dict with status, date, tickers_scanned, signals_found,
    and a top-crowded summary — mirroring the result shape used by
    short_interest_scanner.scheduler.run_once().
    """
    logger.info("Running Crowded Trades analysis...")
    today = str(date.today())

    try:
        init_db()

        if dry_run:
            result = analyze_all()
            logger.info(
                "Dry run: %d tickers with signals, %d found",
                result.get("tickers_with_signals", 0),
                result.get("signals_found", 0),
            )
            result["dry_run"] = True
            return result

        result = analyze_all()

        status = result.get("status", "unknown")
        if status == "no_data":
            logger.info("No data available — upstream scanners may not have run yet")
            _log_run(today, "no_data", 0, 0)
            return {
                "status": "no_data",
                "date": today,
                "tickers_scanned": 0,
                "signals_found": 0,
                "message": "No watchlist tickers found. Ensure upstream scanners have populated the DB.",
            }

        tickers_scanned = result.get("tickers_scanned", 0)
        signals_found = result.get("signals_found", 0)

        _log_run(today, "completed", tickers_scanned, signals_found)

        logger.info(
            "Crowded Trades analysis complete: %d tickers scanned, %d with signals (%d found)",
            tickers_scanned,
            result.get("tickers_with_signals", 0),
            signals_found,
        )
        result["status"] = "completed"
        return result

    except Exception as e:
        logger.error(f"Crowded Trades analysis failed: {e}")
        _log_run(today, "error", 0, 0, str(e))
        return {
            "status": "error",
            "error": str(e),
            "date": today,
        }


def start_scheduler():
    """Start the APScheduler for continuous mode (optional, not used by cron)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    # Run daily at 6:30 AM UTC+10 (after upstream scanners at 6:00 AM)
    scheduler.add_job(
        run_once,
        CronTrigger(hour=6, minute=30, timezone="Asia/Brisbane"),
        id="daily_crowded_trades",
        name="Daily Crowded Trades Analysis",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — will run daily at 6:30 AM UTC+10")

    try:
        import asyncio
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


def get_log(n: int = 20):
    """Show ingestion/analysis log."""
    return get_ingestion_log(n)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        result = run_once()
        print(json.dumps(result, indent=2, default=str))
    else:
        start_scheduler()

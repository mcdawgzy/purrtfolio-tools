"""
Scheduler for automatic FINRA short interest ingestion
Runs daily checks for newly published settlement dates
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import DB_PATH
from .ingest import get_finra_settlement_dates, ingest_date, sync_watchlist
from .db import init_db, get_ingestion_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def get_ingested_dates() -> set:
    """Get set of already-ingested settlement dates"""
    try:
        logs = get_ingestion_log(100)
        return {log['settlement_date'] for log in logs if log['status'] == 'completed'}
    except Exception:
        return set()

def get_pending_dates(max_lookback_days: int = 30) -> List[date]:
    """Get settlement dates that should be available but aren't ingested yet"""
    today = date.today()
    start_date = today - timedelta(days=max_lookback_days)
    
    # Get all settlement dates in range
    all_dates = get_finra_settlement_dates(start_date, today)
    
    # Filter to dates that should be published by now (7 business days after settlement)
    published_dates = []
    for d in all_dates:
        # Estimate publication date: 7 business days after settlement
        pub_date = d
        business_days = 0
        while business_days < 7:
            pub_date += timedelta(days=1)
            if pub_date.weekday() < 5:  # Mon-Fri
                business_days += 1
        
        if pub_date <= today:
            published_dates.append(d)
    
    # Return dates not yet ingested
    ingested = get_ingested_dates()
    pending = [d for d in published_dates if str(d) not in ingested]
    
    return sorted(pending)

async def check_and_ingest() -> dict:
    """Check for new data and ingest if available"""
    logger.info("Running scheduled ingestion check...")
    
    try:
        init_db()
        sync_watchlist()
        
        pending = get_pending_dates()
        
        if not pending:
            logger.info("No new settlement dates to ingest")
            return {'status': 'no_new_data', 'pending': 0}
        
        logger.info(f"Found {len(pending)} pending settlement dates: {pending}")
        
        results = []
        for d in pending:
            logger.info(f"Ingesting {d}...")
            result = await ingest_date(d)
            results.append(result)
            
            if 'error' not in result:
                logger.info(f"  Success: {result['watchlist_rows']} tickers, {result['new_rows']} new")
            else:
                logger.warning(f"  Failed: {result['error']}")
        
        return {
            'status': 'completed',
            'processed': len(results),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Scheduled ingestion failed: {e}")
        return {'status': 'error', 'error': str(e)}

def start_scheduler():
    """Start the APScheduler"""
    # Run daily at 6:00 AM ET (adjust timezone as needed)
    scheduler.add_job(
        check_and_ingest,
        CronTrigger(hour=6, minute=0, timezone='US/Eastern'),
        id='daily_finra_check',
        name='Daily FINRA short interest check',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started - will run daily at 6:00 AM ET")
    
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("Scheduler stopped")

def run_once() -> dict:
    """Run ingestion check once (for cron/systemd)"""
    return asyncio.run(check_and_ingest())

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        result = run_once()
        print(result)
    else:
        start_scheduler()
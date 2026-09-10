"""
Database layer for Short Interest Scanner - Unified Schema (purrtfolio.db)
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import date
import pandas as pd

from .config import DB_PATH

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initialize database schema - unified schema already created, just verify tables exist"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Verify unified schema tables exist
        tables = ['tickers', 'funds', 'filings_13f', 'holdings_13f', 'holding_changes_13f',
                  'short_interest', 'ticker_short_meta', 'ingestion_log_si', 'alerts']
        for table in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if not cursor.fetchone():
                print(f"WARNING: Table {table} not found in unified schema")
        
        # Watchlist is now handled via tickers.category in unified schema
        # Create a compatibility view if needed
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS watchlist AS
            SELECT ticker as symbol, category, created_at as added_at, is_active as active
            FROM tickers WHERE category IS NOT NULL
        """)
        
        conn.commit()
    print(f"Database verified at {DB_PATH}")

def get_latest_settlement_date() -> Optional[date]:
    """Get the most recent settlement date in the database"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(settlement_date) FROM short_interest")
        result = cursor.fetchone()
        if result and result[0]:
            return date.fromisoformat(result[0])
    return None

def get_ticker_history(symbol: str, limit: int = 26) -> List[Dict]:
    """Get historical short interest for a ticker"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT settlement_date, current_short, previous_short, 
                   days_to_cover, change_pct, change_abs, avg_daily_volume
            FROM short_interest
            WHERE symbol = ?
            ORDER BY settlement_date DESC
            LIMIT ?
        """, (symbol.upper(), limit))
        return [dict(row) for row in cursor.fetchall()]

def get_latest_snapshot(symbol: str) -> Optional[Dict]:
    """Get latest short interest for a ticker"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM short_interest
            WHERE symbol = ?
            ORDER BY settlement_date DESC
            LIMIT 1
        """, (symbol.upper(),))
        row = cursor.fetchone()
        return dict(row) if row else None

def search_tickers(query: str, limit: int = 20) -> List[Dict]:
    """Search tickers by symbol or name"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ticker as symbol, name, exchange, market_class, category, 
                   latest_short, latest_dtc, latest_change_pct
            FROM tickers
            WHERE ticker LIKE ? OR name LIKE ?
            ORDER BY 
                CASE WHEN ticker LIKE ? THEN 0 ELSE 1 END,
                latest_short DESC
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"{query.upper()}%", limit))
        return [dict(row) for row in cursor.fetchall()]

def get_spikes(min_change_pct: float = 50.0, min_short: int = 1_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers with largest % increase in short interest (latest period)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, si.avg_daily_volume,
                   t.category, t.exchange
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.change_pct >= ?
              AND si.current_short >= ?
            ORDER BY si.change_pct DESC
            LIMIT ?
        """, (min_change_pct, min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_high_dtc(min_dtc: float = 10.0, min_short: int = 1_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers with highest days-to-cover"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.days_to_cover,
                   si.avg_daily_volume, si.change_pct, t.category, t.exchange
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.days_to_cover >= ?
              AND si.current_short >= ?
            ORDER BY si.days_to_cover DESC
            LIMIT ?
        """, (min_dtc, min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_largest_positions(min_short: int = 1_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers with largest short positions"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.days_to_cover,
                   si.change_pct, t.category, t.exchange
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.current_short >= ?
            ORDER BY si.current_short DESC
            LIMIT ?
        """, (min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_covering(min_change_pct: float = -30.0, min_short: int = 1_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers with largest short covering (decrease)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, t.category
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.change_pct <= ?
              AND si.current_short >= ?
            ORDER BY si.change_pct ASC
            LIMIT ?
        """, (min_change_pct, min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_new_shorts(multiplier: float = 5.0, min_short: int = 1_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers where short position increased dramatically (new short)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.previous_short,
                   si.change_pct, si.change_abs, si.days_to_cover, t.category
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND si.previous_short > 0
              AND si.current_short >= si.previous_short * ?
              AND si.current_short >= ?
            ORDER BY (si.current_short * 1.0 / si.previous_short) DESC
            LIMIT ?
        """, (multiplier, min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_consensus_shorts(min_short: int = 5_000_000, limit: int = 50) -> List[Dict]:
    """Get tickers with consistently high short interest across periods"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, 
                   AVG(si.current_short) as avg_short,
                   COUNT(*) as periods,
                   MAX(si.current_short) as max_short,
                   MIN(si.current_short) as min_short,
                   t.category, t.exchange
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.current_short >= ?
            GROUP BY si.symbol, t.name, t.category, t.exchange
            HAVING periods >= 3
            ORDER BY avg_short DESC
            LIMIT ?
        """, (min_short, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_categories() -> List[str]:
    """Get all categories in watchlist"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM tickers WHERE category IS NOT NULL ORDER BY category")
        return [row[0] for row in cursor.fetchall()]

def get_category_summary(category: str) -> List[Dict]:
    """Get summary for a category"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT si.symbol, t.name, si.current_short, si.days_to_cover, si.change_pct
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
              AND t.category = ?
            ORDER BY si.current_short DESC
        """, (category,))
        return [dict(row) for row in cursor.fetchall()]

def get_ingestion_log(limit: int = 20) -> List[Dict]:
    """Get ingestion log"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ingestion_log_si ORDER BY started_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

def export_to_dataframe(query: str, params: tuple = ()) -> pd.DataFrame:
    """Export query results to pandas DataFrame"""
    with get_db() as conn:
        return pd.read_sql_query(query, conn, params=params)

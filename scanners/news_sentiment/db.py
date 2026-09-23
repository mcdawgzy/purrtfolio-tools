"""
Database layer for News Sentiment Scanner — Unified Schema (purrtfolio.db).
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from datetime import date

from .config import DB_PATH


@contextmanager
def get_db():
    """Context manager for database connections (same pattern as put_call_ratio)."""
    conn = sqlite3.connect(str(DB_PATH))
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
    """Create news_sentiment tables if they don't already exist."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Verify the unified schema's tickers table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickers'")
        if not cursor.fetchone():
            print("WARNING: 'tickers' table not found in unified schema — run the schema migration first")

        # Raw headlines with sentiment scores
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_headlines (
                id              TEXT PRIMARY KEY,
                source          TEXT NOT NULL,
                title           TEXT NOT NULL,
                url             TEXT,
                published_at    TIMESTAMP,
                retrieved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sentiment_score REAL,
                sentiment_label TEXT,
                tickers_mentioned TEXT
            )
        """)

        # Daily aggregated sentiment per ticker
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticker_news_sentiment (
                ticker          TEXT NOT NULL,
                date            DATE NOT NULL,
                headline_count  INTEGER DEFAULT 0,
                avg_sentiment   REAL,
                bullish_count   INTEGER DEFAULT 0,
                bearish_count   INTEGER DEFAULT 0,
                neutral_count   INTEGER DEFAULT 0,
                PRIMARY KEY (ticker, date)
            )
        """)

        # Ingestion audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_log_news (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at    TIMESTAMP,
                status          TEXT NOT NULL,
                urls_checked    INTEGER DEFAULT 0,
                headlines_found INTEGER DEFAULT 0,
                headlines_stored INTEGER DEFAULT 0,
                error_message   TEXT
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_published ON news_headlines(published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_source ON news_headlines(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_sentiment ON news_headlines(sentiment_score)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_tickers ON news_headlines(tickers_mentioned)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_news_date ON ticker_news_sentiment(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_news_ticker ON ticker_news_sentiment(ticker)")

        conn.commit()
    print(f"News Sentiment database schema ready at {DB_PATH}")


def get_latest_date() -> Optional[str]:
    """Get the most recent retrieved_at date in the headlines table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date(datetime(retrieved_at, 'localtime'))) FROM news_headlines")
        row = cursor.fetchone()
        return row[0] if row and row[0] else None


def get_latest_headlines(limit: int = 100) -> List[Dict]:
    """Get the most recent headlines across all sources."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, title, url, published_at,
                   sentiment_score, sentiment_label, tickers_mentioned
            FROM news_headlines
            ORDER BY retrieved_at DESC, published_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_ticker_sentiment(ticker: str, days: int = 30) -> List[Dict]:
    """Get news sentiment history for a single ticker."""
    ticker = ticker.upper().strip()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ticker, date, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker, days))
        rows = [dict(row) for row in cursor.fetchall()]
        rows.reverse()  # oldest first for charting
        return rows


def get_signals(limit: int = 50) -> Dict:
    """Get current bullish/bearish signal tickers from the latest aggregated data."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Latest date in the aggregated table
        latest_date = cursor.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]

        if not latest_date:
            return {"latest_date": None, "bullish": [], "bearish": [], "neutral": []}

        # Bullish tickers (highest avg sentiment, with meaningful headline count)
        bullish = cursor.execute("""
            SELECT ticker, date, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ?
              AND headline_count >= 2
              AND avg_sentiment >= 0.15
            ORDER BY avg_sentiment DESC, headline_count DESC
            LIMIT ?
        """, (latest_date, limit)).fetchall()

        # Bearish tickers
        bearish = cursor.execute("""
            SELECT ticker, date, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ?
              AND headline_count >= 2
              AND avg_sentiment <= -0.15
            ORDER BY avg_sentiment ASC, headline_count DESC
            LIMIT ?
        """, (latest_date, limit)).fetchall()

        return {
            "latest_date": latest_date,
            "bullish": [dict(r) for r in bullish],
            "bearish": [dict(r) for r in bearish],
            "neutral": [],
        }


def get_meta() -> Dict:
    """Top-level metadata for the news sentiment tab."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Latest headline date
        latest = cursor.execute(
            "SELECT MAX(date(datetime(retrieved_at, 'localtime'))) FROM news_headlines"
        ).fetchone()[0]

        # Total headlines
        total = cursor.execute(
            "SELECT COUNT(*) FROM news_headlines"
        ).fetchone()[0]

        # Distinct sources
        sources = cursor.execute(
            "SELECT DISTINCT source FROM news_headlines ORDER BY source"
        ).fetchall()

        # Latest signal date
        signal_date = cursor.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]

        # Signal counts
        signal_counts = {}
        if signal_date:
            for label in ("bullish", "bearish"):
                count = cursor.execute(
                    "SELECT COUNT(*) FROM ticker_news_sentiment "
                    "WHERE date = ? AND headline_count >= 2 "
                    "AND avg_sentiment >= ? ",
                    (signal_date, 0.15 if label == "bullish" else -999)
                ).fetchone()[0] if label == "bullish" else cursor.execute(
                    "SELECT COUNT(*) FROM ticker_news_sentiment "
                    "WHERE date = ? AND headline_count >= 2 "
                    "AND avg_sentiment <= -0.15",
                    (signal_date,)
                ).fetchone()[0]
                signal_counts[label] = count

        # Last ingestion log
        last_log = cursor.execute("""
            SELECT started_at, status, headlines_found, headlines_stored,
                   error_message
            FROM ingestion_log_news
            ORDER BY started_at DESC LIMIT 1
        """).fetchone()

        return {
            "latest_retrieved": latest,
            "total_headlines": total,
            "sources": [s[0] for s in sources],
            "latest_signal_date": signal_date,
            "signal_counts": signal_counts,
            "last_ingestion": dict(last_log) if last_log else None,
        }


def get_ticker_headlines(ticker: str, limit: int = 50) -> List[Dict]:
    """Get individual headlines mentioning a specific ticker."""
    ticker = ticker.upper().strip()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT source, title, url, published_at,
                   sentiment_score, sentiment_label
            FROM news_headlines
            WHERE tickers_mentioned LIKE ?
            ORDER BY published_at DESC
            LIMIT ?
        """, (f"%{ticker}%", limit))
        return [dict(row) for row in cursor.fetchall()]


def get_ingestion_log(limit: int = 20) -> List[Dict]:
    """Get ingestion log entries."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT started_at, completed_at, status,
                   urls_checked, headlines_found, headlines_stored,
                   error_message
            FROM ingestion_log_news
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

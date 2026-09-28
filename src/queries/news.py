"""News sentiment."""
from __future__ import annotations

from typing import Any

from ..database import db_conn, row_dicts, table_exists


# ---------------------------------------------------------------------------
# News Sentiment
# ---------------------------------------------------------------------------
def get_news_meta() -> dict:
    """Top-level news sentiment metadata: latest date, sources, counts, ingestion log."""
    with db_conn() as c:
        if not table_exists(c, "news_headlines"):
            return {"latest_date": None, "total_headlines": 0,
                    "sources": [], "signal_counts": {}, "last_ingestion": None}

        latest = c.execute(
            "SELECT MAX(date(datetime(retrieved_at, 'localtime'))) FROM news_headlines"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM news_headlines"
        ).fetchone()[0]
        sources = [r[0] for r in c.execute(
            "SELECT DISTINCT source FROM news_headlines ORDER BY source"
        ).fetchall()]
        signal_date = c.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]
        signal_counts = {}
        if signal_date:
            signal_counts["bullish"] = c.execute(
                "SELECT COUNT(*) FROM ticker_news_sentiment "
                "WHERE date = ? AND headline_count >= 2 AND avg_sentiment >= 0.15",
                (signal_date,)
            ).fetchone()[0]
            signal_counts["bearish"] = c.execute(
                "SELECT COUNT(*) FROM ticker_news_sentiment "
                "WHERE date = ? AND headline_count >= 2 AND avg_sentiment <= -0.15",
                (signal_date,)
            ).fetchone()[0]
        last_log = c.execute("""
            SELECT started_at, completed_at, status,
                   urls_checked, headlines_found, headlines_stored,
                   error_message
            FROM ingestion_log_news
            ORDER BY started_at DESC LIMIT 1
        """).fetchone()

        return {
            "latest_date": latest,
            "total_headlines": total,
            "sources": sources,
            "latest_signal_date": signal_date,
            "signal_counts": signal_counts,
            "last_ingestion": dict(last_log) if last_log else None,
        }


def get_news_headlines(limit: int = 100) -> list[dict[str, Any]]:
    """Latest headlines across all sources, newest first."""
    with db_conn() as c:
        if not table_exists(c, "news_headlines"):
            return []
        return row_dicts(c.execute("""
            SELECT id, source, title, url, published_at,
                   sentiment_score, sentiment_label, tickers_mentioned
            FROM news_headlines
            ORDER BY retrieved_at DESC, published_at DESC
            LIMIT ?
        """, (limit,)))


def local_date(ts: str) -> str | None:
    """SQLite's date(datetime(ts, 'localtime')) for a stored timestamp."""
    with db_conn() as c:
        return c.execute("SELECT date(datetime(?, 'localtime'))", (ts,)).fetchone()[0]


def get_news_ticker(ticker: str) -> dict | None:
    """Get news sentiment detail for a single ticker: latest aggregate + individual headlines."""
    ticker = ticker.upper().strip()
    with db_conn() as c:
        if not table_exists(c, "news_headlines"):
            return None
        agg = c.execute("""
            SELECT ticker, date, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT ?
        """, (ticker, 30)).fetchall()
        headlines = row_dicts(c.execute("""
            SELECT source, title, url, published_at,
                   sentiment_score, sentiment_label
            FROM news_headlines
            WHERE ',' || REPLACE(tickers_mentioned, ' ', '') || ',' LIKE ?
            ORDER BY published_at DESC
            LIMIT 50
        """, (f"%,{ticker.upper()},%",)))
        if not agg and not headlines:
            return None
        rows = row_dicts(agg)
        rows.reverse()  # oldest first
        return {
            "ticker": ticker,
            "history": rows,
            "headlines": headlines,
        }


def get_news_signals() -> dict:
    """Current bullish / bearish ticker signals from the latest aggregated data."""
    with db_conn() as c:
        if not table_exists(c, "news_headlines"):
            return {"latest_date": None, "bullish": [], "bearish": []}
        latest_date = c.execute(
            "SELECT MAX(date) FROM ticker_news_sentiment"
        ).fetchone()[0]
        if not latest_date:
            return {"latest_date": None, "bullish": [], "bearish": []}
        bullish = row_dicts(c.execute("""
            SELECT ticker, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ? AND headline_count >= 2 AND avg_sentiment >= 0.15
            ORDER BY avg_sentiment DESC, headline_count DESC
            LIMIT 20
        """, (latest_date,)))
        bearish = row_dicts(c.execute("""
            SELECT ticker, headline_count, avg_sentiment,
                   bullish_count, bearish_count, neutral_count
            FROM ticker_news_sentiment
            WHERE date = ? AND headline_count >= 2 AND avg_sentiment <= -0.15
            ORDER BY avg_sentiment ASC, headline_count DESC
            LIMIT 20
        """, (latest_date,)))
        return {
            "latest_date": latest_date,
            "bullish": bullish,
            "bearish": bearish,
        }

"""News sentiment."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import news as qry

router = APIRouter()


@router.get("/api/news/meta")
def news_meta():
    """Metadata: latest date, sources, headline count, signal counts, ingestion log."""
    return qry.get_news_meta()


@router.get("/api/news/headlines")
def news_headlines(limit: int = Query(100, ge=1, le=500, description="Max headlines to return")):
    """Latest headlines with sentiment scores (newest first)."""
    rows = qry.get_news_headlines(limit=limit)
    if not rows:
        return {"latest_date": None, "headlines": [],
                "note": "No data yet — scanner ingests daily at 6 AM ET"}
    latest = rows[0].get("retrieved_at") or rows[0].get("published_at")
    if latest:
        latest = qry.local_date(latest)
    return {"latest_date": latest, "headlines": rows}


@router.get("/api/news/tickers/{ticker}")
def news_ticker(ticker: str):
    """News sentiment detail for a single ticker: historical aggregates + headlines."""
    return qry.get_news_ticker(ticker) or {
        "ticker": ticker.upper(), "history": [], "headlines": [],
        "note": "No news sentiment data for this ticker yet",
    }


@router.get("/api/news/signals")
def news_signals():
    """Current bullish / bearish ticker signals from aggregated sentiment."""
    return qry.get_news_signals()

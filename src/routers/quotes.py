"""Famous trader quotes."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..queries import quotes as qry

router = APIRouter()


@router.get("/api/quotes")
def trader_quotes(
    category: str = Query("", description="Category filter (empty = all)"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
):
    """Famous trader quotes. Optionally filter by category."""
    return qry.get_trader_quotes(category=category, limit=limit)


@router.get("/api/quotes/meta")
def trader_quote_meta():
    """Available quote categories."""
    return {"categories": qry.get_trader_quote_categories()}


@router.get("/api/quotes/random")
def random_quote():
    """A single random trader quote."""
    return qry.get_random_trader_quote()

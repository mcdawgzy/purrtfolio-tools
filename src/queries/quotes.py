"""Famous trader quotes."""
from __future__ import annotations

from ..database import db_conn, writable_conn


# ---------------------------------------------------------------------------
# Famous Trader Quotes
# ---------------------------------------------------------------------------
def init_trader_quotes() -> None:
    """Create the trader_quotes table if it doesn't exist (writable)."""
    conn = writable_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trader_quotes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            author        TEXT    NOT NULL,
            quote         TEXT    NOT NULL,
            category      TEXT,
            source        TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trader_quotes_category
        ON trader_quotes(category)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trader_quotes_unique
        ON trader_quotes(author, quote)
    """)
    conn.commit()
    conn.close()


def get_trader_quotes(category: str = "", limit: int = 100) -> list[dict]:
    """Retrieve trader quotes, optionally filtered by category."""
    with db_conn() as c:
        if category:
            rows = c.execute(
                "SELECT author, quote, category, source "
                "FROM trader_quotes WHERE category = ? "
                "ORDER BY id",
                (category,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT author, quote, category, source "
                "FROM trader_quotes ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows][:limit]


def get_trader_quote_categories() -> list[str]:
    """Return distinct categories used in the trader_quotes table."""
    with db_conn() as c:
        rows = c.execute(
            "SELECT DISTINCT category FROM trader_quotes "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY category"
        ).fetchall()
    return [r[0] for r in rows]


def get_random_trader_quote() -> dict | None:
    """Return a single random quote."""
    with db_conn() as c:
        row = c.execute(
            "SELECT author, quote, category, source "
            "FROM trader_quotes ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    return dict(row) if row else None

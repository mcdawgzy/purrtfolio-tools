"""Economic calendar."""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..database import db_conn, row_dicts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Economic Calendar
# ---------------------------------------------------------------------------
def get_econ_events(
    *,
    days_ahead: int = 30,
    impact: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Upcoming economic calendar events from the economic_events table.

    Mirrors the read-only pattern from get_si_latest / get_si_signals.
    Returns empty list if the table doesn't exist yet (e.g. old DB mount).
    """
    with db_conn() as c:
        try:
            c.execute("SELECT 1 FROM economic_events LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            logger.warning("economic_events table not found in DB — returning empty")
            return []
        where: list[str] = [
            "event_date >= date('now')",
            f"event_date <= date('now', '+{days_ahead} days')",
        ]
        params: list[Any] = []
        if impact:
            where.append("impact = ?")
            params.append(impact)
        if category:
            where.append("category = ?")
            params.append(category)
        where_sql = " AND ".join(where)

        sql = f"""
            SELECT event_date, event_time, event_name, category, impact,
                   actual, prior, forecast, timezone_id, source, url
            FROM economic_events
            WHERE {where_sql}
            ORDER BY event_date, event_time
        """ + (" LIMIT ?" if limit else "")
        if limit:
            params.append(limit)
        rows = c.execute(sql, params).fetchall()
        return row_dicts(rows)


def get_econ_meta() -> dict:
    """Top-level economic calendar info: last refresh, categories, impact dist.

    Returns zeroed metadata if the table doesn't exist yet.
    """
    with db_conn() as c:
        try:
            c.execute("SELECT 1 FROM economic_events LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            logger.warning("economic_events table not found in DB — returning empty meta")
            return {"last_update": None, "upcoming_count": 0, "categories": []}
        last_update = c.execute(
            "SELECT MAX(updated_at) FROM economic_events"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE event_date >= date('now')"
        ).fetchone()[0]
        categories = [r[0] for r in c.execute(
            "SELECT DISTINCT category FROM economic_events "
            "WHERE event_date >= date('now') ORDER BY category"
        ).fetchall()]
        return {
            "last_update": last_update,
            "upcoming_count": total,
            "categories": categories,
        }

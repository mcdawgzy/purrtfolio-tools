"""Site-level metadata + health check."""
from __future__ import annotations

from ..config import get_db_path
from ..database import db_conn, row_dicts


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
def get_meta() -> dict:
    """Top-level site info: row counts, quarters available, last update."""
    with db_conn() as c:
        counts = {
            "funds": c.execute("SELECT COUNT(*) FROM funds").fetchone()[0],
            "filings": c.execute("SELECT COUNT(*) FROM filings_13f").fetchone()[0],
            "holdings": c.execute("SELECT COUNT(*) FROM holdings_13f").fetchone()[0],
            "changes": c.execute("SELECT COUNT(*) FROM holding_changes_13f").fetchone()[0],
            "unique_tickers": c.execute(
                "SELECT COUNT(DISTINCT ticker) FROM holdings_13f "
                "WHERE ticker IS NOT NULL AND ticker != ''"
            ).fetchone()[0],
        }
        quarters = row_dicts(c.execute("""
            SELECT report_period, COUNT(DISTINCT fund_cik) as funds_filing,
                   SUM(CASE WHEN has_infotable=1 THEN total_value_usd ELSE 0 END) as total_aum_usd
            FROM filings_13f
            GROUP BY report_period ORDER BY report_period DESC
        """))
        last_update = c.execute(
            "SELECT MAX(MAX(created_at, '')) FROM "
            "(SELECT MAX(created_at) as created_at FROM filings_13f "
            " UNION ALL SELECT MAX(created_at) FROM holdings_13f "
            " UNION ALL SELECT MAX(created_at) FROM holding_changes_13f)"
        ).fetchone()[0]
        return {
            "counts": counts,
            "quarters": quarters,
            "last_update": last_update,
        }


# ---------------------------------------------------------------------------
# Health (lightweight)
# ---------------------------------------------------------------------------
def health() -> dict:
    with db_conn() as c:
        ok = c.execute("SELECT 1").fetchone() is not None
        si_latest = c.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]
    return {"ok": ok, "db_file": get_db_path().name, "si_latest_settlement": si_latest}

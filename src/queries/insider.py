"""Form 4 insider trading."""
from __future__ import annotations

from typing import Any

from ..database import db_conn, row_dicts, table_exists


# ---------------------------------------------------------------------------
# Form 4 Insider Trading
# ---------------------------------------------------------------------------
def get_insider_meta() -> dict:
    """Top-level insider trading info: latest filing, form4 count, tickers covered."""
    with db_conn() as c:
        if not table_exists(c, "insider_submissions"):
            return {"latest_filing_date": None, "total_form4_filings": 0,
                    "tickers_covered": 0, "quarters_available": []}
        latest = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]
        total = c.execute(
            "SELECT COUNT(*) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]
        tickers = c.execute("""
            SELECT COUNT(DISTINCT issuertradingsymbol)
            FROM insider_submissions
            WHERE issuertradingsymbol IS NOT NULL
              AND issuertradingsymbol != ''
        """).fetchone()[0]
        quarters = [r[0] for r in c.execute("""
            SELECT DISTINCT quarter FROM insider_submissions
            WHERE quarter IS NOT NULL ORDER BY quarter DESC LIMIT 12
        """).fetchall()]
        return {
            "latest_filing_date": latest,
            "total_form4_filings": total,
            "tickers_covered": tickers,
            "quarters_available": quarters,
        }


def search_insider_tickers(query: str, limit: int = 30) -> list[dict]:
    """Search tickers that have insider transaction data."""
    with db_conn() as c:
        if not table_exists(c, "insider_submissions"):
            return []
        rows = c.execute("""
            SELECT DISTINCT
                t.ticker, COALESCE(t.name, s.issuername) AS name, COUNT(*) as tx_count
            FROM insider_submissions s
            LEFT JOIN tickers t ON t.ticker = s.issuertradingsymbol
            WHERE s.issuertradingsymbol LIKE ?
               OR t.name LIKE ?
               OR s.issuername LIKE ?
            GROUP BY COALESCE(t.ticker, s.issuertradingsymbol), COALESCE(t.name, s.issuername)
            ORDER BY tx_count DESC
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        return row_dicts(rows)


def get_insider_latest(ticker: str | None = None, limit: int = 100,
                       min_value: int | None = None) -> list[dict]:
    """Latest insider transactions, optionally filtered to a ticker.

    Joins submissions → owners → transactions. Filters to Form 4 filings.
    """
    ticker = ticker.upper().strip() if ticker else None
    with db_conn() as c:
        if not table_exists(c, "insider_submissions"):
            return []
        where: list[str] = ["s.document_type IN ('4', '4/A')"]
        params: list[Any] = []
        if ticker:
            where.append("s.issuertradingsymbol = ?")
            params.append(ticker)
        if min_value is not None:
            where.append("t.transaction_value_usd >= ?")
            params.append(min_value)
        where_sql = " AND ".join(where)

        rows = c.execute(f"""
            SELECT
                s.accession_number,
                s.filing_date,
                s.period_of_report,
                s.document_type,
                s.issuername,
                s.issuertradingsymbol as ticker,
                o.rptownercik,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.security_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.trans_acquired_disp_cd,
                t.trans_code,
                t.transaction_value_usd,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                t.direct_indirect_ownership,
                t.nature_of_ownership,
                t.trans_timeliness
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE {where_sql}
            ORDER BY s.filing_date DESC, t.trans_date DESC
            LIMIT ?
        """, (*params, limit)).fetchall()
        return row_dicts(rows)


def get_insider_ticker(symbol: str) -> dict | None:
    """Full insider trading history for a single ticker.

    Returns company info, insider list, and all transactions.
    """
    symbol = symbol.upper().strip()
    with db_conn() as c:
        if not table_exists(c, "insider_submissions"):
            return None

        # Basic ticker info from shared dimension
        t = c.execute(
            "SELECT ticker, name, sector, industry, category FROM tickers WHERE ticker = ?",
            (symbol,)
        ).fetchone()
        ticker_name = dict(t) if t else None

        # All transactions for this ticker
        rows = c.execute("""
            SELECT
                s.accession_number,
                s.filing_date,
                s.period_of_report,
                s.document_type,
                o.rptownercik,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.security_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.trans_acquired_disp_cd,
                t.trans_code,
                t.transaction_value_usd,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                t.direct_indirect_ownership,
                t.nature_of_ownership,
                t.trans_timeliness
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.issuertradingsymbol = ?
              AND s.document_type IN ('4', '4/A')
            ORDER BY s.filing_date DESC, t.trans_date DESC
        """, (symbol,)).fetchall()

        if not rows:
            return None

        transactions = row_dicts(rows)

        # Latest filing info
        latest = c.execute("""
            SELECT s.accession_number, s.filing_date, s.period_of_report,
                   s.document_type, s.issuername
            FROM insider_submissions s
            WHERE s.issuertradingsymbol = ?
              AND s.document_type IN ('4', '4/A')
            ORDER BY s.filing_date DESC LIMIT 1
        """, (symbol,)).fetchone()
        latest_info = dict(latest) if latest else None

        # Distinct insiders who traded
        insiders = []
        seen = set()
        for r in transactions:
            key = r["rptownername"]
            if key not in seen:
                seen.add(key)
                ins_txns = [tx for tx in transactions if tx["rptownername"] == key]
                buys = sum(tx.get("transaction_value_usd") or 0
                           for tx in ins_txns if tx["trans_acquired_disp_cd"] == "A")
                sells = sum(tx.get("transaction_value_usd") or 0
                            for tx in ins_txns if tx["trans_acquired_disp_cd"] == "D")
                insiders.append({
                    "name": key,
                    "cik": r.get("rptownercik"),
                    "relationship": r["rptowner_relationship"],
                    "title": r.get("rptowner_title"),
                    "tx_count": len(ins_txns),
                    "total_buy_value_usd": buys,
                    "total_sell_value_usd": sells,
                })

        # Aggregate totals
        total_buy = sum(tx.get("transaction_value_usd") or 0
                        for tx in transactions if tx["trans_acquired_disp_cd"] == "A")
        total_sell = sum(tx.get("transaction_value_usd") or 0
                         for tx in transactions if tx["trans_acquired_disp_cd"] == "D")

        return {
            "symbol": symbol,
            "company_name": ticker_name["name"] if ticker_name
                          else (latest_info["issuername"] if latest_info else None),
            "sector": ticker_name["sector"] if ticker_name else None,
            "industry": ticker_name["industry"] if ticker_name else None,
            "category": ticker_name["category"] if ticker_name else None,
            "latest_filing": latest_info,
            "insiders": insiders,
            "transactions": transactions,
            "total_transactions": len(transactions),
            "total_form4_filings": len(set(r["accession_number"] for r in transactions)),
            "total_buy_value_usd": total_buy,
            "total_sell_value_usd": total_sell,
            "net_value_usd": total_buy - total_sell,
        }


def get_insider_signals(limit: int = 100) -> dict:
    """Compute signal sets from recent insider transactions."""
    with db_conn() as c:
        if not table_exists(c, "insider_submissions"):
            return {"latest_filing_date": None, "top_buys": [], "top_sells": [], "officer_trades": []}

        latest_filing = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]

        buys = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.direct_indirect_ownership,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'A'
              AND t.trans_code IN ('P', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND t.direct_indirect_ownership = 'D'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        sells = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_relationship,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.direct_indirect_ownership,
                t.shrs_ownfollowingtrans,
                t.val_ownfollowingtrans,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'D'
              AND t.trans_code IN ('S', 'D', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND t.direct_indirect_ownership = 'D'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        officers = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_title,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                t.trans_acquired_disp_cd,
                t.trans_code,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND o.rptowner_relationship LIKE '%OFFICER%'
              AND t.trans_code IN ('P', 'S', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
            ORDER BY s.filing_date DESC, t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return {
            "latest_filing_date": latest_filing,
            "top_buys": row_dicts(buys),
            "top_sells": row_dicts(sells),
            "officer_trades": row_dicts(officers),
        }

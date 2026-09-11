"""
Analysis engine for Form 4 insider trading signals.
"""
import json
from typing import Any, Optional
from .db import get_db_readonly


def _row_dicts(rows):
    return [dict(r) for r in rows]


def analyze_ticker(symbol: str) -> dict[str, Any]:
    """Comprehensive insider trading analysis for a single ticker."""
    from .db import get_insider_ticker
    result = get_insider_ticker(symbol)
    if not result:
        return {"error": f"No insider data for {symbol}"}

    txns = result.get("transactions", [])

    # Aggregate buys vs sells
    buys = [t for t in txns if t.get("trans_acquired_disp_cd") == "A"]
    sells = [t for t in txns if t.get("trans_acquired_disp_cd") == "D"]

    total_buy_value = sum(t.get("transaction_value_usd") or 0 for t in buys)
    total_sell_value = sum(t.get("transaction_value_usd") or 0 for t in sells)
    net_value = total_buy_value - total_sell_value

    # Recent transactions (last 10 filings)
    recent = txns[:10]

    return {
        "symbol": result["symbol"],
        "company_name": result.get("company_name"),
        "sector": result.get("sector"),
        "industry": result.get("industry"),
        "latest_filing": result.get("latest_filing"),
        "insiders": result.get("insiders"),
        "total_transactions": result.get("total_transactions"),
        "total_form4_filings": result.get("total_form4_filings"),
        "total_buy_value_usd": total_buy_value,
        "total_sell_value_usd": total_sell_value,
        "net_value_usd": net_value,
        "net_direction": "BUY" if net_value > 0 else ("SELL" if net_value < 0 else "NEUTRAL"),
        "recent_transactions": recent,
    }


def get_all_signals(limit: int = 100) -> dict[str, Any]:
    """Get all insider trading signal sets."""
    from .db import get_insider_signals
    return get_insider_signals(limit=limit)


def get_market_summary() -> dict[str, Any]:
    """Market-level insider trading summary."""
    from .db import get_insider_meta
    meta = get_insider_meta()
    with get_db_readonly() as c:
        # Total transaction value
        row = c.execute("""
            SELECT
                COUNT(*) as total_txns,
                SUM(CASE WHEN trans_acquired_disp_cd = 'A' THEN transaction_value_usd ELSE 0 END) as total_buys,
                SUM(CASE WHEN trans_acquired_disp_cd = 'D' THEN transaction_value_usd ELSE 0 END) as total_sells,
                COUNT(DISTINCT issuertradingsymbol) as tickers_active
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
        """).fetchone()

        # Top tickers by insider buying
        top_buys = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                COUNT(*) as tx_count,
                SUM(t.transaction_value_usd) as total_buy_value
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'A'
              AND t.trans_code IN ('P', 'M', 'A', 'X', 'O')
              AND t.direct_indirect_ownership = 'Direct'
            GROUP BY s.issuertradingsymbol, s.issuername
            ORDER BY total_buy_value DESC
            LIMIT 20
        """).fetchall()

        # Top tickers by insider selling
        top_sells = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                COUNT(*) as tx_count,
                SUM(t.transaction_value_usd) as total_sell_value
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'D'
              AND t.trans_code IN ('S', 'D', 'X', 'O')
              AND t.direct_indirect_ownership = 'Direct'
            GROUP BY s.issuertradingsymbol, s.issuername
            ORDER BY total_sell_value DESC
            LIMIT 20
        """).fetchall()

    return {
        "meta": meta,
        "total_transactions": row["total_txns"] if row else 0,
        "total_buy_value_usd": row["total_buys"] if row else 0,
        "total_sell_value_usd": row["total_sells"] if row else 0,
        "net_value_usd": (row["total_buys"] or 0) - (row["total_sells"] or 0) if row else 0,
        "tickers_with_activity": row["tickers_active"] if row else 0,
        "top_buys": _row_dicts(top_buys),
        "top_sells": _row_dicts(top_sells),
    }


def detect_aggregation_signals(limit: int = 50) -> dict[str, Any]:
    """Detect insider buying/selling aggregation signals across the watchlist.

    - Concentrated buying: single ticker with multiple insiders buying
    - Concentrated selling: single ticker with multiple insiders selling
    - Large single trades: > $5M transactions
    - Officer buying: CEO/CFO/VP purchases
    """
    with get_db_readonly() as c:
        latest_period = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]

        # Concentrated buying — tickers with 3+ distinct insiders buying
        concentrated_buys = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                COUNT(DISTINCT o.rptownercik) as insiders_buying,
                SUM(t.transaction_value_usd) as total_buy_value
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND t.trans_acquired_disp_cd = 'A'
              AND t.trans_code IN ('P', 'M', 'A', 'X', 'O')
              AND t.direct_indirect_ownership = 'Direct'
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND s.filing_date >= date(?, '-180 days')
            GROUP BY s.issuertradingsymbol, s.issuername
            HAVING COUNT(DISTINCT o.rptownercik) >= 3
            ORDER BY total_buy_value DESC
            LIMIT ?
        """, (latest_period or "2025-01-01", limit)).fetchall()

        # Officer buying
        officer_buys = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptownertitle,
                t.trans_date,
                t.trans_shares,
                t.trans_pricepershare,
                t.transaction_value_usd,
                s.filing_date
            FROM insider_submissions s
            JOIN insider_owners o ON s.accession_number = o.accession_number
            JOIN insider_transactions t ON s.accession_number = t.accession_number
            WHERE s.document_type IN ('4', '4/A')
              AND o.rptowner_relationship = 'OFFICER'
              AND t.trans_acquired_disp_cd = 'A'
              AND t.trans_code IN ('P', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
              AND s.filing_date >= date(?, '-180 days')
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (latest_period or "2025-01-01", limit)).fetchall()

        # Large single trades (> $5M)
        large_trades = c.execute("""
            SELECT
                s.issuertradingsymbol as ticker,
                s.issuername,
                o.rptownername,
                o.rptowner_relationship,
                o.rptownertitle,
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
              AND t.transaction_value_usd >= 5000000
              AND t.direct_indirect_ownership = 'Direct'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return {
        "latest_filing_date": latest_period,
        "concentrated_buys": _row_dicts(concentrated_buys),
        "officer_buys": _row_dicts(officer_buys),
        "large_trades": _row_dicts(large_trades),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m form4_insider_trading.analyze <ticker|signals|summary>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "ticker":
        if len(sys.argv) < 3:
            print("Usage: python -m form4_insider_trading.analyze ticker SYMBOL")
            sys.exit(1)
        print(json.dumps(analyze_ticker(sys.argv[2].upper()), indent=2, default=str))
    elif cmd == "signals":
        print(json.dumps(get_all_signals(), indent=2, default=str))
    elif cmd == "summary":
        print(json.dumps(get_market_summary(), indent=2, default=str))
    elif cmd == "aggregation":
        print(json.dumps(detect_aggregation_signals(), indent=2, default=str))
    else:
        print(f"Unknown command: {cmd}")

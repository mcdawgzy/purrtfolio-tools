"""
Database layer for Form 4 Insider Trading Scanner.

Manages insider trading tables in the unified purrtfolio.db.
All operations use the shared tickers dimension (same as short interest scanner).

Schema mirrors the SEC Insider Transactions Data Sets (8 tab-delimited files,
flattened from the XML-based fillable portions of Forms 3, 4, and 5).
"""
import json
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

from .config import DB_PATH

logger = logging.getLogger(__name__)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Read-write connection to purrtfolio.db."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_db_readonly() -> Iterator[sqlite3.Connection]:
    """Read-only connection (mirrors the web db.py pattern)."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_insider_schema():
    """Create insider trading tables in the unified purrtfolio.db.

    Tables follow the SEC Insider Transactions Data Set structure (8 files):
      insider_submissions   — filing metadata (ACCESSION_NUMBER = PK)
      insider_owners        — insider/person details (reporter)
      insider_transactions  — non-derivative transactions (Form 4 Table 1)
      insider_holdings      — non-derivative holdings (Form 3/4 Table I holdings)
      insider_deriv_trans   — derivative transactions (Form 4 Table 2)
      insider_deriv_holdings — derivative holdings (Form 4 Table II)
      insider_footnotes     — footnote text
      insider_signatures    — signature data
      ingestion_log_insider — audit log

    The web dashboard focuses on insider_transactions + insider_owners
    (the actionable buy/sell data from Form 4).
    """
    with get_db() as conn:
        c = conn.cursor()

        # --- SUBMISSION: one row per Form 3/4/5 filing ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_submissions (
                accession_number        VARCHAR(25)  PRIMARY KEY,
                filing_date            DATE         NOT NULL,
                period_of_report       DATE         NOT NULL,
                date_of_orig_sub       DATE,
                no_securities_owned    VARCHAR(1),
                not_subject_sec16      VARCHAR(1),
                form3_holding_reported VARCHAR(1),
                form4_trans_reported   VARCHAR(1),
                document_type          VARCHAR(20)  NOT NULL,
                issuercik              VARCHAR(10)  NOT NULL,
                issuername             VARCHAR(150) NOT NULL,
                issuertradingsymbol    VARCHAR(10),
                remarks                VARCHAR(2000),
                quarter                VARCHAR(6),
                created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # --- REPORTINGOWNER: insider/person filing ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_owners (
                accession_number         VARCHAR(25)  NOT NULL
                    REFERENCES insider_submissions(accession_number),
                rptownercik              VARCHAR(10)  NOT NULL,
                rptownername             VARCHAR(150) NOT NULL,
                rptowner_relationship    VARCHAR(100) NOT NULL,
                rptowner_title           VARCHAR(150),
                rptowner_txt             VARCHAR(50),
                rptowner_street1         VARCHAR(150),
                rptowner_street2         VARCHAR(150),
                rptowner_city            VARCHAR(150),
                rptowner_state           VARCHAR(2),
                rptowner_zipcode         VARCHAR(10),
                rptowner_state_desc      VARCHAR(150),
                file_number              VARCHAR(30),
                PRIMARY KEY (accession_number, rptownercik)
            )
        """)

        # --- NONDERIV_TRANS: the actual buy/sell transactions ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_transactions (
                accession_number          VARCHAR(25)  NOT NULL
                    REFERENCES insider_submissions(accession_number),
                nonderiv_trans_sk         VARCHAR(20),  -- SEC field name preserved
                security_title            VARCHAR(60)  NOT NULL,
                security_title_fn         VARCHAR(150),
                trans_date                DATE         NOT NULL,
                trans_date_fn             VARCHAR(150),
                deemed_execution_date    DATE,
                deemed_execution_date_fn  VARCHAR(150),
                trans_form_type           VARCHAR(1),          -- A (acquired) or D (disposed)
                trans_code                VARCHAR(1),           -- P, S, M, A, G, etc.
                equity_swap_involved      VARCHAR(1),
                trans_timeliness          VARCHAR(1),           -- E, L, or '' (on-time)
                trans_timeliness_fn       VARCHAR(150),
                trans_shares              NUMBER(16,2),
                trans_shares_fn           VARCHAR(150),
                trans_pricepershare       NUMBER(16,2),
                trans_pricepershare_fn    VARCHAR(150),
                trans_acquired_disp_cd    VARCHAR(1),
                trans_acquired_disp_cd_fn VARCHAR(150),
                shrs_ownfollowingtrans    NUMBER(16,2),
                shrs_ownfollowingtrans_fn VARCHAR(150),
                val_ownfollowingtrans     NUMBER(16,2),
                val_ownfollowingtrans_fn  VARCHAR(150),
                direct_indirect_ownership VARCHAR(5)  NOT NULL,
                direct_indirect_ownership_fn VARCHAR(150),
                nature_of_ownership       VARCHAR(100),
                nature_of_ownership_fn    VARCHAR(150),
                transaction_value_usd     BIGINT,               -- computed: shares * price
                PRIMARY KEY (accession_number, nonderiv_trans_sk)
            )
        """)

        # Index for fast ticker-based lookups
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_insider_ticker_transdate
            ON insider_transactions (trans_date DESC, trans_shares)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_insider_sub_ticker
            ON insider_submissions (issuertradingsymbol, filing_date DESC)
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_insider_sub_owner
            ON insider_submissions (issuercik, filing_date DESC)
        """)

        # --- NONDERIV_HOLDING ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_holdings (
                accession_number          VARCHAR(25)  NOT NULL
                    REFERENCES insider_submissions(accession_number),
                nonderiv_holding_sk       VARCHAR(20),
                security_title            VARCHAR(60)  NOT NULL,
                security_title_fn         VARCHAR(150),
                trans_form_type           VARCHAR(1),
                trans_form_type_fn        VARCHAR(150),
                shrs_ownfollowingtrans    NUMBER(16,2),
                shrs_ownfollowingtrans_fn VARCHAR(150),
                val_ownfollowingtrans     NUMBER(16,2),
                val_ownfollowingtrans_fn  VARCHAR(150),
                direct_indirect_ownership VARCHAR(5)  NOT NULL,
                direct_indirect_ownership_fn VARCHAR(150),
                nature_of_ownership       VARCHAR(100),
                nature_of_ownership_fn    VARCHAR(150),
                PRIMARY KEY (accession_number, nonderiv_holding_sk)
            )
        """)

        # --- DERIV_TRANS ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_deriv_trans (
                accession_number          VARCHAR(25)  NOT NULL
                    REFERENCES insider_submissions(accession_number),
                deriv_trans_sk            VARCHAR(20),
                security_title            VARCHAR(60)  NOT NULL,
                security_title_fn         VARCHAR(150),
                conv_exercise_price       NUMBER(16,2),
                conv_exercise_price_fn    VARCHAR(150),
                trans_date                DATE         NOT NULL,
                trans_date_fn             VARCHAR(150),
                deemed_execution_date    DATE,
                deemed_execution_date_fn  VARCHAR(150),
                trans_form_type           VARCHAR(1),
                trans_code                VARCHAR(1),
                equity_swap_involved      VARCHAR(1),
                trans_timeliness          VARCHAR(1),
                trans_timeliness_fn       VARCHAR(150),
                trans_shares              NUMBER(16,2),
                trans_shares_fn           VARCHAR(150),
                trans_total_value        NUMBER(16,2),
                trans_total_value_fn      VARCHAR(150),
                trans_pricepershare       NUMBER(16,2),
                trans_pricepershare_fn    VARCHAR(150),
                trans_acquired_disp_cd    VARCHAR(1),
                trans_acquired_disp_cd_fn VARCHAR(150),
                shrs_ownfollowingtrans    NUMBER(16,2),
                shrs_ownfollowingtrans_fn VARCHAR(150),
                val_ownfollowingtrans     NUMBER(16,2),
                val_ownfollowingtrans_fn  VARCHAR(150),
                direct_indirect_ownership VARCHAR(5)  NOT NULL,
                direct_indirect_ownership_fn VARCHAR(150),
                nature_of_ownership       VARCHAR(100),
                nature_of_ownership_fn    VARCHAR(150),
                underlying_sec_title      VARCHAR(20),
                underlying_sec_title_fn   VARCHAR(150),
                underlying_sec_shares     NUMBER(16,2),
                underlying_sec_shares_fn  VARCHAR(150),
                underlying_sec_value      NUMBER(16,2),
                underlying_sec_value_fn   VARCHAR(150),
                exercise_date             DATE,
                exercise_date_fn          VARCHAR(150),
                expiration_date           DATE,
                expiration_date_fn        VARCHAR(150),
                PRIMARY KEY (accession_number, deriv_trans_sk)
            )
        """)

        # --- DERIV_HOLDING ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_deriv_holdings (
                accession_number          VARCHAR(25)  NOT NULL
                    REFERENCES insider_submissions(accession_number),
                deriv_holding_sk          VARCHAR(20),
                security_title            VARCHAR(60)  NOT NULL,
                security_title_fn         VARCHAR(150),
                conv_exercise_price       NUMBER(16,2),
                conv_exercise_price_fn    VARCHAR(150),
                trans_form_type           VARCHAR(1),
                trans_form_type_fn        VARCHAR(150),
                exercise_date             DATE,
                exercise_date_fn          VARCHAR(150),
                expiration_date           DATE,
                expiration_date_fn        VARCHAR(150),
                underlying_sec_title      VARCHAR(20),
                underlying_sec_title_fn   VARCHAR(150),
                underlying_sec_shares     NUMBER(16,2),
                underlying_sec_shares_fn  VARCHAR(150),
                underlying_sec_value      NUMBER(16,2),
                underlying_sec_value_fn   VARCHAR(150),
                shrs_ownfollowingtrans    NUMBER(16,2),
                shrs_ownfollowingtrans_fn VARCHAR(150),
                val_ownfollowingtrans     NUMBER(16,2),
                val_ownfollowingtrans_fn  VARCHAR(150),
                direct_indirect_ownership VARCHAR(5)  NOT NULL,
                direct_indirect_ownership_fn VARCHAR(150),
                nature_of_ownership       VARCHAR(100),
                nature_of_ownership_fn    VARCHAR(150),
                PRIMARY KEY (accession_number, deriv_holding_sk)
            )
        """)

        # --- FOOTNOTES ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_footnotes (
                accession_number  VARCHAR(25) NOT NULL
                    REFERENCES insider_submissions(accession_number),
                footnote_id       VARCHAR(10) NOT NULL,
                footnote_text     VARCHAR(2000) NOT NULL,
                PRIMARY KEY (accession_number, footnote_id)
            )
        """)

        # --- OWNER_SIGNATURE ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS insider_signatures (
                accession_number       VARCHAR(25) NOT NULL
                    REFERENCES insider_submissions(accession_number),
                ownersignaturename     VARCHAR(255) NOT NULL,
                ownersignaturedate     DATE,
                PRIMARY KEY (accession_number, ownersignaturename)
            )
        """)

        # --- Ingestion log ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_log_insider (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                quarter         VARCHAR(6),
                total_submissions INTEGER,
                watchlist_submissions INTEGER,
                new_rows        INTEGER,
                updated_rows    INTEGER,
                status          TEXT,
                started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at    TIMESTAMP
            )
        """)

        conn.commit()
        logger.info("Insider trading schema initialized")


def _row_dicts(rows):
    return [dict(r) for r in rows]


def get_insider_meta() -> dict:
    """Metadata: latest filing date, total submissions, tickers covered."""
    with get_db_readonly() as c:
        latest = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions"
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
        quarters = [r[0] for r in c.execute(
            "SELECT DISTINCT quarter FROM insider_submissions WHERE quarter IS NOT NULL ORDER BY quarter DESC LIMIT 12"
        ).fetchall()]
        return {
            "latest_filing_date": latest,
            "total_form4_filings": total,
            "tickers_covered": tickers,
            "quarters_available": quarters,
        }


def search_insider_tickers(query: str, limit: int = 30) -> list[dict]:
    """Search tickers that have insider transaction data."""
    with get_db_readonly() as c:
        rows = c.execute("""
            SELECT DISTINCT t.ticker, t.name, COUNT(*) as tx_count
            FROM insider_submissions s
            JOIN tickers t ON t.ticker = s.issuertradingsymbol
            WHERE s.issuertradingsymbol LIKE ?
               OR t.name LIKE ?
               OR s.issuername LIKE ?
            GROUP BY t.ticker, t.name
            ORDER BY tx_count DESC
            LIMIT ?
        """, (f"%{query.upper()}%", f"%{query}%", f"%{query}%", limit)).fetchall()
        return _row_dicts(rows)


def get_insider_latest(ticker: str | None = None, limit: int = 100) -> list[dict]:
    """Latest insider transactions, optionally filtered to a ticker.

    Joins submissions → owners → transactions to produce the rich
    buy/sell rows the frontend renders.
    """
    ticker = ticker.upper().strip() if ticker else None
    with get_db_readonly() as c:
        if ticker:
            rows = c.execute("""
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
                    t.nature_of_ownership
                FROM insider_submissions s
                JOIN insider_owners o ON s.accession_number = o.accession_number
                JOIN insider_transactions t ON s.accession_number = t.accession_number
                WHERE s.issuertradingsymbol = ?
                  AND s.document_type IN ('4', '4/A')
                ORDER BY s.filing_date DESC
                LIMIT ?
            """, (ticker, limit)).fetchall()
        else:
            rows = c.execute("""
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
                    t.nature_of_ownership
                FROM insider_submissions s
                JOIN insider_owners o ON s.accession_number = o.accession_number
                JOIN insider_transactions t ON s.accession_number = t.accession_number
                WHERE s.document_type IN ('4', '4/A')
                ORDER BY s.filing_date DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return _row_dicts(rows)


def get_insider_ticker(symbol: str) -> dict | None:
    """Full insider trading history for a single ticker.

    Returns company info, insider list, and all transactions.
    """
    symbol = symbol.upper().strip()
    with get_db_readonly() as c:
        # Basic ticker info from shared dimension
        t = c.execute(
            "SELECT ticker, name, sector, industry, category FROM tickers WHERE ticker = ?",
            (symbol,)
        ).fetchone()
        ticker_name = dict(t) if t else None

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

        # All transactions for this ticker
        rows = c.execute("""
            SELECT
                s.accession_number,
                s.filing_date,
                s.period_of_report,
                s.document_type,
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

        transactions = _row_dicts(rows)

        # Distinct insiders who traded
        insiders = []
        seen = set()
        for r in transactions:
            key = r["rptownername"]
            if key not in seen:
                seen.add(key)
                insiders.append({
                    "name": key,
                    "relationship": r["rptowner_relationship"],
                    "title": r.get("rptowner_title"),
                    "total_tx_count": len([tx for tx in transactions if tx["rptownername"] == key]),
                })

        # Aggregate: total buy/sell value per insider
        for insider in insiders:
            ins_txns = [tx for tx in transactions if tx["rptownername"] == insider["name"]]
            buys = sum(tx["transaction_value_usd"] or 0 for tx in ins_txns if tx["trans_acquired_disp_cd"] == "A")
            sells = sum(tx["transaction_value_usd"] or 0 for tx in ins_txns if tx["trans_acquired_disp_cd"] == "D")
            insider["total_buy_value_usd"] = buys
            insider["total_sell_value_usd"] = sells

        return {
            "symbol": symbol,
            "company_name": ticker_name["name"] if ticker_name else latest_info["issuername"] if latest_info else None,
            "sector": ticker_name["sector"] if ticker_name else None,
            "industry": ticker_name["industry"] if ticker_name else None,
            "category": ticker_name["category"] if ticker_name else None,
            "latest_filing": latest_info,
            "insiders": insiders,
            "transactions": transactions,
            "total_transactions": len(transactions),
            "total_form4_filings": len(set(r["accession_number"] for r in transactions)),
        }


def get_insider_owner(owner_cik: str | None = None, limit: int = 50) -> list[dict]:
    """Transactions by a specific insider (by CIK), or top insiders overall."""
    with get_db_readonly() as c:
        if owner_cik:
            rows = c.execute("""
                SELECT
                    s.accession_number,
                    s.filing_date,
                    s.issuername,
                    s.issuertradingsymbol as ticker,
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
                    t.val_ownfollowingtrans
                FROM insider_submissions s
                JOIN insider_owners o ON s.accession_number = o.accession_number
                JOIN insider_transactions t ON s.accession_number = t.accession_number
                WHERE o.rptownercik = ?
                  AND s.document_type IN ('4', '4/A')
                ORDER BY s.filing_date DESC
                LIMIT ?
            """, (owner_cik, limit)).fetchall()
        else:
            # Top insiders by total transaction value
            rows = c.execute("""
                SELECT
                    o.rptownercik,
                    o.rptownername,
                    o.rptowner_relationship,
                    COUNT(*) as tx_count,
                    SUM(t.transaction_value_usd) as total_value_usd,
                    MAX(s.filing_date) as last_filing
                FROM insider_submissions s
                JOIN insider_owners o ON s.accession_number = o.accession_number
                JOIN insider_transactions t ON s.accession_number = t.accession_number
                WHERE s.document_type IN ('4', '4/A')
                GROUP BY o.rptownercik, o.rptownername, o.rptowner_relationship
                ORDER BY total_value_usd DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return _row_dicts(rows)


def get_insider_signals(limit: int = 100) -> dict:
    """Compute signal sets from recent insider transactions.

    Signals:
      - top_buys: largest open-market purchases by value
      - top_sells: largest open-market sales by value
      - ceo_buying: transactions by CEOs/CXOs
      - large_buys: single-ticker buys > $1M
      - frequent_traders: insiders with most transactions
    """
    with get_db_readonly() as c:
        # Top purchases (open market, direct ownership)
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
              AND t.direct_indirect_ownership = 'Direct'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # Top sales
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
              AND t.direct_indirect_ownership = 'Direct'
            ORDER BY t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # CEO/CXO transactions (officers)
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
              AND (o.rptowner_relationship = 'OFFICER')
              AND t.trans_code IN ('P', 'S', 'M', 'A', 'X', 'O')
              AND t.transaction_value_usd IS NOT NULL
              AND t.transaction_value_usd > 0
            ORDER BY s.filing_date DESC, t.transaction_value_usd DESC
            LIMIT ?
        """, (limit,)).fetchall()

        latest_filing = c.execute(
            "SELECT MAX(filing_date) FROM insider_submissions WHERE document_type IN ('4','4/A')"
        ).fetchone()[0]

        return {
            "latest_filing_date": latest_filing,
            "top_buys": _row_dicts(buys),
            "top_sells": _row_dicts(sells),
            "officer_trades": _row_dicts(officers),
        }

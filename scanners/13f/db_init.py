"""
Database schema and initialization for 13F Scanner.
Creates SQLite database with all tables, indexes, and seeds funds table.
"""
import sqlite3
import json
from pathlib import Path
from datetime import date


SCHEMA_SQL = """
-- funds: tracked institutional managers
CREATE TABLE IF NOT EXISTS funds (
    cik TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    strategy TEXT,                    -- 'value_concentrated', 'multi_strat_quant', etc.
    aum_estimate BIGINT,              -- rough AUM in USD for weighting
    is_active BOOLEAN DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- filings_13f: each 13F submission (unified schema)
CREATE TABLE IF NOT EXISTS filings_13f (
    accession_number TEXT PRIMARY KEY,
    fund_cik TEXT NOT NULL REFERENCES funds(cik),
    report_period DATE NOT NULL,      -- quarter end (e.g., 2025-09-30)
    filing_date DATE NOT NULL,        -- when filed with SEC
    submission_type TEXT NOT NULL,    -- '13F-HR', '13F-HR/A', '13F-NT', '13F-NT/A'
    total_value_usd BIGINT,           -- sum of holdings (USD, not thousands)
    total_holdings INT,               -- count of positions
    is_amendment BOOLEAN DEFAULT 0,
    has_infotable BOOLEAN DEFAULT 1,
    raw_filing_json TEXT,             -- store raw edgartools output for debugging
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fund_cik, report_period, submission_type)
);

-- holdings_13f: normalized positions (one row per fund+security+filing) (unified schema)
CREATE TABLE IF NOT EXISTS holdings_13f (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_accession TEXT NOT NULL REFERENCES filings_13f(accession_number),
    fund_cik TEXT NOT NULL REFERENCES funds(cik),
    report_period DATE NOT NULL,
    cusip TEXT NOT NULL,
    ticker TEXT,
    issuer_name TEXT,
    title_of_class TEXT,
    put_call TEXT DEFAULT '',         -- '', 'PUT', 'CALL'
    shares BIGINT NOT NULL,
    share_type TEXT,                  -- 'SH' or 'PRN'
    market_value_usd BIGINT NOT NULL, -- actual USD (SEC reports in thousands)
    voting_sole BIGINT DEFAULT 0,
    voting_shared BIGINT DEFAULT 0,
    voting_none BIGINT DEFAULT 0,
    investment_discretion TEXT,       -- 'SOLE', 'DFND', 'OTR'
    other_manager_cik TEXT,           -- for multi-manager filings
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(filing_accession, cusip, other_manager_cik)
);

-- holding_changes_13f: pre-computed QoQ diffs (materialized for fast queries) (unified schema)
CREATE TABLE IF NOT EXISTS holding_changes_13f (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_cik TEXT NOT NULL REFERENCES funds(cik),
    cusip TEXT NOT NULL,
    ticker TEXT,
    issuer_name TEXT,
    prev_report_period DATE,          -- NULL = NEW position
    curr_report_period DATE NOT NULL,
    prev_shares BIGINT DEFAULT 0,
    curr_shares BIGINT NOT NULL,
    share_change BIGINT GENERATED ALWAYS AS (curr_shares - prev_shares) STORED,
    share_change_pct REAL GENERATED ALWAYS AS (
        CASE WHEN prev_shares = 0 THEN NULL
             ELSE (curr_shares - prev_shares) * 100.0 / prev_shares END
    ) STORED,
    prev_value_usd BIGINT DEFAULT 0,
    curr_value_usd BIGINT NOT NULL,
    value_change_usd BIGINT GENERATED ALWAYS AS (curr_value_usd - prev_value_usd) STORED,
    value_change_pct REAL GENERATED ALWAYS AS (
        CASE WHEN prev_value_usd = 0 THEN NULL
             ELSE (curr_value_usd - prev_value_usd) * 100.0 / prev_value_usd END
    ) STORED,
    status TEXT NOT NULL,             -- 'NEW', 'CLOSED', 'INCREASED', 'DECREASED', 'UNCHANGED'
    put_call TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fund_cik, cusip, curr_report_period)
);

-- alerts: user subscriptions for notifications
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,            -- Discord user ID
    fund_cik TEXT,                    -- NULL = all funds
    ticker TEXT,                      -- NULL = all tickers
    change_types TEXT,                -- comma-separated: 'NEW,INCREASED,CLOSED,DECREASED'
    min_value_change_usd BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- export_log: track generated Excel files
CREATE TABLE IF NOT EXISTS export_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    export_type TEXT NOT NULL,        -- 'fund_holdings', 'fund_changes', 'consensus', 'quarterly_package'
    fund_cik TEXT,
    report_period DATE,
    file_path TEXT,
    file_size_bytes BIGINT,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_filings_13f_fund_period ON filings_13f(fund_cik, report_period);
CREATE INDEX IF NOT EXISTS idx_filings_13f_period ON filings_13f(report_period);
CREATE INDEX IF NOT EXISTS idx_holdings_13f_fund_period ON holdings_13f(fund_cik, report_period);
CREATE INDEX IF NOT EXISTS idx_holdings_13f_cusip_period ON holdings_13f(cusip, report_period);
CREATE INDEX IF NOT EXISTS idx_holdings_13f_ticker_period ON holdings_13f(ticker, report_period);
CREATE INDEX IF NOT EXISTS idx_changes_13f_curr_period ON holding_changes_13f(curr_report_period);
CREATE INDEX IF NOT EXISTS idx_changes_13f_status ON holding_changes_13f(status);
CREATE INDEX IF NOT EXISTS idx_changes_13f_ticker ON holding_changes_13f(ticker);
CREATE INDEX IF NOT EXISTS idx_changes_13f_fund_period ON holding_changes_13f(fund_cik, curr_report_period);
CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id, is_active);
"""


def init_database(db_path: str, seed_file: str = None) -> sqlite3.Connection:
    """Initialize database with schema and optional seed data."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    
    if seed_file and Path(seed_file).exists():
        seed_funds(conn, seed_file)
    
    return conn


def seed_funds(conn: sqlite3.Connection, seed_file: str):
    """Load funds from JSON seed file."""
    with open(seed_file) as f:
        data = json.load(f)
    # Support both {"funds": [...]} and [...] formats
    funds = data["funds"] if isinstance(data, dict) and "funds" in data else data
    
    cursor = conn.cursor()
    for fund in funds:
        cursor.execute("""
            INSERT OR REPLACE INTO funds (cik, name, strategy, aum_estimate, is_active, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            fund["cik"],
            fund["name"],
            fund["strategy"],
            fund["aum_estimate"],
            1 if fund.get("priority", 1) <= 2 else 0,
            fund.get("notes", "")
        ))
    conn.commit()
    print(f"Seeded {len(funds)} funds")


def get_tracked_funds(conn: sqlite3.Connection, active_only: bool = True) -> list:
    """Get list of tracked fund CIKs."""
    query = "SELECT cik, name, strategy FROM funds"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY aum_estimate DESC"
    return conn.execute(query).fetchall()


def get_latest_filing_periods(conn: sqlite3.Connection, limit: int = 8) -> list:
    """Get most recent quarter end dates that have filings."""
    return conn.execute("""
        SELECT DISTINCT report_period 
        FROM filings 
        WHERE has_infotable = 1
        ORDER BY report_period DESC 
        LIMIT ?
    """, (limit,)).fetchall()


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "C:/Users/cho_i/purrtfolio.db"
    seed_path = sys.argv[2] if len(sys.argv) > 2 else "funds_seed.json"
    
    conn = init_database(db_path, seed_path)
    print(f"Database initialized at {db_path}")
    print(f"Tracked funds: {len(get_tracked_funds(conn))}")
    conn.close()
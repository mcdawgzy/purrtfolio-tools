"""
QoQ Comparison Engine - computes holding changes between quarters.
Populates the holding_changes table for fast trend queries.
"""
import sqlite3
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent))


class ChangeComparator:
    """Compute quarter-over-quarter holding changes for tracked funds."""
    
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
    
    def get_available_quarters(self, fund_cik: str = None) -> List[date]:
        """Get all quarter end dates that have filings, optionally filtered by fund."""
        query = """
            SELECT DISTINCT report_period FROM filings_13f 
            WHERE has_infotable = 1
        """
        params = []
        if fund_cik:
            query += " AND fund_cik = ?"
            params.append(fund_cik)
        query += " ORDER BY report_period"
        
        rows = self.conn.execute(query, params).fetchall()
        return [date.fromisoformat(r['report_period']) for r in rows]
    
    def get_previous_quarter(self, report_period: date) -> date:
        """Calculate the previous calendar quarter end date."""
        month = report_period.month
        year = report_period.year
        if month <= 3:
            return date(year - 1, 12, 31)
        elif month <= 6:
            return date(year, 3, 31)
        elif month <= 9:
            return date(year, 6, 30)
        else:
            return date(year, 9, 30)
    
    def compute_changes_for_fund(self, fund_cik: str, curr_period: date, 
                                  prev_period: date = None) -> dict:
        """
        Compare holdings for a single fund between two quarters.
        If prev_period not provided, auto-detect previous quarter.
        """
        if prev_period is None:
            prev_period = self.get_previous_quarter(curr_period)
        
        # Verify both quarters exist for this fund
        curr_exists = self.conn.execute("""
            SELECT 1 FROM filings_13f WHERE fund_cik = ? AND report_period = ? AND has_infotable = 1
        """, (fund_cik, curr_period)).fetchone()
        
        prev_exists = self.conn.execute("""
            SELECT 1 FROM filings_13f WHERE fund_cik = ? AND report_period = ? AND has_infotable = 1
        """, (fund_cik, prev_period)).fetchone()
        
        if not curr_exists:
            return {"status": "error", "message": f"No filing for {fund_cik} in {curr_period}"}
        
        # Get current quarter holdings
        curr_holdings = self.conn.execute("""
            SELECT cusip, ticker, issuer_name, shares, market_value_usd, put_call
            FROM holdings_13f 
            WHERE fund_cik = ? AND report_period = ? AND put_call = ''
        """, (fund_cik, curr_period)).fetchall()
        
        # Get previous quarter holdings
        prev_holdings = self.conn.execute("""
            SELECT cusip, ticker, issuer_name, shares, market_value_usd, put_call
            FROM holdings_13f 
            WHERE fund_cik = ? AND report_period = ? AND put_call = ''
        """, (fund_cik, prev_period)).fetchall()
        
        # Convert to dict keyed by CUSIP
        curr_map = {h['cusip']: h for h in curr_holdings}
        prev_map = {h['cusip']: h for h in prev_holdings}
        
        all_cusips = set(curr_map.keys()) | set(prev_map.keys())
        
        changes = []
        for cusip in all_cusips:
            curr = curr_map.get(cusip)
            prev = prev_map.get(cusip)
            
            if curr and not prev:
                status = "NEW"
                prev_shares = 0
                prev_value = 0
                curr_shares = curr['shares']
                curr_value = curr['market_value_usd']
            elif prev and not curr:
                status = "CLOSED"
                prev_shares = prev['shares']
                prev_value = prev['market_value_usd']
                curr_shares = 0
                curr_value = 0
            elif curr['shares'] > prev['shares']:
                status = "INCREASED"
                prev_shares = prev['shares']
                prev_value = prev['market_value_usd']
                curr_shares = curr['shares']
                curr_value = curr['market_value_usd']
            elif curr['shares'] < prev['shares']:
                status = "DECREASED"
                prev_shares = prev['shares']
                prev_value = prev['market_value_usd']
                curr_shares = curr['shares']
                curr_value = curr['market_value_usd']
            else:
                status = "UNCHANGED"
                prev_shares = prev['shares']
                prev_value = prev['market_value_usd']
                curr_shares = curr['shares']
                curr_value = curr['market_value_usd']
            
            share_change = curr_shares - prev_shares
            share_change_pct = None
            if prev_shares != 0:
                share_change_pct = round((share_change / prev_shares) * 100, 2)
            
            value_change = curr_value - prev_value
            value_change_pct = None
            if prev_value != 0:
                value_change_pct = round((value_change / prev_value) * 100, 2)
            
            changes.append({
                "fund_cik": fund_cik,
                "cusip": cusip,
                "ticker": curr['ticker'] if curr else prev['ticker'],
                "issuer_name": curr['issuer_name'] if curr else prev['issuer_name'],
                "prev_report_period": prev_period if prev else None,
                "curr_report_period": curr_period,
                "prev_shares": prev_shares,
                "curr_shares": curr_shares,
                "share_change": share_change,
                "share_change_pct": share_change_pct,
                "prev_value_usd": prev_value,
                "curr_value_usd": curr_value,
                "value_change_usd": value_change,
                "value_change_pct": value_change_pct,
                "status": status,
                "put_call": curr['put_call'] if curr else prev['put_call']
            })
        
        # Insert into holding_changes_13f table
        inserted = 0
        for chg in changes:
            try:
                self.conn.execute("""
                    INSERT OR REPLACE INTO holding_changes_13f 
                    (fund_cik, cusip, ticker, issuer_name, prev_report_period, curr_report_period,
                     prev_shares, curr_shares,
                     prev_value_usd, curr_value_usd,
                     status, put_call)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chg["fund_cik"], chg["cusip"], chg["ticker"], chg["issuer_name"],
                    chg["prev_report_period"], chg["curr_report_period"],
                    chg["prev_shares"], chg["curr_shares"],
                    chg["prev_value_usd"], chg["curr_value_usd"],
                    chg["status"], chg["put_call"]
                ))
                inserted += 1
            except sqlite3.IntegrityError as e:
                # Real duplicate (UNIQUE collision) is expected on rerun.
                # Foreign key errors are NOT expected and indicate a missing
                # parent row — surface them so they don't silently corrupt data.
                msg = str(e).lower()
                if "foreign key" in msg or "references" in msg:
                    self.conn.rollback()
                    raise RuntimeError(
                        f"FK error writing holding_changes row "
                        f"(fund={chg['fund_cik']} cusip={chg['cusip']} "
                        f"ticker={chg['ticker']!r}): {e}"
                    ) from e
                # Otherwise: duplicate, silently skip (expected on rerun)
        
        self.conn.commit()
        
        # Summary stats
        status_counts = {}
        for chg in changes:
            status_counts[chg["status"]] = status_counts.get(chg["status"], 0) + 1
        
        return {
            "fund_cik": fund_cik,
            "curr_period": str(curr_period),
            "prev_period": str(prev_period),
            "total_compared": len(changes),
            "inserted": inserted,
            "status_breakdown": status_counts,
            "new_positions": [c for c in changes if c["status"] == "NEW"],
            "closed_positions": [c for c in changes if c["status"] == "CLOSED"],
            "top_increases": sorted([c for c in changes if c["status"] == "INCREASED"], 
                                   key=lambda x: x["value_change_usd"] or 0, reverse=True)[:10],
            "top_decreases": sorted([c for c in changes if c["status"] == "DECREASED"], 
                                   key=lambda x: x["value_change_usd"] or 0)[:10]
        }
    
    def compute_changes_all_funds(self, curr_period: date, prev_period: date = None) -> dict:
        """Compute changes for ALL funds that filed in both quarters."""
        if prev_period is None:
            prev_period = self.get_previous_quarter(curr_period)
        
        # Get funds that have filings in BOTH quarters
        funds = self.conn.execute("""
            SELECT DISTINCT f.cik, f.name
            FROM funds f
            JOIN filings_13f f1 ON f.cik = f1.fund_cik AND f1.report_period = ? AND f1.has_infotable = 1
            JOIN filings_13f f2 ON f.cik = f2.fund_cik AND f2.report_period = ? AND f2.has_infotable = 1
            WHERE f.is_active = 1
            ORDER BY f.aum_estimate DESC
        """, (curr_period, prev_period)).fetchall()
        
        summary = {
            "curr_period": str(curr_period),
            "prev_period": str(prev_period),
            "funds_compared": 0,
            "total_changes": 0,
            "aggregate_status": {},
            "fund_results": [],
            "errors": []
        }
        
        aggregate = {"NEW": 0, "CLOSED": 0, "INCREASED": 0, "DECREASED": 0, "UNCHANGED": 0}
        
        for fund in funds:
            try:
                result = self.compute_changes_for_fund(fund['cik'], curr_period, prev_period)
                if result.get("status") != "error":
                    summary["funds_compared"] += 1
                    summary["total_changes"] += result["total_compared"]
                    for status, count in result["status_breakdown"].items():
                        aggregate[status] = aggregate.get(status, 0) + count
                    summary["fund_results"].append({
                        "cik": fund['cik'],
                        "name": fund['name'],
                        "changes": result["total_compared"],
                        "breakdown": result["status_breakdown"]
                    })
                else:
                    summary["errors"].append(f"{fund['cik']}: {result['message']}")
            except Exception as e:
                summary["errors"].append(f"{fund['cik']}: {str(e)}")
        
        summary["aggregate_status"] = aggregate
        return summary
    
    def compute_historical_changes(self, max_quarters: int = 8) -> dict:
        """Compute changes for all available quarter pairs (backfill)."""
        quarters = self.get_available_quarters()
        quarters = sorted(quarters, reverse=True)[:max_quarters]
        
        if len(quarters) < 2:
            return {"status": "error", "message": "Need at least 2 quarters of data"}
        
        results = []
        for i in range(len(quarters) - 1):
            curr = quarters[i]
            prev = quarters[i + 1]
            print(f"Computing changes: {prev} -> {curr}")
            result = self.compute_changes_all_funds(curr, prev)
            results.append(result)
        
        return {"quarters_processed": len(results), "results": results}
    
    def get_fund_summary(self, fund_cik: str, curr_period: date) -> dict:
        """Get a summary of changes for a fund in a given quarter."""
        changes = self.conn.execute("""
            SELECT status, COUNT(*) as count,
                   SUM(ABS(value_change_usd)) as total_value_impact
            FROM holding_changes_13f
            WHERE fund_cik = ? AND curr_report_period = ?
            GROUP BY status
        """, (fund_cik, curr_period)).fetchall()
        
        return {row['status']: {"count": row['count'], "value_impact": row['total_value_impact']} 
                for row in changes}
    
    def close(self):
        self.conn.close()


def run_comparison(db_path: str, quarter: str = None, fund: str = None, backfill: bool = False):
    """Main entry point for comparison."""
    comparator = ChangeComparator(db_path)
    
    if backfill:
        print("Running historical backfill...")
        result = comparator.compute_historical_changes()
        print(json.dumps(result, indent=2, default=str))
    elif quarter:
        curr = date.fromisoformat(quarter)
        if fund:
            print(f"Computing changes for {fund} in {quarter}...")
            result = comparator.compute_changes_for_fund(fund, curr)
        else:
            print(f"Computing changes for all funds in {quarter}...")
            result = comparator.compute_changes_all_funds(curr)
        print(json.dumps(result, indent=2, default=str))
    else:
        # Default: latest quarter
        quarters = comparator.get_available_quarters()
        if quarters:
            latest = quarters[-1]
            print(f"Computing changes for latest quarter: {latest}")
            result = comparator.compute_changes_all_funds(latest)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("No filings found in database")
    
    comparator.close()


if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Compute QoQ 13F holding changes")
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db", help="SQLite database path")
    parser.add_argument("--quarter", help="Quarter end date YYYY-MM-DD (default: latest)")
    parser.add_argument("--fund", help="Single fund CIK (optional)")
    parser.add_argument("--backfill", action="store_true", help="Compute all historical quarter pairs")
    args = parser.parse_args()
    
    run_comparison(args.db, args.quarter, args.fund, args.backfill)
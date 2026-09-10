"""
13F Ingestion Pipeline using edgartools.
Fetches, parses, and stores 13F-HR filings for tracked funds.
"""
import sqlite3
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent))

from edgar import Company, set_identity, get_filings, Filing


class EdgartoolsIngestor:
    """Ingest 13F filings using edgartools (free, no API key)."""
    
    def __init__(self, db_path: str, identity_email: str = "13f-scanner@example.com"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        set_identity(identity_email)
    
    def ingest_fund_latest(self, fund_cik: str, max_filings: int = 4) -> Dict[str, Any]:
        """
        Ingest latest 13F-HR filings for a single fund.
        Returns summary of what was processed.
        """
        try:
            company = Company(fund_cik)
            filings = company.get_filings(form="13F-HR")
            
            if not filings:
                return {"fund_cik": fund_cik, "status": "no_filings", "count": 0}
            
            results = {
                "fund_cik": fund_cik,
                "fund_name": company.name,
                "processed": 0,
                "skipped": 0,
                "errors": []
            }
            
            for filing in filings[:max_filings]:
                try:
                    result = self._process_filing(filing, fund_cik, company.name)
                    if result == "inserted":
                        results["processed"] += 1
                    elif result == "skipped":
                        results["skipped"] += 1
                except Exception as e:
                    results["errors"].append(str(e))
            
            return results
            
        except Exception as e:
            return {"fund_cik": fund_cik, "status": "error", "error": str(e)}
    
    def _process_filing(self, filing: Filing, fund_cik: str, fund_name: str) -> str:
        """Process a single filing: parse, check exists, store."""
        accession = filing.accession_number
        
        # Check if already processed
        existing = self.conn.execute(
            "SELECT 1 FROM filings_13f WHERE accession_number = ?", (accession,)
        ).fetchone()
        if existing:
            return "skipped"
        
        # Parse the filing
        report = filing.obj()
        
        # Skip if no info table (13F-NT)
        if not report.has_infotable():
            self._store_filing_record(
                accession, fund_cik, fund_name, filing.filing_date,
                report.report_period, filing.form, 0, 0, True, False, "{}"
            )
            return "skipped"
        
        # Get holdings DataFrame (aggregated across managers)
        holdings_df = report.holdings.copy()
        
        # Store filing record
        # edgartools returns 'Value' already in actual USD (not thousands),
        # so we store as-is. (Previously multiplied by 1000, which inflated all
        # values 1000x. Fixed 2026-09-05.)
        total_value = int(holdings_df['Value'].sum())
        total_holdings = len(holdings_df)
        
        self._store_filing_record(
            accession, fund_cik, fund_name, filing.filing_date,
            report.report_period, filing.form, total_value, total_holdings,
            filing.form.endswith('/A'), True, json.dumps(report.__dict__, default=str)
        )
        
        # Store each holding
        for _, row in holdings_df.iterrows():
            self._store_holding(accession, fund_cik, report.report_period, row)
        
        return "inserted"
    
    def _store_filing_record(self, accession: str, fund_cik: str, fund_name: str,
                             filing_date: date, report_period: date, form: str,
                             total_value: int, total_holdings: int,
                             is_amendment: bool, has_infotable: bool, raw_json: str):
        """Insert filing metadata."""
        self.conn.execute("""
            INSERT INTO filings_13f 
            (accession_number, fund_cik, report_period, filing_date, submission_type,
             total_value_usd, total_holdings, is_amendment, has_infotable, raw_filing_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            accession, fund_cik, report_period, filing_date, form,
            total_value, total_holdings, is_amendment, has_infotable, raw_json
        ))
        self.conn.commit()
    
    def _store_holding(self, accession: str, fund_cik: str, report_period: date, row: Any):
        """Insert a single holding row."""
        # Handle potential NaN/None values
        ticker = row.get('Ticker', '') or ''
        if isinstance(ticker, float):  # NaN
            ticker = ''
        
        put_call = row.get('PutCall', '') or ''
        if isinstance(put_call, float):
            put_call = ''
        
        share_type = row.get('Type', '') or ''
        if isinstance(share_type, float):
            share_type = ''
        
        self.conn.execute("""
            INSERT INTO holdings_13f 
            (filing_accession, fund_cik, report_period, cusip, ticker, issuer_name,
             title_of_class, put_call, shares, share_type, market_value_usd,
             voting_sole, voting_shared, voting_none, investment_discretion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            accession,
            fund_cik,
            report_period,
            row['Cusip'],
            ticker,
            row['Issuer'],
            row.get('TitleOfClass', ''),
            put_call,
            int(row['SharesPrnAmount']),
            share_type,
            int(row['Value']),  # edgartools returns Value in actual USD; stored as-is
            int(row.get('VotingSole', 0) or 0),
            int(row.get('VotingShared', 0) or 0),
            int(row.get('VotingNone', 0) or 0),
            row.get('InvestmentDiscretion', '')
        ))
        self.conn.commit()
    
    def ingest_all_tracked_funds(self, max_filings_per_fund: int = 4) -> Dict[str, Any]:
        """Ingest latest filings for all tracked funds."""
        funds = self.conn.execute(
            "SELECT cik, name FROM funds WHERE is_active = 1 ORDER BY aum_estimate DESC"
        ).fetchall()
        
        summary = {
            "total_funds": len(funds),
            "processed_funds": 0,
            "total_filings": 0,
            "total_holdings": 0,
            "fund_results": [],
            "errors": []
        }
        
        for fund in funds:
            result = self.ingest_fund_latest(fund['cik'], max_filings_per_fund)
            summary["fund_results"].append(result)
            
            if result.get("processed", 0) > 0:
                summary["processed_funds"] += 1
                summary["total_filings"] += result["processed"]
                # Count holdings from DB
                holdings_count = self.conn.execute("""
                    SELECT COUNT(*) FROM holdings_13f WHERE fund_cik = ?
                """, (fund['cik'],)).fetchone()[0]
                summary["total_holdings"] += holdings_count
            
            if result.get("errors"):
                summary["errors"].extend([f"{fund['cik']}: {e}" for e in result["errors"]])
            
            # Progress
            print(f"  {fund['name']} ({fund['cik']}): {result.get('processed', 0)} new filings")
        
        return summary
    
    def ingest_by_quarter(self, report_period: date, fund_ciks: List[str] = None) -> Dict[str, Any]:
        """
        Ingest all 13F-HR filings for a specific quarter across funds.
        More efficient for quarterly batch runs.
        """
        if fund_ciks is None:
            fund_ciks = [row['cik'] for row in self.conn.execute(
                "SELECT cik FROM funds WHERE is_active = 1"
            ).fetchall()]
        
        summary = {
            "report_period": str(report_period),
            "funds_attempted": len(fund_ciks),
            "filings_found": 0,
            "filings_inserted": 0,
            "holdings_inserted": 0,
            "fund_results": []
        }
        
        for cik in fund_ciks:
            try:
                company = Company(cik)
                filings = company.get_filings(form="13F-HR")
                
                # Filter to target quarter
                target_filings = [f for f in filings 
                                if f.obj().report_period == report_period]
                
                for filing in target_filings:
                    summary["filings_found"] += 1
                    result = self._process_filing(filing, cik, company.name)
                    if result == "inserted":
                        summary["filings_inserted"] += 1
                        # Count holdings added
                        report = filing.obj()
                        summary["holdings_inserted"] += len(report.holdings)
                
                summary["fund_results"].append({
                    "cik": cik,
                    "name": company.name,
                    "filings_found": len(target_filings)
                })
                
            except Exception as e:
                summary["fund_results"].append({
                    "cik": cik,
                    "error": str(e)
                })
        
        return summary
    
    def close(self):
        self.conn.close()


def run_ingestion(db_path: str, identity_email: str = None, max_filings: int = 4):
    """Main entry point for ingestion."""
    email = identity_email or "13f-scanner@example.com"
    ingestor = EdgartoolsIngestor(db_path, email)
    
    print("Starting 13F ingestion for all tracked funds...")
    summary = ingestor.ingest_all_tracked_funds(max_filings)
    
    print("\n=== INGESTION SUMMARY ===")
    print(f"Funds tracked: {summary['total_funds']}")
    print(f"Funds with new filings: {summary['processed_funds']}")
    print(f"New filings inserted: {summary['total_filings']}")
    print(f"Total holdings in DB: {summary['total_holdings']}")
    
    if summary["errors"]:
        print(f"\nErrors ({len(summary['errors'])}):")
        for err in summary["errors"][:10]:
            print(f"  - {err}")
    
    ingestor.close()
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest 13F filings via edgartools")
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db", help="SQLite database path")
    parser.add_argument("--email", default="13f-scanner@example.com", help="SEC identity email")
    parser.add_argument("--max-filings", type=int, default=4, help="Max filings per fund")
    parser.add_argument("--fund", help="Single fund CIK to ingest (optional)")
    parser.add_argument("--quarter", help="Specific quarter YYYY-MM-DD (optional)")
    args = parser.parse_args()
    
    ingestor = EdgartoolsIngestor(args.db, args.email)
    
    if args.fund and args.quarter:
        from datetime import date
        result = ingestor.ingest_by_quarter(date.fromisoformat(args.quarter), [args.fund])
        print(json.dumps(result, indent=2, default=str))
    elif args.fund:
        result = ingestor.ingest_fund_latest(args.fund, args.max_filings)
        print(json.dumps(result, indent=2, default=str))
    else:
        run_ingestion(args.db, args.email, args.max_filings)
    
    ingestor.close()
"""
13F Analysis Engine - Canned queries for actionable insights.
Run as: python analyze.py --quarter 2026-06-30 --type consensus
"""
import sqlite3
import argparse
import json
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional
import sys

DB_PATH = Path(r"C:\Users\cho_i\purrtfolio.db")

# Fund groups for strategy-level analysis (names must match funds.name in DB)
FUND_GROUPS = {
    "value_concentrated": [
        "Berkshire Hathaway Inc", "Baupost Group LLC", "Pershing Square Capital Management LP",
        "Greenlight Capital Inc", "Third Point LLC", "Elliott Investment Management LP",
        "ValueAct Holdings LP", "Starboard Value LP"
    ],
    "quant_multi_strat": [
        "Citadel Advisors LLC", "Renaissance Technologies LLC", "D.E. Shaw & Co Inc",
        "Two Sigma Investments LP", "Millennium Management LLC", "Point72 Asset Management LP"
    ],
    "tech_growth": [
        "Tiger Global Management LLC", "Coatue Management LLC", "D1 Capital Partners LP",
        "Altimeter Capital Management LP", "Whale Rock Capital Management LLC", "Atreides Management LP"
    ],
    "activist": [
        "Elliott Investment Management LP", "Third Point LLC", "ValueAct Holdings LP",
        "Starboard Value LP", "Pershing Square Capital Management LP", "Sachem Head Capital Management LP",
        "Greenlight Capital Inc"
    ],
    "macro_all_weather": [
        "Bridgewater Associates LP", "Point72 Asset Management LP", "Greenlight Capital Inc"
    ],
    "index_passive": [
        "BlackRock Fund Advisors", "Vanguard Group Inc", "State Street Corp", "FMR LLC (Fidelity)",
        "JPMorgan Chase & Co"
    ],
    "star_managers": [
        "Berkshire Hathaway Inc", "Baupost Group LLC", "Pershing Square Capital Management LP",
        "Tiger Global Management LLC", "Renaissance Technologies LLC", "Citadel Advisors LLC",
        "Bridgewater Associates LP", "D.E. Shaw & Co Inc", "Two Sigma Investments LP",
        "Elliott Investment Management LP", "Third Point LLC", "Greenlight Capital Inc",
        "Coatue Management LLC", "D1 Capital Partners LP", "Altimeter Capital Management LP"
    ],
    # Subset of star managers that actually have filings in our DB
    "star_managers_active": [
        "Berkshire Hathaway Inc", "Baupost Group LLC", "Pershing Square Capital Management LP",
        "Renaissance Technologies LLC", "Citadel Advisors LLC",
        "Bridgewater Associates LP", "D.E. Shaw & Co Inc", "ValueAct Holdings LP",
        "Whale Rock Capital Management LLC", "Atreides Management LP"
    ]
}

# Passive/index funds to exclude for "smart money" analysis (names must match funds.name in DB)
PASSIVE_FUNDS = {
    "BlackRock Fund Advisors", "Vanguard Group Inc", "State Street Corp", 
    "FMR LLC (Fidelity)", "JPMorgan Chase & Co", "Norges Bank Investment Management", "Temasek Holdings Pte Ltd"
}


class Analyzer:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def _placeholders(self, items: List[str]) -> str:
        return ",".join("?" * len(items))

    def _fund_filter(self, exclude_passive: bool = True, include_only: Optional[List[str]] = None) -> tuple[str, List[str]]:
        """Build WHERE clause for fund filtering."""
        if include_only:
            ph = self._placeholders(include_only)
            return f"AND f.name IN ({ph})", include_only
        if exclude_passive:
            ph = self._placeholders(list(PASSIVE_FUNDS))
            return f"AND f.name NOT IN ({ph})", list(PASSIVE_FUNDS)
        return "", []

    def consensus_buys(self, quarter: str, prev_quarter: str, min_funds: int = 3, 
                       exclude_passive: bool = True, include_only: Optional[List[str]] = None) -> List[Dict]:
        """Positions where multiple funds INCREASED or NEW."""
        fund_where, fund_params = self._fund_filter(exclude_passive, include_only)
        
        q = f"""
        SELECT 
            hc.cusip, hc.ticker, hc.issuer_name,
            COUNT(DISTINCT hc.fund_cik) as num_funds,
            GROUP_CONCAT(DISTINCT f.name || ':' || hc.status) as fund_actions,
            SUM(hc.curr_value_usd) as total_curr_value,
            SUM(hc.prev_value_usd) as total_prev_value,
            SUM(hc.curr_value_usd - hc.prev_value_usd) as net_value_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status IN ('INCREASED', 'NEW')
          {fund_where}
        GROUP BY hc.cusip, hc.ticker, hc.issuer_name
        HAVING COUNT(DISTINCT hc.fund_cik) >= ?
        ORDER BY net_value_change DESC
        """
        params = [quarter, prev_quarter] + fund_params + [min_funds]
        return [dict(row) for row in self.conn.execute(q, params)]

    def consensus_sells(self, quarter: str, prev_quarter: str, min_funds: int = 3,
                        exclude_passive: bool = True, include_only: Optional[List[str]] = None) -> List[Dict]:
        """Positions where multiple funds DECREASED or CLOSED."""
        fund_where, fund_params = self._fund_filter(exclude_passive, include_only)
        
        q = f"""
        SELECT 
            hc.cusip, hc.ticker, hc.issuer_name,
            COUNT(DISTINCT hc.fund_cik) as num_funds,
            GROUP_CONCAT(DISTINCT f.name || ':' || hc.status) as fund_actions,
            SUM(hc.curr_value_usd) as total_curr_value,
            SUM(hc.prev_value_usd) as total_prev_value,
            SUM(hc.curr_value_usd - hc.prev_value_usd) as net_value_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status IN ('DECREASED', 'CLOSED')
          {fund_where}
        GROUP BY hc.cusip, hc.ticker, hc.issuer_name
        HAVING COUNT(DISTINCT hc.fund_cik) >= ?
        ORDER BY net_value_change ASC
        """
        params = [quarter, prev_quarter] + fund_params + [min_funds]
        return [dict(row) for row in self.conn.execute(q, params)]

    def star_new_positions(self, quarter: str, prev_quarter: str, limit: int = 50) -> List[Dict]:
        """NEW positions by star managers."""
        ph = self._placeholders(FUND_GROUPS["star_managers"])
        q = f"""
        SELECT 
            f.name as fund_name,
            hc.ticker, hc.issuer_name,
            hc.curr_shares, hc.curr_value_usd,
            hc.prev_shares, hc.prev_value_usd
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status = 'NEW'
          AND f.name IN ({ph})
        ORDER BY hc.curr_value_usd DESC
        LIMIT ?
        """
        params = [quarter, prev_quarter] + FUND_GROUPS["star_managers"] + [limit]
        return [dict(row) for row in self.conn.execute(q, params)]

    def star_closed_positions(self, quarter: str, prev_quarter: str, limit: int = 50) -> List[Dict]:
        """CLOSED positions by star managers."""
        ph = self._placeholders(FUND_GROUPS["star_managers"])
        q = f"""
        SELECT 
            f.name as fund_name,
            hc.ticker, hc.issuer_name,
            hc.prev_shares, hc.prev_value_usd
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status = 'CLOSED'
          AND f.name IN ({ph})
        ORDER BY hc.prev_value_usd DESC
        LIMIT ?
        """
        params = [quarter, prev_quarter] + FUND_GROUPS["star_managers"] + [limit]
        return [dict(row) for row in self.conn.execute(q, params)]

    def star_biggest_increases(self, quarter: str, prev_quarter: str, limit: int = 50) -> List[Dict]:
        """Largest $ increases by star managers."""
        ph = self._placeholders(FUND_GROUPS["star_managers"])
        q = f"""
        SELECT 
            f.name as fund_name,
            hc.ticker, hc.issuer_name,
            hc.curr_shares, hc.curr_value_usd,
            hc.prev_shares, hc.prev_value_usd,
            (hc.curr_value_usd - hc.prev_value_usd) as value_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status = 'INCREASED'
          AND f.name IN ({ph})
        ORDER BY value_change DESC
        LIMIT ?
        """
        params = [quarter, prev_quarter] + FUND_GROUPS["star_managers"] + [limit]
        return [dict(row) for row in self.conn.execute(q, params)]

    def star_biggest_decreases(self, quarter: str, prev_quarter: str, limit: int = 50) -> List[Dict]:
        """Largest $ decreases by star managers."""
        ph = self._placeholders(FUND_GROUPS["star_managers"])
        q = f"""
        SELECT 
            f.name as fund_name,
            hc.ticker, hc.issuer_name,
            hc.curr_shares, hc.curr_value_usd,
            hc.prev_shares, hc.prev_value_usd,
            (hc.curr_value_usd - hc.prev_value_usd) as value_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ?
          AND hc.prev_report_period = ?
          AND hc.status = 'DECREASED'
          AND f.name IN ({ph})
        ORDER BY value_change ASC
        LIMIT ?
        """
        params = [quarter, prev_quarter] + FUND_GROUPS["star_managers"] + [limit]
        return [dict(row) for row in self.conn.execute(q, params)]

    def strategy_divergence(self, quarter: str, prev_quarter: str, 
                           group_a: str, group_b: str, threshold: float = 1e9) -> List[Dict]:
        """Find positions where group_a is net buying and group_b is net selling."""
        funds_a = FUND_GROUPS.get(group_a, [])
        funds_b = FUND_GROUPS.get(group_b, [])
        if not funds_a or not funds_b:
            return []
        
        ph_a = self._placeholders(funds_a)
        ph_b = self._placeholders(funds_b)
        
        q = f"""
        WITH group_a AS (
            SELECT 
                hc.cusip, hc.ticker, hc.issuer_name,
                SUM(hc.curr_value_usd - hc.prev_value_usd) as net_change
            FROM holding_changes hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ?
              AND hc.prev_report_period = ?
              AND f.name IN ({ph_a})
            GROUP BY hc.cusip, hc.ticker, hc.issuer_name
        ),
        group_b AS (
            SELECT 
                hc.cusip, hc.ticker, hc.issuer_name,
                SUM(hc.curr_value_usd - hc.prev_value_usd) as net_change
            FROM holding_changes hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ?
              AND hc.prev_report_period = ?
              AND f.name IN ({ph_b})
            GROUP BY hc.cusip, hc.ticker, hc.issuer_name
        )
        SELECT 
            a.ticker, a.issuer_name,
            a.net_change as group_a_net,
            b.net_change as group_b_net
        FROM group_a a
        JOIN group_b b ON a.cusip = b.cusip
        WHERE a.net_change > ?  -- group_a buying
          AND b.net_change < ?  -- group_b selling
        ORDER BY a.net_change DESC
        """
        params = [quarter, prev_quarter] + funds_a + [quarter, prev_quarter] + funds_b + [threshold, -threshold]
        return [dict(row) for row in self.conn.execute(q, params)]

    def fund_summary(self, quarter: str, fund_name: str) -> Dict:
        """Summary of a single fund's quarter activity."""
        q = """
        SELECT 
            status, COUNT(*) as count,
            SUM(curr_value_usd) as curr_value,
            SUM(prev_value_usd) as prev_value,
            SUM(curr_value_usd - prev_value_usd) as net_change
        FROM holding_changes hc
        JOIN funds f ON hc.fund_cik = f.cik
        WHERE hc.curr_report_period = ? AND f.name = ?
        GROUP BY status
        """
        rows = self.conn.execute(q, [quarter, fund_name]).fetchall()
        return {row["status"]: dict(row) for row in rows}

    def top_holdings(self, quarter: str, fund_name: str, limit: int = 10) -> List[Dict]:
        """Top holdings for a fund in a quarter."""
        q = """
        SELECT 
            h.ticker, h.issuer_name, h.cusip,
            h.shares, h.market_value_usd,
            h.market_value_usd * 100.0 / SUM(h.market_value_usd) OVER () as pct_portfolio
        FROM holdings h
        JOIN filings fl ON h.filing_accession = fl.accession_number
        JOIN funds f ON fl.fund_cik = f.cik
        WHERE fl.report_period = ? AND f.name = ?
        ORDER BY h.market_value_usd DESC
        LIMIT ?
        """
        return [dict(row) for row in self.conn.execute(q, [quarter, fund_name, limit])]

    def sector_rotation(self, quarter: str, prev_quarter: str) -> List[Dict]:
        """Sector-level net changes (requires GICS mapping - placeholder)."""
        # TODO: Join with GICS sector mapping table
        return []

    def get_available_quarters(self) -> List[str]:
        """List all quarters with data."""
        q = "SELECT DISTINCT report_period FROM filings ORDER BY report_period DESC"
        return [row[0] for row in self.conn.execute(q)]

    def print_results(self, results: List[Dict], title: str, money_fmt: str = "${:.1f}B"):
        """Pretty print results."""
        print(f"\n=== {title} ===")
        if not results:
            print("  (no results)")
            return
        for r in results:
            ticker = r.get('ticker', 'N/A')
            name = r.get('issuer_name', 'N/A')[:45]
            funds = r.get('num_funds', r.get('fund_name', ''))
            net = r.get('net_value_change', r.get('value_change', r.get('group_a_net', 0)))
            actions = r.get('fund_actions', '')
            if isinstance(funds, int):
                fund_str = f"Funds: {funds}"
            else:
                fund_str = f"Fund: {funds}"
            print(f"  {ticker:6} {name:45} | {fund_str} | Net {money_fmt.format(net/1e9)} | {actions}")


def main():
    parser = argparse.ArgumentParser(description="13F Analysis Engine")
    parser.add_argument("--quarter", required=True, help="Current quarter end (YYYY-MM-DD)")
    parser.add_argument("--prev-quarter", help="Previous quarter end (YYYY-MM-DD)")
    parser.add_argument("--type", choices=[
        "consensus-buys", "consensus-sells", "star-new", "star-closed",
        "star-increases", "star-decreases", "divergence", "fund-summary",
        "top-holdings", "all"
    ], default="all", help="Analysis type")
    parser.add_argument("--fund", help="Fund name for fund-specific queries")
    parser.add_argument("--group-a", help="First strategy group for divergence")
    parser.add_argument("--group-b", help="Second strategy group for divergence")
    parser.add_argument("--min-funds", type=int, default=3, help="Min funds for consensus")
    parser.add_argument("--limit", type=int, default=30, help="Result limit")
    parser.add_argument("--include-passive", action="store_true", help="Include passive/index funds")
    parser.add_argument("--group", choices=list(FUND_GROUPS.keys()), help="Use predefined fund group")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    analyzer = Analyzer()
    
    # Get previous quarter if not specified
    quarters = analyzer.get_available_quarters()
    if args.quarter not in quarters:
        print(f"Quarter {args.quarter} not found. Available: {quarters}")
        return 1
    
    prev_quarter = args.prev_quarter
    if not prev_quarter:
        idx = quarters.index(args.quarter)
        if idx + 1 < len(quarters):
            prev_quarter = quarters[idx + 1]
        else:
            print("No previous quarter available")
            return 1

    include_only = FUND_GROUPS.get(args.group) if args.group else None

    def output(data, title):
        if args.json:
            print(json.dumps({title: data}, indent=2, default=str))
        else:
            analyzer.print_results(data, title)

    if args.type in ("consensus-buys", "all"):
        output(analyzer.consensus_buys(args.quarter, prev_quarter, args.min_funds, 
                                       not args.include_passive, include_only), 
               f"CONSENSUS BUYS ({prev_quarter} -> {args.quarter})")

    if args.type in ("consensus-sells", "all"):
        output(analyzer.consensus_sells(args.quarter, prev_quarter, args.min_funds,
                                        not args.include_passive, include_only),
               f"CONSENSUS SELLS ({prev_quarter} -> {args.quarter})")

    if args.type in ("star-new", "all"):
        output(analyzer.star_new_positions(args.quarter, prev_quarter, args.limit),
               f"STAR MANAGERS NEW POSITIONS")

    if args.type in ("star-closed", "all"):
        output(analyzer.star_closed_positions(args.quarter, prev_quarter, args.limit),
               f"STAR MANAGERS CLOSED POSITIONS")

    if args.type in ("star-increases", "all"):
        output(analyzer.star_biggest_increases(args.quarter, prev_quarter, args.limit),
               f"STAR MANAGERS BIGGEST INCREASES")

    if args.type in ("star-decreases", "all"):
        output(analyzer.star_biggest_decreases(args.quarter, prev_quarter, args.limit),
               f"STAR MANAGERS BIGGEST DECREASES")

    if args.type == "divergence":
        if not args.group_a or not args.group_b:
            print("Divergence requires --group-a and --group-b")
            return 1
        output(analyzer.strategy_divergence(args.quarter, prev_quarter, args.group_a, args.group_b),
               f"DIVERGENCE: {args.group_a} BUYING vs {args.group_b} SELLING")

    if args.type == "fund-summary":
        if not args.fund:
            print("Fund summary requires --fund")
            return 1
        summary = analyzer.fund_summary(args.quarter, args.fund)
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            print(f"\n=== {args.fund} SUMMARY ({args.quarter}) ===")
            for status, data in summary.items():
                print(f"  {status}: {data['count']} positions, Net ${data['net_change']/1e9:.1f}B")

    if args.type == "top-holdings":
        if not args.fund:
            print("Top holdings requires --fund")
            return 1
        holdings = analyzer.top_holdings(args.quarter, args.fund, args.limit)
        if args.json:
            print(json.dumps(holdings, indent=2, default=str))
        else:
            print(f"\n=== TOP {args.limit} HOLDINGS: {args.fund} ({args.quarter}) ===")
            for h in holdings:
                print(f"  {h['ticker']:6} {h['issuer_name'][:40]:40} | ${h['market_value_usd']/1e9:.1f}B ({h['pct_portfolio']:.1f}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
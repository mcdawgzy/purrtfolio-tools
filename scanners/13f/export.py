"""
Excel Export Module - generates analysis-ready Excel workbooks for cross-checking.
Multiple report types: fund holdings, QoQ changes, consensus, master tracker.
"""
import sqlite3
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
import sys
import shutil

sys.path.insert(0, str(Path(__file__).parent))


class ExcelExporter:
    """Generate analysis-ready Excel workbooks for manual cross-checking."""
    
    # Color constants
    HEADER_BG = "2F5496"
    HEADER_FONT = "FFFFFF"
    GREEN_FILL = "C6EFCE"
    RED_FILL = "FFC7CE"
    YELLOW_FILL = "FFEB9C"
    BLUE_FILL = "D6E4F0"
    
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
    
    # ──────────────────────────────────────────────────────────────
    # WORKBOOK 1: Quarterly Holdings Snapshot (per fund)
    # ──────────────────────────────────────────────────────────────
    def export_fund_holdings(self, fund_cik: str, report_period: date, 
                             output_path: str, top_n: int = None) -> str:
        """Single fund, single quarter — formatted for review."""
        fund = self.conn.execute(
            "SELECT name FROM funds WHERE cik = ?", (fund_cik,)
        ).fetchone()
        fund_name = fund['name'] if fund else fund_cik
        
        query = """
            SELECT 
                h.ticker,
                h.issuer_name,
                h.cusip,
                h.title_of_class,
                h.put_call,
                h.shares,
                h.share_type,
                h.market_value_usd,
                h.voting_sole,
                h.voting_shared,
                h.voting_none,
                h.investment_discretion,
                ROUND(h.market_value_usd * 100.0 / SUM(h.market_value_usd) OVER (), 2) AS portfolio_weight_pct
            FROM holdings_13f h
            WHERE h.fund_cik = ? AND h.report_period = ? AND h.put_call = ''
            ORDER BY h.market_value_usd DESC
        """
        df = pd.read_sql(query, self.conn, params=[fund_cik, report_period])
        
        if top_n:
            df = df.head(top_n)
        
        wb = Workbook()
        ws = wb.active
        ws.title = f"{fund_name} {report_period}"[:31]
        
        headers = [
            "Ticker", "Issuer", "CUSIP", "Class", "Put/Call",
            "Shares", "Type", "Market Value ($)", "Portfolio %",
            "Voting Sole", "Voting Shared", "Voting None", "Discretion"
        ]
        
        self._write_header_row(ws, headers, row=1)
        
        for row_idx, row in df.iterrows():
            excel_row = row_idx + 2
            ws.cell(row=excel_row, column=1, value=row['ticker'])
            ws.cell(row=excel_row, column=2, value=row['issuer_name'])
            ws.cell(row=excel_row, column=3, value=row['cusip'])
            ws.cell(row=excel_row, column=4, value=row['title_of_class'])
            ws.cell(row=excel_row, column=5, value=row['put_call'])
            ws.cell(row=excel_row, column=6, value=row['shares']).number_format = '#,##0'
            ws.cell(row=excel_row, column=7, value=row['share_type'])
            ws.cell(row=excel_row, column=8, value=row['market_value_usd']).number_format = '$#,##0'
            ws.cell(row=excel_row, column=9, value=row['portfolio_weight_pct']).number_format = '0.00"%"'
            ws.cell(row=excel_row, column=10, value=row['voting_sole']).number_format = '#,##0'
            ws.cell(row=excel_row, column=11, value=row['voting_shared']).number_format = '#,##0'
            ws.cell(row=excel_row, column=12, value=row['voting_none']).number_format = '#,##0'
            ws.cell(row=excel_row, column=13, value=row['investment_discretion'])
            
            # Right-align numeric columns
            for col in [6, 8, 10, 11, 12]:
                ws.cell(row=excel_row, column=col).alignment = Alignment(horizontal="right")
            ws.cell(row=excel_row, column=9).alignment = Alignment(horizontal="right")
        
        self._add_table_and_autofilter(ws, headers, len(df) + 1, f"Holdings_{fund_cik}_{report_period}")
        self._set_column_widths(ws, [10, 35, 12, 8, 8, 15, 8, 18, 12, 12, 14, 12, 12])
        
        # Summary row
        summary_row = len(df) + 3
        ws.cell(row=summary_row, column=1, value="TOTAL").font = Font(bold=True)
        ws.cell(row=summary_row, column=8, value=df['market_value_usd'].sum()).font = Font(bold=True)
        ws.cell(row=summary_row, column=8).number_format = '$#,##0'
        ws.cell(row=summary_row, column=9, value=100.0).font = Font(bold=True)
        ws.cell(row=summary_row, column=9).number_format = '0.00"%"'
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        self._log_export("fund_holdings", fund_cik, report_period, output_path)
        return output_path
    
    # ──────────────────────────────────────────────────────────────
    # WORKBOOK 2: QoQ Changes (per fund) — 5 tabs
    # ──────────────────────────────────────────────────────────────
    def export_fund_changes(self, fund_cik: str, curr_period: date, 
                            prev_period: date, output_path: str) -> str:
        """Side-by-side comparison with NEW/CLOSED/INCREASED/DECREASED tabs."""
        fund = self.conn.execute(
            "SELECT name FROM funds WHERE cik = ?", (fund_cik,)
        ).fetchone()
        fund_name = fund['name'] if fund else fund_cik
        
        query = """
            SELECT 
                hc.ticker,
                hc.issuer_name,
                hc.cusip,
                hc.status,
                hc.prev_shares,
                hc.curr_shares,
                hc.share_change,
                hc.share_change_pct,
                hc.prev_value_usd,
                hc.curr_value_usd,
                hc.value_change_usd,
                hc.value_change_pct,
                CASE 
                    WHEN hc.prev_shares = 0 THEN 'NEW'
                    WHEN hc.curr_shares = 0 THEN 'EXIT'
                    WHEN hc.share_change > 0 THEN 'ADD'
                    WHEN hc.share_change < 0 THEN 'REDUCE'
                    ELSE 'SAME'
                END AS action
            FROM holding_changes_13f hc
            WHERE hc.fund_cik = ? AND hc.curr_report_period = ?
            ORDER BY 
                CASE hc.status 
                    WHEN 'NEW' THEN 1 
                    WHEN 'CLOSED' THEN 2 
                    WHEN 'INCREASED' THEN 3 
                    WHEN 'DECREASED' THEN 4 
                    ELSE 5 END,
                ABS(hc.value_change_usd) DESC
        """
        df = pd.read_sql(query, self.conn, params=[fund_cik, curr_period])
        
        wb = Workbook()
        
        # Sheet 1: All Changes
        ws1 = wb.active
        ws1.title = "All Changes"
        self._write_changes_sheet(ws1, df, fund_name, curr_period, prev_period, "ALL")
        
        # Sheet 2: New Positions Only
        ws2 = wb.create_sheet("New Positions")
        new_df = df[df['status'] == 'NEW']
        self._write_changes_sheet(ws2, new_df, fund_name, curr_period, prev_period, "NEW")
        
        # Sheet 3: Exits Only
        ws3 = wb.create_sheet("Exits")
        exit_df = df[df['status'] == 'CLOSED']
        self._write_changes_sheet(ws3, exit_df, fund_name, curr_period, prev_period, "CLOSED")
        
        # Sheet 4: Top Increases
        ws4 = wb.create_sheet("Top Increases")
        inc_df = df[df['status'] == 'INCREASED'].head(20)
        self._write_changes_sheet(ws4, inc_df, fund_name, curr_period, prev_period, "INCREASED")
        
        # Sheet 5: Top Decreases
        ws5 = wb.create_sheet("Top Decreases")
        dec_df = df[df['status'] == 'DECREASED'].head(20)
        self._write_changes_sheet(ws5, dec_df, fund_name, curr_period, prev_period, "DECREASED")
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        self._log_export("fund_changes", fund_cik, curr_period, output_path)
        return output_path
    
    def _write_changes_sheet(self, ws, df, fund_name, curr_p, prev_p, filter_label="ALL"):
        """Helper to write a formatted changes sheet."""
        headers = [
            "Ticker", "Issuer", "CUSIP", "Status", "Action",
            "Prev Shares", "Curr Shares", "Share Chg", "Share Chg %",
            "Prev Value ($)", "Curr Value ($)", "Value Chg ($)", "Value Chg %"
        ]
        
        # Title row
        ws.merge_cells('A1:M1')
        title = ws.cell(row=1, column=1, value=f"{fund_name} — {filter_label} Changes: {prev_p} → {curr_p}")
        title.font = Font(bold=True, size=14)
        title.alignment = Alignment(horizontal="center")
        
        # Headers on row 2
        self._write_header_row(ws, headers, row=2)
        
        status_colors = {
            'NEW': self.GREEN_FILL, 'INCREASED': self.GREEN_FILL,
            'CLOSED': self.RED_FILL, 'DECREASED': self.RED_FILL,
            'UNCHANGED': self.YELLOW_FILL
        }
        
        for row_idx, row in df.iterrows():
            excel_row = row_idx + 3
            ws.cell(row=excel_row, column=1, value=row['ticker'])
            ws.cell(row=excel_row, column=2, value=row['issuer_name'])
            ws.cell(row=excel_row, column=3, value=row['cusip'])
            status_cell = ws.cell(row=excel_row, column=4, value=row['status'])
            ws.cell(row=excel_row, column=5, value=row['action'])
            ws.cell(row=excel_row, column=6, value=row['prev_shares']).number_format = '#,##0'
            ws.cell(row=excel_row, column=7, value=row['curr_shares']).number_format = '#,##0'
            ws.cell(row=excel_row, column=8, value=row['share_change']).number_format = '#,##0'
            
            if row['share_change_pct'] is not None:
                ws.cell(row=excel_row, column=9, value=row['share_change_pct'] / 100).number_format = '0.00%'
            
            ws.cell(row=excel_row, column=10, value=row['prev_value_usd']).number_format = '$#,##0'
            ws.cell(row=excel_row, column=11, value=row['curr_value_usd']).number_format = '$#,##0'
            ws.cell(row=excel_row, column=12, value=row['value_change_usd']).number_format = '$#,##0'
            
            if row['value_change_pct'] is not None:
                ws.cell(row=excel_row, column=13, value=row['value_change_pct'] / 100).number_format = '0.00%'
            
            # Color status column
            if row['status'] in status_colors:
                status_cell.fill = PatternFill(
                    start_color=status_colors[row['status']], 
                    end_color=status_colors[row['status']], fill_type="solid")
            
            # Right-align numeric columns
            for col in [6, 7, 8, 10, 11, 12]:
                ws.cell(row=excel_row, column=col).alignment = Alignment(horizontal="right")
            for col in [9, 13]:
                ws.cell(row=excel_row, column=col).alignment = Alignment(horizontal="right")
        
        self._add_table_and_autofilter(ws, headers, len(df) + 2, f"Changes_{filter_label}", start_row=2)
        self._set_column_widths(ws, [10, 35, 12, 12, 8, 14, 14, 12, 12, 16, 16, 14, 12])
    
    # ──────────────────────────────────────────────────────────────
    # WORKBOOK 3: Market-Wide Consensus (cross-fund)
    # ──────────────────────────────────────────────────────────────
    def export_consensus_report(self, report_period: date, output_path: str, 
                                min_funds: int = 2) -> str:
        """What are MULTIPLE funds doing with each ticker?"""
        query = """
            SELECT 
                hc.ticker,
                hc.issuer_name,
                COUNT(*) AS funds_total,
                SUM(CASE WHEN hc.status IN ('NEW','INCREASED') THEN 1 ELSE 0 END) AS funds_adding,
                SUM(CASE WHEN hc.status IN ('CLOSED','DECREASED') THEN 1 ELSE 0 END) AS funds_reducing,
                SUM(CASE WHEN hc.status = 'NEW' THEN 1 ELSE 0 END) AS funds_new,
                SUM(CASE WHEN hc.status = 'CLOSED' THEN 1 ELSE 0 END) AS funds_exited,
                SUM(hc.curr_value_usd) AS total_current_value_usd,
                SUM(hc.value_change_usd) AS net_value_change_usd,
                GROUP_CONCAT(DISTINCT f.name || ':' || hc.status) AS fund_actions
            FROM holding_changes_13f hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ? AND hc.put_call = ''
            GROUP BY hc.ticker, hc.issuer_name
            HAVING funds_total >= ?
            ORDER BY funds_adding DESC, net_value_change_usd DESC
        """
        df = pd.read_sql(query, self.conn, params=[report_period, min_funds])
        
        wb = Workbook()
        ws = wb.active
        ws.title = f"Consensus {report_period}"[:31]
        
        headers = [
            "Ticker", "Issuer", "Funds Tracking", "Funds Adding", "Funds Reducing",
            "New Positions", "Full Exits", "Total Current Value ($)", 
            "Net Value Change ($)", "Fund Actions Detail"
        ]
        
        self._write_header_row(ws, headers, row=1)
        
        for row_idx, row in df.iterrows():
            excel_row = row_idx + 2
            for col_idx, val in enumerate(row, 1):
                cell = ws.cell(row=excel_row, column=col_idx, value=val)
                if col_idx in (8, 9) and isinstance(val, (int, float)):
                    cell.number_format = '$#,##0'
                    cell.alignment = Alignment(horizontal="right")
        
        # Highlight strong consensus rows
        for row_idx in range(2, len(df) + 2):
            adding = ws.cell(row=row_idx, column=4).value or 0
            reducing = ws.cell(row=row_idx, column=5).value or 0
            if adding >= 5:
                for c in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=c).fill = PatternFill(
                        start_color=self.GREEN_FILL, end_color=self.GREEN_FILL, fill_type="solid")
            elif reducing >= 5:
                for c in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=c).fill = PatternFill(
                        start_color=self.RED_FILL, end_color=self.RED_FILL, fill_type="solid")
        
        self._add_table_and_autofilter(ws, headers, len(df) + 1, f"Consensus_{report_period}")
        self._set_column_widths(ws, [10, 35, 14, 14, 14, 14, 12, 22, 20, 60])
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        self._log_export("consensus", None, report_period, output_path)
        return output_path
    
    # ──────────────────────────────────────────────────────────────
    # WORKBOOK 4: Master Tracker (all funds, all quarters)
    # ──────────────────────────────────────────────────────────────
    def export_master_tracker(self, output_path: str, 
                              quarters: List[date] = None) -> str:
        """One sheet per quarter, each with all funds' top 10 holdings."""
        if quarters is None:
            rows = self.conn.execute("""
                SELECT DISTINCT report_period FROM filings_13f 
                WHERE has_infotable = 1 ORDER BY report_period DESC LIMIT 8
            """).fetchall()
            quarters = [date.fromisoformat(r['report_period']) for r in rows]
        
        wb = Workbook()
        
        for q_idx, qtr in enumerate(quarters):
            if q_idx == 0:
                ws = wb.active
            else:
                ws = wb.create_sheet()
            ws.title = str(qtr)[:31]
            
            query = """
                SELECT 
                    f.name AS fund_name,
                    h.ticker,
                    h.issuer_name,
                    h.market_value_usd,
                    ROUND(h.market_value_usd * 100.0 / SUM(h.market_value_usd) OVER (PARTITION BY h.fund_cik), 2) AS weight_pct,
                    ROW_NUMBER() OVER (PARTITION BY h.fund_cik ORDER BY h.market_value_usd DESC) AS rn
                FROM holdings_13f h
                JOIN funds f ON h.fund_cik = f.cik
                WHERE h.report_period = ? AND h.put_call = ''
            """
            df = pd.read_sql(query, self.conn, params=[qtr])
            df = df[df['rn'] <= 10]  # Top 10 per fund
            
            row_ptr = 1
            for fund_name, fund_df in df.groupby('fund_name'):
                # Fund header
                ws.cell(row=row_ptr, column=1, value=fund_name).font = Font(bold=True, size=12)
                row_ptr += 1
                
                # Column headers
                headers = ["Rank", "Ticker", "Issuer", "Market Value ($)", "Portfolio %"]
                self._write_header_row(ws, headers, row=row_ptr)
                row_ptr += 1
                
                for _, row in fund_df.iterrows():
                    ws.cell(row=row_ptr, column=1, value=row['rn'])
                    ws.cell(row=row_ptr, column=2, value=row['ticker'])
                    ws.cell(row=row_ptr, column=3, value=row['issuer_name'])
                    cell_val = ws.cell(row=row_ptr, column=4, value=row['market_value_usd'])
                    cell_val.number_format = '$#,##0'
                    cell_val.alignment = Alignment(horizontal="right")
                    cell_wt = ws.cell(row=row_ptr, column=5, value=row['weight_pct'])
                    cell_wt.number_format = '0.00"%"'
                    cell_wt.alignment = Alignment(horizontal="right")
                    row_ptr += 1
                
                row_ptr += 1  # blank row between funds
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        self._log_export("master_tracker", None, None, output_path)
        return output_path
    
    # ──────────────────────────────────────────────────────────────
    # WORKBOOK 5: Sector/Strategy Analysis (with GICS sectors)
    # ──────────────────────────────────────────────────────────────
    def export_sector_analysis(self, report_period: date, output_path: str) -> str:
        """Aggregate holdings by sector (requires sector mapping table)."""
        wb = Workbook()
        
        # Sheet 1: By GICS Sector (from sector mapping table)
        ws1 = wb.active
        ws1.title = f"By Sector {report_period}"
        
        query_sector = """
            SELECT 
                s.sector,
                COUNT(DISTINCT h.ticker) as unique_tickers,
                COUNT(*) as total_positions,
                SUM(h.market_value_usd) as total_value_usd,
                AVG(h.market_value_usd) as avg_position_size_usd
            FROM holdings_13f h
            JOIN sectors s ON h.ticker = s.ticker
            WHERE h.report_period = ? AND h.put_call = '' AND s.sector IS NOT NULL
            GROUP BY s.sector
            ORDER BY total_value_usd DESC
        """
        df_sector = pd.read_sql(query_sector, self.conn, params=[report_period])
        
        headers_sector = ["GICS Sector", "Unique Tickers", "Positions", "Total Value ($)", "Avg Position ($)"]
        self._write_header_row(ws1, headers_sector, row=1)
        
        for row_idx, row in df_sector.iterrows():
            ws1.cell(row=row_idx+2, column=1, value=row['sector'])
            ws1.cell(row=row_idx+2, column=2, value=row['unique_tickers'])
            ws1.cell(row=row_idx+2, column=3, value=row['total_positions'])
            cell = ws1.cell(row=row_idx+2, column=4, value=row['total_value_usd'])
            cell.number_format = '$#,##0'
            cell.alignment = Alignment(horizontal="right")
            cell = ws1.cell(row=row_idx+2, column=5, value=row['avg_position_size_usd'])
            cell.number_format = '$#,##0'
            cell.alignment = Alignment(horizontal="right")
        
        self._add_table_and_autofilter(ws1, headers_sector, len(df_sector) + 1, f"Sector_{report_period}")
        self._set_column_widths(ws1, [30, 16, 12, 20, 20])
        
        # Sheet 2: By Strategy (existing)
        ws2 = wb.create_sheet(f"By Strategy {report_period}")
        
        query_strat = """
            SELECT 
                f.strategy,
                COUNT(DISTINCT f.cik) as fund_count,
                COUNT(*) as total_positions,
                SUM(h.market_value_usd) as total_value_usd
            FROM holdings h
            JOIN funds f ON h.fund_cik = f.cik
            WHERE h.report_period = ? AND h.put_call = ''
            GROUP BY f.strategy
            ORDER BY total_value_usd DESC
        """
        df_strat = pd.read_sql(query_strat, self.conn, params=[report_period])
        
        headers_strat = ["Strategy", "Funds", "Positions", "Total Value ($)"]
        self._write_header_row(ws2, headers_strat, row=1)
        
        for row_idx, row in df_strat.iterrows():
            ws2.cell(row=row_idx+2, column=1, value=row['strategy'])
            ws2.cell(row=row_idx+2, column=2, value=row['fund_count'])
            ws2.cell(row=row_idx+2, column=3, value=row['total_positions'])
            cell = ws2.cell(row=row_idx+2, column=4, value=row['total_value_usd'])
            cell.number_format = '$#,##0'
            cell.alignment = Alignment(horizontal="right")
        
        self._add_table_and_autofilter(ws2, headers_strat, len(df_strat) + 1, f"Strategy_{report_period}")
        self._set_column_widths(ws2, [25, 10, 12, 20])
        
        # Sheet 3: Sector x Strategy cross-tab (top holdings by sector per strategy)
        ws3 = wb.create_sheet(f"Sector x Strategy {report_period}")
        
        query_cross = """
            SELECT 
                f.strategy,
                s.sector,
                COUNT(DISTINCT h.ticker) as tickers,
                SUM(h.market_value_usd) as total_value_usd
            FROM holdings_13f h
            JOIN funds f ON h.fund_cik = f.cik
            JOIN sectors s ON h.ticker = s.ticker
            WHERE h.report_period = ? AND h.put_call = '' 
              AND s.sector IS NOT NULL
            GROUP BY f.strategy, s.sector
            ORDER BY f.strategy, total_value_usd DESC
        """
        df_cross = pd.read_sql(query_cross, self.conn, params=[report_period])
        
        headers_cross = ["Strategy", "GICS Sector", "Tickers", "Total Value ($)"]
        self._write_header_row(ws3, headers_cross, row=1)
        
        for row_idx, row in df_cross.iterrows():
            ws3.cell(row=row_idx+2, column=1, value=row['strategy'])
            ws3.cell(row=row_idx+2, column=2, value=row['sector'])
            ws3.cell(row=row_idx+2, column=3, value=row['tickers'])
            cell = ws3.cell(row=row_idx+2, column=4, value=row['total_value_usd'])
            cell.number_format = '$#,##0'
            cell.alignment = Alignment(horizontal="right")
        
        self._add_table_and_autofilter(ws3, headers_cross, len(df_cross) + 1, f"SectorStrategy_{report_period}")
        self._set_column_widths(ws3, [22, 30, 10, 20])
        
        # Sheet 4: Top holdings by sector (detailed)
        ws4 = wb.create_sheet(f"Top by Sector {report_period}")
        
        query_top = """
            SELECT 
                s.sector,
                h.ticker,
                h.issuer_name,
                SUM(h.market_value_usd) as total_value_usd,
                COUNT(DISTINCT h.fund_cik) as funds_holding,
                GROUP_CONCAT(DISTINCT f.name) as fund_names
            FROM holdings_13f h
            JOIN funds f ON h.fund_cik = f.cik
            JOIN sectors s ON h.ticker = s.ticker
            WHERE h.report_period = ? AND h.put_call = '' AND s.sector IS NOT NULL
            GROUP BY s.sector, h.ticker, h.issuer_name
            ORDER BY s.sector, total_value_usd DESC
        """
        df_top = pd.read_sql(query_top, self.conn, params=[report_period])
        
        # Limit to top 5 per sector
        df_top_limited = df_top.groupby('sector').head(5).reset_index(drop=True)
        
        headers_top = ["Sector", "Ticker", "Issuer", "Total Value ($)", "Funds Holding", "Fund Names"]
        self._write_header_row(ws4, headers_top, row=1)
        
        for row_idx, row in df_top_limited.iterrows():
            ws4.cell(row=row_idx+2, column=1, value=row['sector'])
            ws4.cell(row=row_idx+2, column=2, value=row['ticker'])
            ws4.cell(row=row_idx+2, column=3, value=row['issuer_name'])
            cell = ws4.cell(row=row_idx+2, column=4, value=row['total_value_usd'])
            cell.number_format = '$#,##0'
            cell.alignment = Alignment(horizontal="right")
            ws4.cell(row=row_idx+2, column=5, value=row['funds_holding'])
            ws4.cell(row=row_idx+2, column=6, value=row['fund_names'])
        
        self._add_table_and_autofilter(ws4, headers_top, len(df_top_limited) + 1, f"TopBySector_{report_period}")
        self._set_column_widths(ws4, [25, 10, 35, 20, 14, 60])
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        self._log_export("sector_analysis", None, report_period, output_path)
        return output_path
    
    # ──────────────────────────────────────────────────────────────
    # Convenience: Generate all reports for a quarter
    # ──────────────────────────────────────────────────────────────
    def generate_quarterly_package(self, report_period: date, output_dir: str) -> Dict[str, str]:
        """One-call generation of all Excel files for a quarter, returns zip path."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {}
        
        # 1. Consensus report (market-wide)
        consensus_path = output_dir / f"consensus_{report_period}.xlsx"
        results['consensus'] = self.export_consensus_report(report_period, str(consensus_path))
        
        # 2. Per-fund changes (for each fund that filed)
        funds = self.conn.execute("""
            SELECT DISTINCT fund_cik FROM filings_13f 
            WHERE report_period = ? AND has_infotable = 1
        """, (report_period,)).fetchall()
        
        prev_period = self._get_previous_quarter(report_period)
        
        for fund_row in funds:
            fund_cik = fund_row['fund_cik']
            try:
                changes_path = output_dir / f"changes_{fund_cik}_{report_period}.xlsx"
                results[f'changes_{fund_cik}'] = self.export_fund_changes(
                    fund_cik, report_period, prev_period, str(changes_path)
                )
            except Exception as e:
                print(f"Failed {fund_cik}: {e}")
        
        # 3. Master tracker (last 8 quarters)
        master_path = output_dir / f"master_tracker_{date.today().isoformat()}.xlsx"
        results['master'] = self.export_master_tracker(str(master_path))
        
        # 4. Sector analysis
        sector_path = output_dir / f"sector_{report_period}.xlsx"
        results['sector'] = self.export_sector_analysis(report_period, str(sector_path))
        
        # Create zip
        zip_path = shutil.make_archive(str(output_dir), 'zip', str(output_dir))
        results['zip'] = zip_path
        
        return results
    
    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────
    def _write_header_row(self, ws, headers: List[str], row: int = 1):
        """Write formatted header row."""
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col_idx, value=header)
            cell.font = Font(bold=True, color=self.HEADER_FONT)
            cell.fill = PatternFill(start_color=self.HEADER_BG, end_color=self.HEADER_BG, fill_type="solid")
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
    
    def _add_table_and_autofilter(self, ws, headers: List[str], last_row: int, 
                                   table_name: str, start_row: int = 1):
        """Add Excel table and auto-filter."""
        last_col = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A{start_row}:{last_col}{last_row}"
        
        table = Table(displayName=table_name.replace("-", "_").replace(".", "_"), 
                      ref=f"A{start_row}:{last_col}{last_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
        ws.add_table(table)
    
    def _set_column_widths(self, ws, widths: List[int]):
        """Set column widths."""
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
    
    def _get_previous_quarter(self, dt: date) -> date:
        """Calculate previous quarter end date."""
        month = dt.month
        year = dt.year
        if month <= 3:
            return date(year - 1, 12, 31)
        elif month <= 6:
            return date(year, 3, 31)
        elif month <= 9:
            return date(year, 6, 30)
        else:
            return date(year, 9, 30)
    
    def _log_export(self, export_type: str, fund_cik: str, report_period: date, file_path: str):
        """Log export to database."""
        try:
            size = Path(file_path).stat().st_size
            self.conn.execute("""
                INSERT INTO export_log (export_type, fund_cik, report_period, file_path, file_size_bytes)
                VALUES (?, ?, ?, ?, ?)
            """, (export_type, fund_cik, report_period, file_path, size))
            self.conn.commit()
        except Exception:
            pass  # Non-critical
    
    def close(self):
        self.conn.close()


def run_export(db_path: str, quarter: str = None, fund: str = None, 
               package: bool = False, output_dir: str = "exports"):
    """Main entry point for exports."""
    exporter = ExcelExporter(db_path)
    
    if package and quarter:
        report_period = date.fromisoformat(quarter)
        print(f"Generating quarterly package for {quarter}...")
        results = exporter.generate_quarterly_package(report_period, output_dir)
        print(f"Generated {len(results)} files")
        print(f"Zip: {results.get('zip')}")
    elif quarter and fund:
        report_period = date.fromisoformat(quarter)
        prev_period = exporter._get_previous_quarter(report_period)
        fund_cik = fund if len(fund) == 10 and fund.isdigit() else None
        
        if not fund_cik:
            # Resolve by name
            row = exporter.conn.execute(
                "SELECT cik FROM funds WHERE name LIKE ? LIMIT 1", (f"%{fund}%",)
            ).fetchone()
            if row:
                fund_cik = row['cik']
        
        if fund_cik:
            path = f"{output_dir}/changes_{fund_cik}_{quarter}.xlsx"
            exporter.export_fund_changes(fund_cik, report_period, prev_period, path)
            print(f"Exported: {path}")
    elif quarter:
        report_period = date.fromisoformat(quarter)
        path = f"{output_dir}/consensus_{quarter}.xlsx"
        exporter.export_consensus_report(report_period, path)
        print(f"Exported: {path}")
    else:
        # Latest quarter consensus
        rows = exporter.conn.execute("""
            SELECT DISTINCT report_period FROM filings_13f 
            WHERE has_infotable = 1 ORDER BY report_period DESC LIMIT 1
        """).fetchall()
        if rows:
            latest = date.fromisoformat(rows[0]['report_period'])
            path = f"{output_dir}/consensus_{latest}.xlsx"
            exporter.export_consensus_report(latest, path)
            print(f"Exported latest consensus: {path}")
    
    exporter.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Export 13F analysis to Excel")
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db", help="SQLite database path")
    parser.add_argument("--quarter", help="Quarter end date YYYY-MM-DD")
    parser.add_argument("--fund", help="Fund name or CIK (for fund-specific exports)")
    parser.add_argument("--package", action="store_true", help="Generate full quarterly package (zip)")
    parser.add_argument("--output-dir", default="exports", help="Output directory")
    args = parser.parse_args()
    
    run_export(args.db, args.quarter, args.fund, args.package, args.output_dir)
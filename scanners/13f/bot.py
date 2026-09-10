"""
Discord Bot Commands for 13F Scanner.
Integrates with Hermes Gateway for slash commands and interactions.
"""
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List
import sys
import os

sys.path.insert(0, str(Path(__file__).parent))

from export import ExcelExporter
from compare import ChangeComparator
from ingest import EdgartoolsIngestor
from db_init import init_database, get_tracked_funds


class ScannerBot(commands.Bot):
    """13F Scanner Discord Bot."""
    
    def __init__(self, db_path: str, **kwargs):
        super().__init__(command_prefix="!", intents=discord.Intents.default(), **kwargs)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.exporter = ExcelExporter(db_path)
        self.comparator = ChangeComparator(db_path)
        self.ingestor = EdgartoolsIngestor(db_path)
    
    async def setup_hook(self):
        """Register slash commands."""
        await self.tree.sync()
        print("Slash commands synced")
    
    async def close(self):
        self.conn.close()
        self.exporter.close()
        self.comparator.close()
        self.ingestor.close()
        await super().close()


def create_bot(db_path: str = "C:/Users/cho_i/purrtfolio.db") -> ScannerBot:
    """Factory function to create bot instance."""
    return ScannerBot(db_path)


# ──────────────────────────────────────────────────────────────
# Slash Command Groups
# ──────────────────────────────────────────────────────────────

class FundCommands(app_commands.Group):
    """Fund-specific queries."""
    
    def __init__(self, bot: ScannerBot):
        super().__init__(name="fund", description="Query specific fund holdings")
        self.bot = bot
    
    @app_commands.command(name="holdings", description="Show fund's top holdings for a quarter")
    @app_commands.describe(fund="Fund name or CIK", quarter="Quarter end YYYY-MM-DD (default: latest)", top="Number of top positions")
    async def holdings(self, interaction: discord.Interaction, fund: str, quarter: str = None, top: int = 20):
        await interaction.response.defer(ephemeral=True)
        
        fund_cik = self._resolve_fund(fund)
        if not fund_cik:
            await interaction.followup.send(f"❌ Fund not found: {fund}")
            return
        
        if quarter:
            report_period = date.fromisoformat(quarter)
        else:
            report_period = self._get_latest_quarter(fund_cik)
            if not report_period:
                await interaction.followup.send(f"❌ No filings found for {fund}")
                return
        
        # Query holdings
        rows = self.bot.conn.execute("""
            SELECT ticker, issuer_name, market_value_usd, shares,
                   ROUND(market_value_usd * 100.0 / SUM(market_value_usd) OVER (), 2) as weight_pct
            FROM holdings
            WHERE fund_cik = ? AND report_period = ? AND put_call = ''
            ORDER BY market_value_usd DESC
            LIMIT ?
        """, (fund_cik, report_period, top)).fetchall()
        
        if not rows:
            await interaction.followup.send(f"❌ No holdings data for {fund} in {report_period}")
            return
        
        # Build embed
        fund_info = self.bot.conn.execute("SELECT name FROM funds WHERE cik = ?", (fund_cik,)).fetchone()
        fund_name = fund_info['name'] if fund_info else fund_cik
        
        embed = discord.Embed(
            title=f"📊 {fund_name} Holdings — {report_period}",
            description=f"Top {len(rows)} positions (long equity only)",
            color=0x2F5496
        )
        
        total_value = sum(r['market_value_usd'] for r in rows)
        
        # Top 10 in embed
        for i, row in enumerate(rows[:10], 1):
            weight = row['weight_pct']
            embed.add_field(
                name=f"{i}. {row['ticker']} — {row['issuer_name'][:40]}",
                value=f"${row['market_value_usd']:,.0f} ({weight:.1f}%) • {row['shares']:,.0f} shares",
                inline=False
            )
        
        embed.set_footer(text=f"Total tracked value: ${total_value:,.0f} • Data: SEC 13F-HR via edgartools")
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="changes", description="Show QoQ changes for a fund")
    @app_commands.describe(fund="Fund name or CIK", quarter="Current quarter end YYYY-MM-DD (default: latest)")
    async def changes(self, interaction: discord.Interaction, fund: str, quarter: str = None):
        await interaction.response.defer(ephemeral=True)
        
        fund_cik = self._resolve_fund(fund)
        if not fund_cik:
            await interaction.followup.send(f"❌ Fund not found: {fund}")
            return
        
        if quarter:
            curr_period = date.fromisoformat(quarter)
        else:
            curr_period = self._get_latest_quarter(fund_cik)
        
        prev_period = self.comparator.get_previous_quarter(curr_period)
        
        # Get change summary
        summary = self.bot.conn.execute("""
            SELECT status, COUNT(*) as cnt, SUM(ABS(value_change_usd)) as impact
            FROM holding_changes
            WHERE fund_cik = ? AND curr_report_period = ?
            GROUP BY status
        """, (fund_cik, curr_period)).fetchall()
        
        if not summary:
            await interaction.followup.send(f"❌ No changes computed for {fund} in {curr_period}. Run `/admin compute-changes` first.")
            return
        
        fund_info = self.bot.conn.execute("SELECT name FROM funds WHERE cik = ?", (fund_cik,)).fetchone()
        fund_name = fund_info['name'] if fund_info else fund_cik
        
        embed = discord.Embed(
            title=f"📈 {fund_name} QoQ Changes — {prev_period} → {curr_period}",
            color=0x2F5496
        )
        
        status_emoji = {"NEW": "🟢", "INCREASED": "🔵", "DECREASED": "🟠", "CLOSED": "🔴", "UNCHANGED": "⚪"}
        
        for row in summary:
            emoji = status_emoji.get(row['status'], "⚪")
            embed.add_field(
                name=f"{emoji} {row['status']}",
                value=f"{row['cnt']} positions • ${row['impact']:,.0f} value impact",
                inline=True
            )
        
        # Add top moves
        top_new = self.bot.conn.execute("""
            SELECT ticker, issuer_name, curr_value_usd
            FROM holding_changes
            WHERE fund_cik = ? AND curr_report_period = ? AND status = 'NEW'
            ORDER BY curr_value_usd DESC LIMIT 3
        """, (fund_cik, curr_period)).fetchall()
        
        if top_new:
            embed.add_field(
                name="🟢 Top New Positions",
                value="\n".join(f"• {r['ticker']} ({r['issuer_name'][:30]}) — ${r['curr_value_usd']:,.0f}" for r in top_new),
                inline=False
            )
        
        top_exits = self.bot.conn.execute("""
            SELECT ticker, issuer_name, prev_value_usd
            FROM holding_changes
            WHERE fund_cik = ? AND curr_report_period = ? AND status = 'CLOSED'
            ORDER BY prev_value_usd DESC LIMIT 3
        """, (fund_cik, curr_period)).fetchall()
        
        if top_exits:
            embed.add_field(
                name="🔴 Top Exits",
                value="\n".join(f"• {r['ticker']} ({r['issuer_name'][:30]}) — was ${r['prev_value_usd']:,.0f}" for r in top_exits),
                inline=False
            )
        
        embed.set_footer(text="Use /export fund-changes for full Excel breakdown")
        await interaction.followup.send(embed=embed)
    
    def _resolve_fund(self, name_or_cik: str) -> Optional[str]:
        if name_or_cik.isdigit() and len(name_or_cik) == 10:
            return name_or_cik
        row = self.bot.conn.execute(
            "SELECT cik FROM funds WHERE name LIKE ? OR cik = ? LIMIT 1",
            (f"%{name_or_cik}%", name_or_cik)
        ).fetchone()
        return row['cik'] if row else None
    
    def _get_latest_quarter(self, fund_cik: str) -> Optional[date]:
        row = self.bot.conn.execute("""
            SELECT MAX(report_period) as latest FROM filings 
            WHERE fund_cik = ? AND has_infotable = 1
        """, (fund_cik,)).fetchone()
        return date.fromisoformat(row['latest']) if row and row['latest'] else None


class MarketCommands(app_commands.Group):
    """Market-wide consensus and trend queries."""
    
    def __init__(self, bot: ScannerBot):
        super().__init__(name="market", description="Market-wide 13F trends")
        self.bot = bot
    
    @app_commands.command(name="consensus", description="Show tickers with multi-fund conviction")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD (default: latest)", min_funds="Minimum funds tracking")
    async def consensus(self, interaction: discord.Interaction, quarter: str = None, min_funds: int = 3):
        await interaction.response.defer(ephemeral=True)
        
        if quarter:
            report_period = date.fromisoformat(quarter)
        else:
            row = self.bot.conn.execute("""
                SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
            """).fetchone()
            report_period = date.fromisoformat(row['latest']) if row else None
        
        if not report_period:
            await interaction.followup.send("❌ No data available")
            return
        
        rows = self.bot.conn.execute("""
            SELECT 
                hc.ticker, hc.issuer_name,
                COUNT(*) as funds_total,
                SUM(CASE WHEN hc.status IN ('NEW','INCREASED') THEN 1 ELSE 0 END) as funds_adding,
                SUM(CASE WHEN hc.status IN ('CLOSED','DECREASED') THEN 1 ELSE 0 END) as funds_reducing,
                SUM(hc.curr_value_usd) as total_value,
                SUM(hc.value_change_usd) as net_change
            FROM holding_changes hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ? AND hc.put_call = ''
            GROUP BY hc.ticker, hc.issuer_name
            HAVING funds_total >= ?
            ORDER BY funds_adding DESC, net_change DESC
            LIMIT 20
        """, (report_period, min_funds)).fetchall()
        
        if not rows:
            await interaction.followup.send(f"❌ No consensus data for {report_period} (min_funds={min_funds})")
            return
        
        embed = discord.Embed(
            title=f"🎯 Institutional Consensus — {report_period}",
            description=f"Tickers held by ≥{min_funds} tracked funds",
            color=0x2F5496
        )
        
        for i, row in enumerate(rows[:15], 1):
            sentiment = "🟢" if row['funds_adding'] > row['funds_reducing'] else "🔴" if row['funds_reducing'] > row['funds_adding'] else "⚪"
            embed.add_field(
                name=f"{i}. {sentiment} {row['ticker']} — {row['issuer_name'][:35]}",
                value=f"📊 {row['funds_total']} funds • 🟢{row['funds_adding']} adding 🔴{row['funds_reducing']} reducing • Net ${row['net_change']:,.0f}",
                inline=False
            )
        
        embed.set_footer(text="Use /export consensus for full Excel with fund-level detail")
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="buys", description="Top new positions across all funds")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD (default: latest)", limit="Number of results")
    async def buys(self, interaction: discord.Interaction, quarter: str = None, limit: int = 15):
        await interaction.response.defer(ephemeral=True)
        
        report_period = date.fromisoformat(quarter) if quarter else self._latest_quarter()
        
        rows = self.bot.conn.execute("""
            SELECT hc.ticker, hc.issuer_name, COUNT(*) as fund_count,
                   SUM(hc.curr_value_usd) as total_value,
                   GROUP_CONCAT(DISTINCT f.name) as funds
            FROM holding_changes hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ? AND hc.status = 'NEW' AND hc.put_call = ''
            GROUP BY hc.ticker, hc.issuer_name
            ORDER BY total_value DESC
            LIMIT ?
        """, (report_period, limit)).fetchall()
        
        embed = discord.Embed(title=f"🟢 Top New Positions — {report_period}", color=0x00AA00)
        for i, row in enumerate(rows, 1):
            embed.add_field(
                name=f"{i}. {row['ticker']} — {row['issuer_name'][:40]}",
                value=f"{row['fund_count']} funds • ${row['total_value']:,.0f} • {row['funds'][:80]}",
                inline=False
            )
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="sells", description="Top exits across all funds")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD (default: latest)", limit="Number of results")
    async def sells(self, interaction: discord.Interaction, quarter: str = None, limit: int = 15):
        await interaction.response.defer(ephemeral=True)
        
        report_period = date.fromisoformat(quarter) if quarter else self._latest_quarter()
        
        rows = self.bot.conn.execute("""
            SELECT hc.ticker, hc.issuer_name, COUNT(*) as fund_count,
                   SUM(hc.prev_value_usd) as total_value,
                   GROUP_CONCAT(DISTINCT f.name) as funds
            FROM holding_changes hc
            JOIN funds f ON hc.fund_cik = f.cik
            WHERE hc.curr_report_period = ? AND hc.status = 'CLOSED' AND hc.put_call = ''
            GROUP BY hc.ticker, hc.issuer_name
            ORDER BY total_value DESC
            LIMIT ?
        """, (report_period, limit)).fetchall()
        
        embed = discord.Embed(title=f"🔴 Top Full Exits — {report_period}", color=0xAA0000)
        for i, row in enumerate(rows, 1):
            embed.add_field(
                name=f"{i}. {row['ticker']} — {row['issuer_name'][:40]}",
                value=f"{row['fund_count']} funds • was ${row['total_value']:,.0f} • {row['funds'][:80]}",
                inline=False
            )
        await interaction.followup.send(embed=embed)
    
    def _latest_quarter(self) -> date:
        row = self.bot.conn.execute("""
            SELECT MAX(report_period) as latest FROM filings WHERE has_infotable = 1
        """).fetchone()
        return date.fromisoformat(row['latest']) if row else date.today()


class ExportCommands(app_commands.Group):
    """Excel export commands."""
    
    def __init__(self, bot: ScannerBot):
        super().__init__(name="export", description="Generate Excel analysis files")
        self.bot = bot
    
    @app_commands.command(name="fund-changes", description="Export QoQ changes Excel for a fund")
    @app_commands.describe(fund="Fund name or CIK", quarter="Quarter end YYYY-MM-DD")
    async def fund_changes(self, interaction: discord.Interaction, fund: str, quarter: str):
        await interaction.response.defer(ephemeral=True)
        
        fund_cik = self._resolve_fund(fund)
        if not fund_cik:
            await interaction.followup.send(f"❌ Fund not found: {fund}")
            return
        
        curr = date.fromisoformat(quarter)
        prev = self.bot.comparator.get_previous_quarter(curr)
        
        path = f"/tmp/changes_{fund_cik}_{quarter}.xlsx"
        try:
            self.bot.exporter.export_fund_changes(fund_cik, curr, prev, path)
            await interaction.followup.send(
                file=discord.File(path, filename=f"{fund}_changes_{quarter}.xlsx")
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Export failed: {e}")
    
    @app_commands.command(name="consensus", description="Export market consensus Excel")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD", min_funds="Minimum funds tracking")
    async def consensus(self, interaction: discord.Interaction, quarter: str, min_funds: int = 2):
        await interaction.response.defer(ephemeral=True)
        
        report_period = date.fromisoformat(quarter)
        path = f"/tmp/consensus_{quarter}.xlsx"
        
        try:
            self.bot.exporter.export_consensus_report(report_period, path, min_funds)
            await interaction.followup.send(
                file=discord.File(path, filename=f"consensus_{quarter}.xlsx")
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Export failed: {e}")
    
    @app_commands.command(name="quarterly-package", description="Generate complete quarterly analysis package (ZIP)")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD")
    async def quarterly_package(self, interaction: discord.Interaction, quarter: str):
        await interaction.response.defer(ephemeral=True)
        
        report_period = date.fromisoformat(quarter)
        output_dir = f"/tmp/quarterly_package_{quarter}"
        
        try:
            results = self.bot.exporter.generate_quarterly_package(report_period, output_dir)
            zip_path = results['zip']
            await interaction.followup.send(
                file=discord.File(zip_path, filename=f"13f_package_{quarter}.zip")
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Package generation failed: {e}")
    
    def _resolve_fund(self, name_or_cik: str) -> Optional[str]:
        if name_or_cik.isdigit() and len(name_or_cik) == 10:
            return name_or_cik
        row = self.bot.conn.execute(
            "SELECT cik FROM funds WHERE name LIKE ? OR cik = ? LIMIT 1",
            (f"%{name_or_cik}%", name_or_cik)
        ).fetchone()
        return row['cik'] if row else None


class AdminCommands(app_commands.Group):
    """Admin/maintenance commands (restrict to authorized users)."""
    
    def __init__(self, bot: ScannerBot, allowed_users: List[int] = None):
        super().__init__(name="admin", description="Admin commands")
        self.bot = bot
        self.allowed_users = allowed_users or []
    
    def _check_permission(self, interaction: discord.Interaction) -> bool:
        if not self.allowed_users:
            return True  # No restriction if not configured
        return interaction.user.id in self.allowed_users
    
    @app_commands.command(name="ingest", description="Ingest latest 13F filings for all tracked funds")
    @app_commands.describe(max_filings="Max filings per fund (default: 4)")
    async def ingest(self, interaction: discord.Interaction, max_filings: int = 4):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            summary = self.bot.ingestor.ingest_all_tracked_funds(max_filings)
            
            embed = discord.Embed(title="📥 Ingestion Complete", color=0x00AA00)
            embed.add_field(name="Funds Tracked", value=summary['total_funds'], inline=True)
            embed.add_field(name="Funds Updated", value=summary['processed_funds'], inline=True)
            embed.add_field(name="New Filings", value=summary['total_filings'], inline=True)
            embed.add_field(name="Total Holdings", value=summary['total_holdings'], inline=True)
            
            if summary['errors']:
                embed.add_field(name="⚠️ Errors", value=f"{len(summary['errors'])} (check logs)", inline=False)
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Ingestion failed: {e}")
    
    @app_commands.command(name="compute-changes", description="Compute QoQ changes for a quarter")
    @app_commands.describe(quarter="Quarter end YYYY-MM-DD (default: latest)", backfill="Compute all historical")
    async def compute_changes(self, interaction: discord.Interaction, quarter: str = None, backfill: bool = False):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            if backfill:
                result = self.bot.comparator.compute_historical_changes()
                await interaction.followup.send(f"✅ Backfill complete: {result['quarters_processed']} quarter pairs processed")
            elif quarter:
                curr = date.fromisoformat(quarter)
                result = self.bot.comparator.compute_changes_all_funds(curr)
                await interaction.followup.send(
                    f"✅ Changes computed for {quarter}: {result['funds_compared']} funds, "
                    f"{result['total_changes']} total changes\n"
                    f"NEW: {result['aggregate_status'].get('NEW',0)} • "
                    f"INCREASED: {result['aggregate_status'].get('INCREASED',0)} • "
                    f"DECREASED: {result['aggregate_status'].get('DECREASED',0)} • "
                    f"CLOSED: {result['aggregate_status'].get('CLOSED',0)}"
                )
            else:
                # Latest quarter
                quarters = self.bot.comparator.get_available_quarters()
                if quarters:
                    result = self.bot.comparator.compute_changes_all_funds(quarters[-1])
                    await interaction.followup.send(f"✅ Changes computed for {quarters[-1]}: {result['funds_compared']} funds")
                else:
                    await interaction.followup.send("❌ No filings in database")
        except Exception as e:
            await interaction.followup.send(f"❌ Computation failed: {e}")
    
    @app_commands.command(name="list-funds", description="List all tracked funds")
    async def list_funds(self, interaction: discord.Interaction):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        
        funds = get_tracked_funds(self.bot.conn)
        
        embed = discord.Embed(title="📋 Tracked Funds", color=0x2F5496)
        
        # Group by strategy
        by_strategy = {}
        for f in funds:
            strat = f['strategy'] or 'other'
            if strat not in by_strategy:
                by_strategy[strat] = []
            by_strategy[strat].append(f)
        
        for strat, flist in by_strategy.items():
            value = "\n".join(f"• {f['name']} (`{f['cik']}`)" for f in flist[:10])
            if len(flist) > 10:
                value += f"\n... and {len(flist)-10} more"
            embed.add_field(name=strat.replace('_', ' ').title(), value=value, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="status", description="Show database status")
    async def status(self, interaction: discord.Interaction):
        if not self._check_permission(interaction):
            await interaction.response.send_message("❌ Unauthorized", ephemeral=True)
            return
        
        stats = {}
        stats['funds'] = self.bot.conn.execute("SELECT COUNT(*) FROM funds WHERE is_active=1").fetchone()[0]
        stats['filings'] = self.bot.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        stats['holdings'] = self.bot.conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        stats['changes'] = self.bot.conn.execute("SELECT COUNT(*) FROM holding_changes").fetchone()[0]
        stats['quarters'] = self.bot.conn.execute("SELECT COUNT(DISTINCT report_period) FROM filings WHERE has_infotable=1").fetchone()[0]
        
        latest = self.bot.conn.execute("SELECT MAX(report_period) FROM filings WHERE has_infotable=1").fetchone()[0]
        
        embed = discord.Embed(title="📊 Database Status", color=0x2F5496)
        embed.add_field(name="Tracked Funds", value=stats['funds'], inline=True)
        embed.add_field(name="Filings Stored", value=stats['filings'], inline=True)
        embed.add_field(name="Holdings Rows", value=f"{stats['holdings']:,}", inline=True)
        embed.add_field(name="Change Records", value=f"{stats['changes']:,}", inline=True)
        embed.add_field(name="Quarters Covered", value=stats['quarters'], inline=True)
        embed.add_field(name="Latest Quarter", value=latest or "None", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup_bot_commands(bot: ScannerBot, allowed_admin_users: List[int] = None):
    """Register all command groups with the bot."""
    bot.tree.add_command(FundCommands(bot))
    bot.tree.add_command(MarketCommands(bot))
    bot.tree.add_command(ExportCommands(bot))
    bot.tree.add_command(AdminCommands(bot, allowed_admin_users))
    
    # Also add a simple ping command
    @bot.tree.command(name="ping", description="Health check")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("🏓 Pong! 13F Scanner is online.", ephemeral=True)
    
    @bot.tree.command(name="help", description="Show available commands")
    async def help_cmd(interaction: discord.Interaction):
        embed = discord.Embed(title="13F Scanner Bot Commands", color=0x2F5496)
        embed.add_field(
            name="📊 Fund Queries",
            value="`/fund holdings <fund> [quarter] [top]` — Top positions\n"
                  "`/fund changes <fund> [quarter]` — QoQ changes summary",
            inline=False
        )
        embed.add_field(
            name="🌍 Market Trends",
            value="`/market consensus [quarter] [min_funds]` — Multi-fund conviction\n"
                  "`/market buys [quarter]` — Top new positions\n"
                  "`/market sells [quarter]` — Top exits",
            inline=False
        )
        embed.add_field(
            name="📁 Exports",
            value="`/export fund-changes <fund> <quarter>` — Fund QoQ Excel (5 tabs)\n"
                  "`/export consensus <quarter> [min_funds]` — Consensus Excel\n"
                  "`/export quarterly-package <quarter>` — Full ZIP package",
            inline=False
        )
        embed.add_field(
            name="⚙️ Admin (authorized only)",
            value="`/admin ingest [max_filings]` — Fetch latest filings\n"
                  "`/admin compute-changes [quarter] [backfill]` — Compute QoQ diffs\n"
                  "`/admin list-funds` — Show tracked funds\n"
                  "`/admin status` — Database stats",
            inline=False
        )
        embed.set_footer(text="Data source: SEC EDGAR via edgartools (free, no API key)")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────────────────────────────────────────────────────────
# Standalone runner for testing
# ──────────────────────────────────────────────────────────────

async def run_bot(db_path: str, token: str, allowed_admins: List[int] = None):
    """Run the bot (for direct execution)."""
    bot = create_bot(db_path)
    setup_bot_commands(bot, allowed_admins)
    
    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        print("------")
    
    await bot.start(token)


if __name__ == "__main__":
    import argparse
    import asyncio
    
    parser = argparse.ArgumentParser(description="Run 13F Scanner Discord Bot")
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db", help="Database path")
    parser.add_argument("--token", required=True, help="Discord bot token")
    parser.add_argument("--admins", help="Comma-separated Discord user IDs for admin commands")
    args = parser.parse_args()
    
    allowed = [int(x) for x in args.admins.split(",")] if args.admins else None
    
    asyncio.run(run_bot(args.db, args.token, allowed))
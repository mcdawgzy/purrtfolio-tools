# 13F Scanner - Institutional Holdings Tracker

Track hedge fund and institutional investor portfolio changes via SEC 13F filings. Built with **edgartools** (free, no API key required).

## Features

- **📥 Automated Ingestion** — Fetch latest 13F-HR filings for 30+ tracked funds via edgartools
- **📊 QoQ Change Detection** — Classify every position: NEW, INCREASED, DECREASED, CLOSED, UNCHANGED
- **🎯 Consensus Analysis** — Identify tickers with multi-fund conviction (adding/exiting)
- **📁 Excel Exports** — Cross-check ready workbooks: fund holdings, changes (5 tabs), consensus, master tracker
- **🤖 Discord Bot** — Slash commands for queries, exports, and admin operations
- **⏰ Quarterly Automation** — Cronjob runs 45 days post-quarter-end

## Quick Start

```bash
# 1. Clone and install
cd 13f-scanner
pip install -r requirements.txt

# 2. Initialize database with 30 tracked funds
python main.py init

# 3. Ingest latest filings (all funds, last 4 quarters each)
python main.py ingest

# 4. Compute QoQ changes for latest quarter
python main.py compare

# 5. Generate consensus Excel for latest quarter
python main.py export --quarter 2025-09-30

# 6. Run Discord bot (requires token)
python main.py bot --token YOUR_DISCORD_TOKEN --admins YOUR_USER_ID
```

## Tracked Institutions (30)

| Tier | Funds |
|------|-------|
| **Core Hedge Funds** | Berkshire, Citadel, Bridgewater, Renaissance, Two Sigma, D.E. Shaw, Millennium, Point72 |
| **Large Asset Managers** | BlackRock, Vanguard, State Street, Fidelity, JPMorgan |
| **Activists** | Pershing Square, Elliott, Third Point, Starboard, ValueAct |
| **Tech/Growth** | Tiger Global, Coatue, D1 Capital, Altimeter, Whale Rock |
| **Value/Special Situations** | Baupost, Greenlight, Sachem Head |
| **Emerging** | Atreides, Monolith |
| **Sovereign** | Norges Bank, Temasek |

All parse via **edgartools** (free, no API key).

## Database Schema

- `funds` — Tracked institutions (CIK, name, strategy, AUM)
- `filings` — 13F submissions (accession, dates, totals)
- `holdings` — Normalized positions (CUSIP, ticker, shares, value, voting)
- `holding_changes` — Pre-computed QoQ diffs with classification
- `alerts` — User subscriptions for notifications
- `export_log` — Track generated Excel files

## Discord Commands

| Command | Description |
|---------|-------------|
| `/fund holdings <fund> [quarter] [top]` | Top positions for a fund |
| `/fund changes <fund> [quarter]` | QoQ change summary |
| `/market consensus [quarter] [min_funds]` | Multi-fund conviction tickers |
| `/market buys [quarter]` | Top new positions market-wide |
| `/market sells [quarter]` | Top exits market-wide |
| `/export fund-changes <fund> <quarter>` | Fund QoQ Excel (5 tabs) |
| `/export consensus <quarter> [min_funds]` | Consensus Excel |
| `/export quarterly-package <quarter>` | Full ZIP package |
| `/admin ingest [max_filings]` | Fetch latest filings (admin) |
| `/admin compute-changes [quarter] [backfill]` | Compute QoQ diffs (admin) |
| `/admin list-funds` | Show tracked funds (admin) |
| `/admin status` | Database stats (admin) |

## Excel Outputs

**`fund_changes_<CIK>_<quarter>.xlsx`** — 5 tabs:
1. All Changes (color-coded by status)
2. New Positions only
3. Exits only
4. Top 20 Increases
5. Top 20 Decreases

**`consensus_<quarter>.xlsx`** — Market-wide:
- Ticker, funds tracking, funds adding/reducing, net value change, fund action detail
- Green highlight: ≥5 funds adding | Red highlight: ≥5 funds reducing

**`master_tracker_<date>.xlsx`** — Historical reference:
- One sheet per quarter (last 8), each fund's top 10 holdings with weights

**`13f_package_<quarter>.zip`** — Complete quarterly analysis bundle

## Automation

Quarterly cronjob (runs ~45 days after quarter-end):
```bash
# Scheduled via Hermes cronjob
# 1. Ingest target quarter filings
# 2. Compute QoQ changes
# 3. Generate Excel package
# 4. Post to Discord with summary + ZIP
```

## Project Structure

```
13f-scanner/
├── main.py              # Unified CLI entry point
├── db_init.py           # Database schema + seed
├── ingest.py            # edgartools ingestion pipeline
├── compare.py           # QoQ change computation
├── export.py            # Excel report generation
├── bot.py               # Discord bot with slash commands
├── cronjob.yaml         # Hermes quarterly automation
├── requirements.txt     # Python dependencies
├── funds_seed.json      # 30 tracked institutions
└── 13f_scanner.db       # SQLite database (created on init)
```

## Requirements

- Python 3.10+
- `edgartools` (free, no API key — uses SEC EDGAR directly)
- Discord bot token (for bot mode)
- Hermes Agent (for cronjob automation)

## Data Source

**SEC EDGAR** via `edgartools` — completely free, no rate limits, parses both XML (post-2013) and fixed-width TXT (pre-2013) formats. All values stored in **actual USD** (SEC reports in thousands; we multiply by 1000).

## Key Technical Notes

1. **CUSIP is the primary key** — never join on name/ticker alone
2. **Values in database are actual USD** — not thousands
3. **45-day filing lag** — Q3 (Sep 30) filings appear mid-November
4. **Multi-manager filings** — edgartools `.holdings` aggregates automatically
5. **Amendments (13F-HR/A)** — handled via `accession_number` deduping
6. **Options positions** — `put_call` field separates PUT/CALL from equity

## Extending

- Add funds: edit `funds_seed.json` and re-run `python main.py init`
- Add sectors: enrich with yfinance or SEC company facts
- Add 13D/G + Form 4: extend ingestion for activist stakes + insider trades
- Add AI summaries: LLM-generated quarterly letters per fund
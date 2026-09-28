# Purrtfolio Tools

Free institutional-ownership + macro market dashboard. Reads from the unified
`purrtfolio.db` (SEC EDGAR + FINRA data) and exposes a small REST API for a
static frontend. Includes 13F scanner, short-interest scanner, and daily
market snapshot renderers.

## Architecture

```
purrtfolio-tools/
├── src/                  # FastAPI backend
│   ├── api.py            # REST endpoints + error envelope
│   ├── db.py             # SQLite query helpers (read-only)
│   └── __init__.py
├── static/               # Frontend source (HTML / CSS / JS)
├── docs/                 # GitHub Pages build output (copy of static/)
├── cron/                 # Hermes job runners (see cron/README.md)
├── scripts/              # One-off maintenance helpers
├── scanners/             # Data ingestion (each writes to purrtfolio.db)
│   ├── 13f/                  # 13F filings (ingest, compare, export, Discord bot)
│   ├── short_interest_scanner/  # FINRA short interest
│   ├── form4_insider_trading/   # SEC Form 4 insider trades
│   ├── economic-calendar/    # FOMC / CPI / NFP / central-bank events
│   ├── put_call_ratio/       # CBOE put/call ratios
│   ├── implied_volatility/   # IV rank
│   ├── unusual_activity/     # Unusual options activity
│   ├── news_sentiment/       # RSS headlines + VADER sentiment
│   ├── price_momentum/       # Price history + momentum signals (slim DB)
│   ├── correlation_matrix/   # Rolling correlations vs pivot assets (slim DB)
│   ├── earnings_revisions/   # Earnings revision momentum
│   ├── crowded_trades/       # Multi-signal crowdedness score
│   └── trader_quotes/        # Seed data for the quotes page
├── snapshots/            # Market snapshot renderers
│   ├── market/           # Compact 16:9 market snapshot PNG (X/Twitter)
│   └── macro/            # Editorial-style macro market update PNG (Discord)
├── tests/                # API smoke tests (need a local purrtfolio.db)
├── render.yaml           # Render free-tier deploy config
├── requirements.txt      # API deps (scanner deps: see "Scanners")
└── README.md
```

## Run the dashboard locally

```bash
pip install -r requirements.txt
python -m uvicorn src.api:app --port 8000
```

Then open `http://127.0.0.1:8000/` (the frontend talks to the local API
automatically) or `http://127.0.0.1:8000/api/health`.

The DB path defaults to `~/purrtfolio.db` for the API **and** all scanners.
Override with the `PURRTFOLIO_DB` env var. The slim momentum/correlation DB
lives at `MOMENTUM_DB` (default: next to `PURRTFOLIO_DB`) and is downloaded
from the latest DB release on startup if missing.

To point the hosted frontend at a local or preview API, add
`?api=http://localhost:8000` to the page URL.

### Tests

```bash
pip install pytest httpx
python -m pytest tests -q     # hits every GET route against your local DB
```

CI (`.github/workflows/ci.yml`) compiles all Python, imports the API, and
syntax-checks `static/app.js` on every PR.

## API endpoints

The full, always-current list (with parameters) is at `/docs` (Swagger UI)
on any running instance. Route groups: `/api/funds`, `/api/tickers`,
`/api/consensus`, `/api/sectors`, `/api/si`, `/api/insider`, `/api/econ`,
`/api/pcr`, `/api/iv`, `/api/ua`, `/api/screener`, `/api/quotes`,
`/api/earnings-revisions`, `/api/snapshot`, `/api/news`, `/api/momentum`,
`/api/correlation`, `/api/factors`, `/api/ct` (crowded trades).

All endpoints return JSON. Errors (including validation errors and unexpected
500s) come back as `{"error": "...", "status": NNN}` — 404 for missing funds,
422 for bad input, 503 if the DB file is missing.

## Scanners

Scanners run on the Hermes cron host via the runners in `cron/` (see
`cron/README.md`), not on Render. Most
are packages run from inside `scanners/`, e.g. `python -m put_call_ratio`.
Beyond `requirements.txt` they need `apscheduler`, `httpx`, `nltk` and (13F)
`edgartools` — see each scanner's own requirements file where present.

### 13F Scanner (`scanners/13f/`)

Quarterly ingestion of institutional 13F filings from SEC EDGAR via
`edgartools`. Tracks ~27 curated funds across value, quant, tech growth,
activist, and macro strategies.

```bash
cd scanners/13f
python main.py ingest --email "bot@example.com" --max-filings 3
python main.py compare --backfill
python main.py export --quarter 2026-06-30 --package
```

Cron: quarterly pipeline (`job id d55765979399`, runs `0 6 15 2,5,8,11 *` —
see Hermes `jobs.json`; `cronjob.yaml` is an older copy).

### Short Interest Scanner (`scanners/short_interest_scanner/`)

Daily ingestion of FINRA short interest data for a curated watchlist of
~50 large-cap tickers. Data is aggregate per ticker (not per-fund).

```bash
cd scanners
python -m short_interest_scanner ingest     # fetch latest settlement date
python -m short_interest_scanner analyze    # generate signal reports
python -m short_interest_scanner export     # export CSV/JSON signals
```

A fresh DB needs `short_interest_scanner/fix_unified_schema.py` once to create
the short-interest tables.

Cron: daily ingestion (`job id 3563943d0bcb`, runs `0 6 * * *`).

### Economic Calendar Scanner (`scanners/economic-calendar/`)

Daily ingestion of upcoming high-impact economic events affecting the
trading markets. Uses free data sources only — no paid API keys required:
- FOMC meetings: scraped from the Federal Reserve website
- US economic releases (CPI, PPI, NFP, GDP, etc.): Finnhub free API
  (optional key) with a curated fallback list
- ECB, BOE, BOJ rate decisions: curated schedule

```bash
cd scanners/economic-calendar
python main.py ingest        # fetch upcoming events (next 30 days) and upsert into DB
python main.py stats         # show DB stats
python main.py export        # export to CSV
```

Cron: daily ingestion (`job id 9e82fa1a9f04`, runs `0 5 * * *`).

## Market Snapshots

### Market Snapshot (`snapshots/market/`)

Compact 16:9 PNG market snapshot (1280×720 @ 200 DPI) with:
- 31 tickers across 7 sections (US Equities, Global Equities, US Rates, FX,
  Commodities, Market Internals, Crypto)
- Tiered narrative depth (2-3 sentences for top 5, 1-liners for rest)
- Green/red color coding for moves, brass (#C9A24E) accent for @Purrtfolio
- Pure typography, minimal color

### Macro Market Update (`snapshots/macro/`)

Editorial-style macro market update PNG posted to Discord at 7 AM UTC+10:
- Header: "Market Snapshot - Month DD YYYY"
- Consolidated treasury rows (2Y/5Y/10Y/30Y only)
- Text-wrapped driver narratives
- Green/red color coding on Level/Move column
- After each run, the latest PNG + JSON report + caption are copied to
  `static/snapshots/` so the web dashboard can serve them via
  `/api/snapshot/latest` and `/snapshots/market_snapshot.png`
- The web frontend has a "Market Snapshot" nav tab showing the latest PNG
  with the top 3 mover narratives and a fresh daily caption

## Production deployment

**GitHub Pages** (frontend) + **Render free tier** (API):
- Frontend served from `docs/` (CI copies `static/` → `docs/` on push to master)
- API deployed via `render.yaml`
- DB published daily as a GitHub Release (`db-vYYYY-MM-DD`) by the Hermes
  "DB Release Auto-Publish" job, which bumps the tag in `src/db.py`,
  `render.yaml` and `scripts/download_db.sh` and pushes (triggering a redeploy)
- Keep-alive via GitHub Actions (`.github/workflows/keepalive.yml`)

**Render cold-start:** Free tier spins down after 15min idle. Keep-alive pings
every 10 min to prevent this.

> **Known issue:** Render runs `preDeployCommand` only on paid plans, and even
> there its filesystem changes are not kept. On the free plan the main DB is
> therefore downloaded lazily by the first API request after each deploy
> (`src/db.py:_download_db_if_needed`), which is what makes that request slow.
> Fix: download in `buildCommand` into the project directory (build output
> under `/opt/render/project/src` is kept) and point `PURRTFOLIO_DB` there.

## Sectors endpoint

The `/api/sectors` endpoint joins `holdings_13f` → `tickers.sector`. Currently
only ~6% of tracked AUM has sector data populated (mostly tickers enriched by
the short-interest scanner). To make sectors useful, populate `tickers.sector`
via a GICS lookup (e.g. `yfinance` or SEC company facts). Run the sector
enrichment cron weekly for new tickers.

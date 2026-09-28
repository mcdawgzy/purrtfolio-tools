# Purrtfolio Tools

Free institutional-ownership + macro market dashboard. Scanners (run by Hermes
cron jobs) write SEC / FINRA / CBOE / market data into one SQLite file,
`purrtfolio.db`; a read-only FastAPI backend serves it to a static, no-build
frontend on GitHub Pages.

## Architecture

```
purrtfolio-tools/
├── src/                  # FastAPI backend (read-only)
│   ├── main.py           # app: middleware, error handlers, routers, static mounts
│   ├── api.py            # `uvicorn src.api:app` entry point (re-exports main.app)
│   ├── config.py         # env config + DB release tag (bumped daily by cron)
│   ├── database.py       # read-only connections, download-if-missing
│   ├── errors.py         # {"error", "status"} envelope for every error
│   ├── scanner_data.py   # the one bridge into scanners/ (momentum, correlation)
│   ├── queries/          # SQL, one module per domain
│   └── routers/          # FastAPI routers, one per domain
├── static/               # Frontend (native ES modules, no build step)
│   ├── index.html
│   ├── styles.css
│   ├── chart.min.js      # vendored Chart.js, lazy-loaded
│   └── js/
│       ├── main.js       # boot
│       ├── router.js     # hash routing + render dispatch
│       ├── nav.js        # nav menus + page descriptions
│       ├── core/         # api, state, dom, format, charts helpers
│       └── views/        # one module per page (+ calculators/)
├── docs/                 # GitHub Pages output (CI copies static/ here; don't edit)
├── scanners/             # Data ingestion package: python -m scanners.<name> ...
│   ├── common.py         # DB paths, connect(), shared tables (tickers, sectors)
│   ├── thirteen_f/           # 13F filings (ingest, compare, export, enrichment)
│   ├── short_interest_scanner/  # FINRA short interest
│   ├── form4_insider_trading/   # SEC Form 4 insider trades
│   ├── economic_calendar/    # FOMC / CPI / NFP / central-bank events
│   ├── put_call_ratio/       # CBOE put/call ratios
│   ├── implied_volatility/   # IV rank
│   ├── unusual_activity/     # Unusual options activity
│   ├── news_sentiment/       # RSS headlines + VADER sentiment
│   ├── price_momentum/       # Price history + momentum signals
│   ├── correlation_matrix/   # Rolling correlations vs pivot assets
│   ├── earnings_revisions/   # Earnings revision momentum
│   ├── crowded_trades/       # Multi-signal crowdedness score
│   └── trader_quotes/        # Quotes page seed data
├── cron/                 # Hermes job runners (see cron/README.md)
├── snapshots/            # Market snapshot PNG renderers
│   ├── market/           # Compact 16:9 market snapshot PNG (X/Twitter)
│   └── macro/            # Editorial-style macro market update PNG (Discord)
├── research/             # Strategy research content (not deployed)
├── scripts/keepalive.py  # Optional local keep-alive pinger
├── tests/                # pytest: API routes, scanner imports, fresh-DB bootstrap
├── render.yaml           # Render free-tier deploy config
├── requirements.txt      # API dependencies
└── requirements-scanners.txt  # + scanner / cron / snapshot dependencies
```
## Run the dashboard locally

```bash
pip install -r requirements.txt
python -m uvicorn src.api:app --port 8000
```

Then open `http://127.0.0.1:8000/` (the frontend talks to the local API
automatically) or `http://127.0.0.1:8000/api/health`.

The DB path defaults to `~/purrtfolio.db` for the API **and** all scanners
(`scanners/common.py`). Override with the `PURRTFOLIO_DB` env var.
Momentum/correlation data is read from `MOMENTUM_DB` if set (Render uses a
small extract published with each DB release), otherwise from the main DB.
The API downloads the release DB only when the file is missing; it never
replaces an existing file unless `DB_AUTO_REFRESH=1` (set on Render).

To point the hosted frontend at a local or preview API, add
`?api=http://localhost:8000` to the page URL.

### Tests

```bash
pip install -r requirements-scanners.txt pytest httpx
python -m pytest tests -q
```

- `tests/test_api_smoke.py` hits every GET route against your local DB
  (skipped when there's no DB, e.g. in CI).
- `tests/test_scanners.py` imports every scanner module and cron runner, and
  bootstraps a fresh DB from the scanners' schema functions in random orders.

CI (`.github/workflows/ci.yml`) runs the tests, compiles all Python, and
syntax-checks every frontend module on each PR.

### Frontend

`static/` is served as-is (no bundler). Each page lives in
`static/js/views/<page>.js` and exports its loader(s) and render function;
`router.js` maps hashes to views. Shared helpers are in `static/js/core/`.
Edit `static/`, never `docs/`: CI mirrors `static/` → `docs/` on push to
master.

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
`cron/README.md`), not on Render. Each is a package under `scanners/`, run
from the repo root: `python -m scanners.<name> ...`. Dependencies:
`pip install -r requirements-scanners.txt`.

### 13F Scanner (`scanners/thirteen_f/`)

Quarterly ingestion of institutional 13F filings from SEC EDGAR via
`edgartools`. Tracks ~27 curated funds across value, quant, tech growth,
activist, and macro strategies.

```bash
python -m scanners.thirteen_f ingest --email "bot@example.com" --max-filings 3
python -m scanners.thirteen_f compare --backfill
python -m scanners.thirteen_f export --quarter 2026-06-30 --package
python -m scanners.thirteen_f.quarterly_pipeline   # all of the above + enrichment
```

Cron: quarterly pipeline (`job id d55765979399`, runs `0 6 15 2,5,8,11 *` —
see Hermes `jobs.json`; `cronjob.yaml` is an older copy).

### Short Interest Scanner (`scanners/short_interest_scanner/`)

Daily ingestion of FINRA short interest data for a curated watchlist of
~50 large-cap tickers. Data is aggregate per ticker (not per-fund).

```bash
python -m scanners.short_interest_scanner ingest     # fetch latest settlement date
python -m scanners.short_interest_scanner analyze    # generate signal reports
python -m scanners.short_interest_scanner export     # export CSV/JSON signals
```

A fresh DB needs `python -m scanners.short_interest_scanner.fix_unified_schema`
once to create the short-interest tables.

Cron: daily ingestion (`job id 3563943d0bcb`, runs `0 6 * * *`).

### Economic Calendar Scanner (`scanners/economic_calendar/`)

Daily ingestion of upcoming high-impact economic events affecting the
trading markets. Uses free data sources only — no paid API keys required:
- FOMC meetings: scraped from the Federal Reserve website
- US economic releases (CPI, PPI, NFP, GDP, etc.): Finnhub free API
  (optional key) with a curated fallback list
- ECB, BOE, BOJ rate decisions: curated schedule

```bash
python -m scanners.economic_calendar ingest   # fetch upcoming events (next 30 days) and upsert
python -m scanners.economic_calendar stats    # show DB stats
python -m scanners.economic_calendar export   # export to CSV
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
  "DB Release Auto-Publish" job (`cron/publish_db_release.py`), which rewrites
  the tag in `src/config.py` and `render.yaml` in the cron checkout. Render
  only picks up the new DB once that change is committed and pushed (which
  triggers a redeploy); the job doesn't commit it itself.
- Keep-alive via GitHub Actions (`.github/workflows/keepalive.yml`)

**Render cold-start:** Free tier spins down after 15min idle. Keep-alive pings
every 10 min to prevent this.

> **Known issue:** Render runs `preDeployCommand` only on paid plans, and even
> there its filesystem changes are not kept. On the free plan the main DB is
> therefore downloaded lazily by the first API request after each deploy
> (`src/database.py:_download_db_if_needed`), which is what makes that request slow.
> Fix: download in `buildCommand` into the project directory (build output
> under `/opt/render/project/src` is kept) and point `PURRTFOLIO_DB` there.

## Sectors endpoint

The `/api/sectors` endpoint joins `holdings_13f` → sector data populated by the
weekly Sector Enrichment job (`python -m scanners.thirteen_f.enrich_sectors`,
yfinance GICS lookups). Coverage is ~97% of tracked 13F AUM.

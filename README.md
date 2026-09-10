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
├── scripts/              # Cron shims + sync helpers
├── scanners/             # Data ingestion scanners
│   ├── 13f/              # 13F scanner (ingest, compare, export, bot)
│   └── short-interest/   # FINRA short interest scanner
├── snapshots/            # Market snapshot renderers
│   ├── market/           # Compact 16:9 market snapshot PNG (X/Twitter)
│   └── macro/            # Editorial-style macro market update PNG (Discord)
├── render.yaml           # Render free-tier deploy config
├── requirements.txt
└── README.md
```

## Run the dashboard locally

```bash
cd C:/Users/cho_i/13f-scanner-web
pip install -r requirements.txt
python -m uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Then visit `http://127.0.0.1:8000/api/health` to confirm.

The DB path defaults to `C:/Users/cho_i/purrtfolio.db`. Override with
`PURRTFOLIO_DB` env var (used in production for read-only file mounts).

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | DB connectivity check |
| `GET /api/meta` | Row counts, available quarters, last update |
| `GET /api/funds` | List funds + strategy + latest quarter AUM |
| `GET /api/funds/{cik}` | Fund detail + filings history |
| `GET /api/funds/{cik}/holdings` | Holdings for a fund (paginated, sortable) |
| `GET /api/funds/{cik}/changes` | QoQ changes for a fund |
| `GET /api/tickers/{ticker}` | Cross-fund holders of a ticker |
| `GET /api/consensus` | Tickers with cross-fund momentum |
| `GET /api/sectors` | Sector aggregation (limited — see note) |

All endpoints return JSON. Errors come back as `{"error": "...", "status": NNN}`
with appropriate HTTP status (404 for missing funds, 422 for bad input, 503 if DB
file is missing).

## Scanners

### 13F Scanner (`scanners/13f/`)

Quarterly ingestion of institutional 13F filings from SEC EDGAR via
`edgartools`. Tracks ~27 curated funds across value, quant, tech growth,
activist, and macro strategies.

```bash
cd scanners/13f
python main.py --db C:/Users/cho_i/purrtfolio.db ingest --email "bot@example.com" --max-filings 3
python main.py --db C:/Users/cho_i/purrtfolio.db compare --backfill
python main.py --db C:/Users/cho_i/purrtfolio.db export --quarter 2026-06-30 --package
```

Cron: quarterly pipeline (`job id d55765979399`, runs `0 6 15 2,5,8,11 *`).

### Short Interest Scanner (`scanners/short-interest/`)

Daily ingestion of FINRA short interest data for a curated watchlist of
~50 large-cap tickers. Data is aggregate per ticker (not per-fund).

```bash
cd scanners/short-interest
python main.py ingest     # fetch latest settlement date
python main.py analyze    # generate signal reports
python main.py export     # export CSV/JSON signals
```

Cron: daily ingestion (`job id 3563943d0bcb`, runs `0 6 * * *`).

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

## Production deployment

**GitHub Pages** (frontend) + **Render free tier** (API):
- Frontend served from `docs/` (CI copies `static/` → `docs/` on push)
- API deployed via `render.yaml` with read-only DB mount
- DB synced quarterly via cron (`scripts/sync_db.py`)
- Keep-alive via GitHub Actions (`.github/workflows/keepalive.yml`)

**Render cold-start:** Free tier spins down after 15min idle. First request
takes 30-60s (container spin-up + DB download). Keep-alive workflows ping
`/api/health` every 10 min to prevent this.

## Sectors endpoint

The `/api/sectors` endpoint joins `holdings_13f` → `tickers.sector`. Currently
only ~6% of tracked AUM has sector data populated (mostly tickers enriched by
the short-interest scanner). To make sectors useful, populate `tickers.sector`
via a GICS lookup (e.g. `yfinance` or SEC company facts). Run the sector
enrichment cron weekly for new tickers.

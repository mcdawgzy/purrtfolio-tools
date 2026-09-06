# 13F Tracker — Web

Free 13F institutional-ownership dashboard. Reads from the unified `purrtfolio.db`
(SEC EDGAR data) and exposes a small REST API for a static frontend.

## Architecture

```
13f-scanner-web/
├── src/
│   ├── api.py          # FastAPI app + HTTP endpoints
│   ├── db.py           # SQLite query helpers (read-only)
│   └── __init__.py
├── static/             # frontend (HTML / CSS / JS, served at /)
├── requirements.txt
└── README.md
```

## Run locally

```bash
# From repo root
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
| `GET /api/funds` | List 27 funds + strategy + latest quarter AUM |
| `GET /api/funds/{cik}` | Fund detail + filings history |
| `GET /api/funds/{cik}/holdings` | Holdings for a fund (paginated, sortable) |
| `GET /api/funds/{cik}/changes` | QoQ changes for a fund |
| `GET /api/tickers/{ticker}` | Cross-fund holders of a ticker |
| `GET /api/consensus` | Tickers with cross-fund momentum |
| `GET /api/sectors` | Sector aggregation (limited — see note) |

All endpoints return JSON. Errors come back as `{"error": "...", "status": NNN}`
with appropriate HTTP status (404 for missing funds, 422 for bad input, 503 if DB
file is missing).

## Sectors endpoint

The `/api/sectors` endpoint joins `holdings_13f` → `tickers.sector`. Currently
only ~6% of tracked AUM has sector data populated (mostly tickers enriched by
the short-interest scanner). To make sectors useful, populate `tickers.sector`
via a GICS lookup (e.g. `yfinance` or SEC company facts).

## Production deployment

Designed for **GitHub Pages** (frontend) + **Render free tier** (API).
See deployment notes in `/ `main conversation — Phase 3.
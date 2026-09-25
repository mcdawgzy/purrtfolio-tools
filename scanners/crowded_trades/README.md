# Crowded Trades Scanner

**Purpose:** Identifies tickers where market positioning is most crowded — across
both long and short sides — by aggregating signals from all upstream scanners
into a single 0–100 crowdedness score per ticker.

## Architecture

```
crowded_trades/
├── __init__.py
├── __main__.py          # CLI entry: python -m crowded_trades {run|analyze} ...
├── config.py            # Thresholds, weights, PCR thresholds, watchlist path
├── db.py                # Schema init, batch loaders, result persistence
├── analyzer.py          # Scoring engine (6 components → 0-100 score)
├── scheduler.py         # run_once() — orchestrates the full pipeline
└── main.py              # CLI argument parser & output formatting
```

## Data Sources (all from `purrtfolio.db`)

| Component     | Source scanner table             | Data date      |
|---------------|----------------------------------|----------------|
| Short Interest| `short_interest`                 | most recent    |
| Options Flow  | `unusual_activity`               | most recent    |
| IV Rank       | `iv_rank`                        | most recent    |
| Momentum      | `price_momentum_signals`         | most recent    |
| Put/Call Ratio| `put_call_latest`                | most recent    |
| Correlation   | `corr_matrices` (3_month window) | most recent    |

## Scoring Methodology

Each ticker gets a 0–100 score from six components:

1. **Short Interest (0–40)** — based on SIR, DTC days, and change velocity
2. **Options Flow (0–30)** — severity of unusual activity (call/put volume spikes)
3. **IV Rank (0–15)** — uses `iv_rank`/`iv_pctile` from the IV scanner; falls back
   to peer-relative IV percentile (ranked within category, min 5 peers)
4. **Momentum (0–15)** — ROC + volume spike from the momentum scanner
5. **Put/Call Ratio (0–20)** — deviation from normal PCR (extreme = crowded)
6. **Correlation (0–20)** — 3-month correlation to SPY (high = herding)

### Direction

- `long` — bullish crowding (everyone long, PCR low, high momentum)
- `short` — bearish crowding (everyone short, PCR high, negative momentum)
- `bilateral` — both sides crowded (high options activity on both calls and puts)

### Signal Bands

| Signal    | Score threshold |
|-----------|-----------------|
| EXTREME   | ≥ 70            |
| HIGH      | 50–69           |
| MEDIUM    | 30–49           |
| NEUTRAL   | < 30            |

## Watchlist

Uses the curated SI watchlist from `short_interest_scanner/ticker_watchlist.json`
(~157 unique tickers across all categories). Not the full 13F universe.

## CLI Usage

```bash
# Full daily run (writes to DB, prints summary)
python -m crowded_trades run

# JSON output (for programmatic use)
python -m crowded_trades run --json

# Pretty-printed signal list
python -m crowded_trades analyze signals

# Detailed single-ticker breakdown
python -m crowded_trades analyze ticker AAPL

# Sector-level aggregation
python -m crowded_trades analyze summary
```

## Cron Job

Scheduled via Hermes cron engine:
- **Name:** Crowded Trades Daily Analysis
- **Schedule:** `30 6 * * *` (6:30 AM UTC+10, after upstream scanners)
- **Script:** `run_crowded_trades_daily.py` (in `~/AppData/Local/hermes/scripts/`)
- **Delivery:** Discord channel "crowded"
- **Mode:** `no_agent` (script stdout delivered verbatim)

## Database Schema

Results are stored in `purrtfolio.db` → `crowded_trades` table:

| Column          | Type    | Description                          |
|-----------------|---------|--------------------------------------|
| ticker          | TEXT    | Ticker symbol                        |
| date            | DATE    | Analysis date (YYYY-MM-DD)           |
| crowdedness_score | REAL  | 0–100 crowdedness score              |
| signal          | TEXT    | EXTREME/HIGH/MEDIUM/NEUTRAL          |
| crowd_direction | TEXT    | long/short/bilateral                 |
| signal_details  | JSON    | Per-component breakdown              |
| created_at      | TIMESTAMP | Insert timestamp                    |
| short_crowd     | REAL    | Short interest component (0–40)      |
| options_crowd   | REAL    | Options flow component (0–30)        |
| iv_crowd        | REAL    | IV component (0–15)                  |
| momentum_crowd  | REAL    | Momentum component (0–15)            |
| pcr_crowd       | REAL    | Put/call ratio component (0–20)    |
| corr_crowd      | REAL    | Correlation component (0–20)         |

Plus `ingestion_log_crowded` — records each run's status, tickers scanned, signals found.

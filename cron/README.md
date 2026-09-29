# cron/ — Hermes job runners

Every scheduled job (ingestion, enrichment, snapshot, DB release, QA) runs
from a file in this folder. Hermes looks up each job's script by name in
`~/AppData/Local/hermes/scripts/`; those files are shims that run the file of
the same name here. Job logic is therefore versioned with the code it drives,
and changes to the repo never require editing Hermes.

| Hermes job | Runner |
|---|---|
| 13F Quarterly Ingestion | `quarterly_13f_pipeline.py` (Hermes script name: `quarterly_pipeline.sh`, a bash shim) |
| Daily Macro Market Update | `macro_market_update.py` |
| Short Interest Daily Ingestion | `run_short_interest_daily.py` |
| Sector Enrichment (Weekly) | `enrich_sectors_cron.py` |
| Economic Calendar Daily Ingestion | `run_economic_calendar_daily.py` |
| Form 4 Insider Trading Daily | `run_form4_insider_daily.py` |
| Price Momentum Daily Ingestion | `run_price_momentum_daily.py` |
| Correlation Matrix Daily Computation | `run_correlation_matrix_daily.py` |
| Audit/QA Bot Daily | `audit_qa_bot.py` |
| QA Fixer Daily | `qa_fixer.py` — reads the QA report, has Claude Code (`claude -p`, on the logged-in subscription) fix what it can, opens one `qa-fix` PR (never merges); works in `~/qa-fixer-work` |
| Put/Call Ratio Daily | `run_put_call_ratio_daily.py` |
| DB Release Auto-Publish | `publish_db_release.py` |
| News Sentiment Daily Ingestion | `run_news_sentiment_daily.py` |
| IV Rank Daily Ingestion | `run_iv_rank_daily.py` |
| Unusual Activity Daily Ingestion | `run_unusual_activity_daily.py` |
| Factor Exposure Weekly Enrichment | `enrich_factors_cron.py` |
| Trader Quotes Init | `run_trader_quotes_init.py` |
| Earnings Revision Momentum Daily | `run_earnings_revisions_daily.py` |
| Crowded Trades Daily Analysis | `run_crowded_trades_daily.py` |

Since 2026-09-30 the site focuses on strategy research, and every data-ingestion
and enrichment job above is **paused** in Hermes (the dashboards stay reachable by
URL with their last data). Still active: Daily Macro Market Update (it also pulls
this checkout), DB Release Auto-Publish (a no-op while data doesn't change),
Audit/QA Bot, and the two Cron Doctor jobs. Resume one with
`hermes cron resume <job_id>`; `hermes cron list` shows the ids.

## Installing the shims (one time)

From the checkout Hermes uses (`C:\Users\cho_i\13f-scanner-web`), after
pulling master:

```bash
python cron/install_hermes_shims.py           # dry run: lists what changes
python cron/install_hermes_shims.py --apply   # backs up originals, writes shims
python cron/install_hermes_shims.py --restore # undo
```

Originals are kept in `hermes/scripts/_pre_repo_backup/`.

## Conventions

- Paths are repo-relative (`REPO = Path(__file__).resolve().parents[1]`).
  Runners put the repo root on `sys.path` and import `scanners.<name>`, or run
  `python -m scanners.<name>...` with the repo root as the working directory.
  The DB is `PURRTFOLIO_DB` or `~/purrtfolio.db` (`scanners/common.py`).
- Hermes runs `.py` scripts with its own venv interpreter
  (`hermes-agent/venv`), which has the scanner dependencies (`apscheduler`,
  `nltk`, `edgartools`, ...). Run runners manually with that interpreter.
- Print a short `Status: ok|error` summary to stdout; it is delivered to
  Discord. Exit non-zero only for real failures.
- Adding a job: add a runner here, create the job in Hermes with the same
  script name, then re-run the installer to write its shim.

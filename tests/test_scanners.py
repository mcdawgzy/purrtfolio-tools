"""Scanner package + cron runner checks (no network, no real DB).

- every scanners.* module and cron/ runner imports from the repo root
- a fresh DB can be bootstrapped from the scanners' own schema functions, in
  any order (shared tables live in scanners/common.py)
"""
from __future__ import annotations

import os
import pkgutil
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Scanner deps live in requirements-scanners.txt; skip cleanly without them.
pytest.importorskip("apscheduler")
pytest.importorskip("httpx")


def _scanner_modules() -> list[str]:
    import scanners

    return sorted(m.name for m in pkgutil.walk_packages(scanners.__path__, "scanners.")
                  if not m.name.endswith("__main__"))


@pytest.mark.parametrize("module", _scanner_modules())
def test_scanner_module_imports(module):
    __import__(module)


@pytest.mark.parametrize("runner", sorted(p.name for p in (ROOT / "cron").glob("[a-z]*.py")))
def test_cron_runner_imports(runner, monkeypatch):
    monkeypatch.setattr(sys, "argv", [runner])
    runpy.run_path(str(ROOT / "cron" / runner), run_name="import_check")


BOOTSTRAP = """
import importlib, os, random, sqlite3
from scanners import common
db = os.environ["PURRTFOLIO_DB"]
steps = [
    lambda: common.ensure_shared_schema(common.connect(db)),
    lambda: importlib.import_module("scanners.thirteen_f.db_init").init_database(db).close(),
    lambda: importlib.import_module("scanners.short_interest_scanner.fix_unified_schema").create_unified_schema(),
    lambda: importlib.import_module("scanners.earnings_revisions.db").init_earnings_revisions(),
    lambda: importlib.import_module("scanners.form4_insider_trading.db").init_insider_schema(),
    lambda: importlib.import_module("scanners.trader_quotes.seed").run_once(),
] + [
    (lambda m=m: importlib.import_module(f"scanners.{m}.db").init_db())
    for m in ["correlation_matrix", "crowded_trades", "economic_calendar", "implied_volatility",
              "news_sentiment", "price_momentum", "put_call_ratio", "short_interest_scanner",
              "unusual_activity"]
]
random.Random(int(os.environ["ORDER_SEED"])).shuffle(steps)
for step in steps:
    step()
names = {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")}
print(",".join(sorted(names)))
"""

# Tables the API reads (ticker_factors is created by enrich_factors on first run)
EXPECTED = {
    "tickers", "sectors", "funds", "filings_13f", "holdings_13f", "holding_changes_13f",
    "short_interest", "ticker_short_meta", "economic_events", "price_history",
    "price_momentum_signals", "corr_matrices", "crowded_trades", "earnings_revision_momentum",
    "trader_quotes", "iv_rank", "unusual_activity", "news_headlines", "ticker_news_sentiment",
}


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_fresh_db_bootstrap_any_order(tmp_path, seed):
    env = {**os.environ, "PURRTFOLIO_DB": str(tmp_path / "fresh.db"), "ORDER_SEED": str(seed),
           "PYTHONIOENCODING": "utf-8"}
    env.pop("MOMENTUM_DB", None)
    r = subprocess.run([sys.executable, "-c", BOOTSTRAP], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    tables = set(r.stdout.strip().splitlines()[-1].split(","))
    assert EXPECTED <= tables, sorted(EXPECTED - tables)

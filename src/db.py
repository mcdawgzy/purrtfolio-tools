"""Compatibility shim — re-exports ONLY the names used outside src/.

The query layer now lives in src/queries/ (SQL per domain) and src/database.py
(connections). The DB release URL/tag lives in src/config.py.

External users (import this file as a top-level module named `db` after doing
sys.path.insert(0, '<repo>/src'), so no relative imports here):
  - trader-quotes cron script:          init_trader_quotes, get_trader_quote_categories
  - scanners/earnings_revisions/ingest.py: init_earnings_revisions
"""
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.queries.earnings import init_earnings_revisions  # noqa: E402
from src.queries.quotes import get_trader_quote_categories, init_trader_quotes  # noqa: E402

__all__ = ["init_trader_quotes", "get_trader_quote_categories", "init_earnings_revisions"]

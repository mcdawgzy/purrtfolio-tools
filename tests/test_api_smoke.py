"""Smoke test: every GET route of the app answers without a 5xx.

Needs a real purrtfolio.db (PURRTFOLIO_DB or ~/purrtfolio.db); skipped otherwise.
Run from the repo root:  python -m pytest tests -q
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

DB = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))

# Set before src.api is imported (route collection below): the scanner modules
# resolve their DB paths at import time. The slim momentum DB is downloaded on
# startup; keep it out of $HOME.
os.environ["PURRTFOLIO_DB"] = str(DB)
os.environ.setdefault("MOMENTUM_DB", str(Path(tempfile.mkdtemp()) / "momentum_data.db"))

pytestmark = pytest.mark.skipif(not DB.exists(), reason=f"no database at {DB}")

# Path params -> sample values; routes needing a query param get one here.
SAMPLES = {"cik": "0000102909", "ticker": "AAPL", "symbol": "AAPL", "series": "TOTAL",
           "date_str": "20260101", "pivot": "^GSPC"}
QUERY = {"/api/si/search": "?q=AA", "/api/insider/search": "?q=AA", "/api/momentum/search": "?q=AA"}


def _routes() -> list[str]:
    # Imports the app at collection time (no startup/DB access happens on import).
    from src.api import app

    api = [r.path for r in app.routes
           if "GET" in getattr(r, "methods", set()) and r.path.startswith("/api")]
    return api + ["/"]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.api import app

    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("route", _routes())
def test_route_does_not_error(client, route):
    path = re.sub(r"\{(\w+)\}", lambda m: SAMPLES[m.group(1)], route) + QUERY.get(route, "")
    r = client.get(path)
    assert r.status_code < 500, f"{path} -> {r.status_code}: {r.text[:300]}"


def test_errors_use_envelope(client):
    r = client.get("/api/funds/0000102909/holdings?sort_by=nope")
    assert r.status_code == 422
    assert set(r.json()) >= {"error", "status"}


def test_corr_pivot_rejects_injection(client):
    r = client.get("/api/correlation/pivot/x')%20OR%201=1--")
    assert r.status_code == 200 and r.json() == []


def test_factor_coverage_at_most_100(client):
    assert client.get("/api/factors/meta").json()["coverage_pct"] <= 100

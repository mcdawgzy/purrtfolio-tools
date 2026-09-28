"""Tests for the publishing catalogue (research/catalogue/studies/*.yaml).

Always run: the data validates, IDs are unique, the public feed is anonymised and
free of account details, and the rendered files are current.

Run only when a trading_hub checkout is importable (it is on the research machine,
not in CI): every strategy, mechanism, paper and pre-registration tested there has a
record here, and every referenced script exists. Point TRADING_HUB_ROOT at the
checkout if it is not the sibling ``../trading_hub``.

    py -3.14 -m pytest research/catalogue -q
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_catalogue import outputs  # noqa: E402
from catalogue import Visibility, load_studies, render_public_json  # noqa: E402

TRADING_HUB_ROOT = Path(os.environ.get(
    "TRADING_HUB_ROOT", Path(__file__).resolve().parents[3] / "trading_hub"))
try:
    if not (TRADING_HUB_ROOT / "src" / "trading_hub").is_dir():
        raise ImportError(str(TRADING_HUB_ROOT))
    sys.path.insert(0, str(TRADING_HUB_ROOT / "src"))
    from trading_hub.optimize.mechanisms import MECHANISM_OF, MECHANISMS
    from trading_hub.optimize.papers import PAPERS
    HAVE_HUB = True
except ImportError:
    MECHANISM_OF, MECHANISMS, PAPERS = {}, {}, {}
    HAVE_HUB = False

needs_hub = pytest.mark.skipif(not HAVE_HUB, reason=f"no trading_hub checkout at {TRADING_HUB_ROOT}")

UNCLASSIFIED = "unclassified"


@pytest.fixture(scope="module")
def studies():
    return load_studies()


def test_ids_and_slugs_are_unique(studies):
    for field in ("id", "slug"):
        dupes = [k for k, n in Counter(getattr(s, field) for s in studies).items() if n > 1]
        assert dupes == [], f"duplicate {field}s: {dupes}"


@needs_hub
def test_mechanisms_are_known(studies):
    unknown = {s.mechanism for s in studies} - set(MECHANISMS) - {UNCLASSIFIED}
    assert unknown == set()


@needs_hub
def test_every_mechanism_is_catalogued(studies):
    covered = {s.mechanism for s in studies}
    assert sorted(set(MECHANISMS) - covered) == []


@needs_hub
def test_every_built_strategy_is_catalogued(studies):
    covered = {name for s in studies for name in s.strategies}
    assert sorted(set(MECHANISM_OF) - covered) == []
    assert sorted(covered - set(MECHANISM_OF)) == []


@needs_hub
def test_strategy_mechanism_matches_the_ledger(studies):
    wrong = [
        (s.id, name) for s in studies for name in s.strategies
        if MECHANISM_OF[name] != s.mechanism
    ]
    assert wrong == []


@needs_hub
def test_every_paper_is_catalogued(studies):
    covered = {s.paper for s in studies if s.paper}
    assert covered <= set(PAPERS)
    assert sorted(set(PAPERS) - covered) == []


@needs_hub
def test_every_preregistration_is_catalogued(studies):
    on_disk = {
        p.relative_to(TRADING_HUB_ROOT).as_posix()
        for p in (TRADING_HUB_ROOT / "docs" / "prereg").glob("*.md")
    }
    referenced = {p for s in studies for p in s.refs.prereg}
    assert sorted(referenced - on_disk) == []
    assert sorted(on_disk - referenced) == []


@needs_hub
def test_referenced_scripts_exist(studies):
    missing = [
        (s.id, p) for s in studies for p in s.refs.scripts
        if not (TRADING_HUB_ROOT / p).exists()
    ]
    assert missing == []


def test_closed_is_not_before_tested(studies):
    bad = [s.id for s in studies if s.closed and s.closed < s.tested]
    assert bad == []


# Account numbers, credential names and live-book internals must never reach a
# page meant for the website.
_PRIVATE = re.compile(
    r"\b5\d{8}\b|MT5_(LOGIN|PASSWORD|SERVER)|\.env\b|TRADING_HUB_REAL_OK|"
    r"halt_book|checkpoints_live|risk_live\.yaml",
    re.IGNORECASE,
)


def test_publishable_text_has_no_account_details(studies):
    leaks = []
    for s in studies:
        if s.visibility is Visibility.PRIVATE:
            continue
        text = " ".join([
            s.title, s.headline, s.why, s.lesson or "", s.public_summary or "",
            s.data, *(v.result for v in s.variants),
        ])
        if _PRIVATE.search(text):
            leaks.append(s.id)
    assert leaks == []


# Social-media posters, vendors and their branded setup names are anonymised in
# the public feed (decision 2026-09-27); published papers keep their citations.
_IDENTIFYING = re.compile(
    r"edgeful|milkman|\bSaty\b|awtrades|AW Model|crackingmarkets|ravenquant|Daybreak|"
    r"MrMilk|Bilbo|Golden Gate|Purgatory|Bartkus|ForexFactory|aHbP0lXLZOs|"
    r"@[A-Za-z_]\w+|\br/\w+|\bu/\w+|x\.com/|youtube\.com|AlphaGroup",
    re.IGNORECASE,
)


def test_public_feed_is_anonymised(studies):
    payload = render_public_json(studies)
    assert _IDENTIFYING.findall(payload) == []


def test_public_json_holds_only_public_studies(studies):
    payload = json.loads(render_public_json(studies))
    public_ids = {s.id for s in studies if s.visibility is Visibility.PUBLIC}
    assert {row["id"] for row in payload} == public_ids
    assert all("refs" not in row for row in payload)


def test_rendered_files_are_current(studies):
    stale = [p.name for p, text in outputs().items()
             if not p.exists() or p.read_text(encoding="utf-8") != text]
    assert stale == [], "stale — run: py -3.14 research/catalogue/build_catalogue.py"

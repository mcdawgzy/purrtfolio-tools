"""Strategy catalogue — one structured record per tested study and its variants.

The research record (what was tested and why it failed) lives in the ``trading_hub``
backtesting repo: ``STRATEGY_LEDGER.md`` and ``optimize/mechanisms.py``. This module
holds the same history arranged for **publishing**: one :class:`Study` per thing
tested, with its variants, verdict, headline numbers and a plain-English summary.

Data: ``research/catalogue/studies/*.yaml`` (one file per :class:`Family`).
``build_catalogue.py`` renders ``STRATEGY_CATALOGUE.md`` (internal view, names every
source), ``public/studies.json`` (the anonymised website / X feed) and
``backtest-log.html``. ``test_catalogue.py`` checks the data, the anonymisation, and —
when a ``trading_hub`` checkout is available — that every tested strategy, mechanism,
paper and pre-registration there has a record here.
"""
from __future__ import annotations

import datetime as dt
import json
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Family",
    "Verdict",
    "Visibility",
    "SourceType",
    "Source",
    "Variant",
    "Refs",
    "Study",
    "CATALOGUE_DIR",
    "HERE",
    "load_studies",
    "render_markdown",
    "render_public_json",
]

HERE = Path(__file__).resolve().parent
CATALOGUE_DIR = HERE / "studies"


class Family(StrEnum):
    """Public-facing grouping — the order posts/pages are organised in."""

    ORB_MOMENTUM = "orb-momentum"
    ICT_SMC = "ict-smc"
    INTRADAY_MEAN_REVERSION = "intraday-mean-reversion"
    DIP_BUYING = "dip-buying"
    CALENDAR_EVENTS = "calendar-events"
    TREND_FOLLOWING = "trend-following"
    VOLUME_ORDER_FLOW = "volume-order-flow"
    OPTIONS = "options"
    FACTORS = "factors"
    CROSS_ASSET = "cross-asset"


FAMILY_TITLES: dict[Family, str] = {
    Family.ORB_MOMENTUM: "Opening range & intraday momentum",
    Family.ICT_SMC: "ICT / smart-money concepts (FVG, sweeps, SMT)",
    Family.INTRADAY_MEAN_REVERSION: "Intraday fades & mean reversion",
    Family.DIP_BUYING: "Daily dip-buying & short-term reversal",
    Family.CALENDAR_EVENTS: "Calendar, session & event effects",
    Family.TREND_FOLLOWING: "Trend following & moving averages",
    Family.VOLUME_ORDER_FLOW: "Volume, breadth & order flow",
    Family.OPTIONS: "Options structures & premium selling",
    Family.FACTORS: "Factors & cross-sectional stock selection",
    Family.CROSS_ASSET: "Pairs, carry & cross-asset state",
}


class Verdict(StrEnum):
    PASS = "PASS"
    CANDIDATE = "CANDIDATE"
    FORWARD_FAILED = "FORWARD_FAILED"
    SHELVED = "SHELVED"
    LEAD = "LEAD"
    NEAR_MISS = "NEAR_MISS"
    PARKED = "PARKED"
    REJECT = "REJECT"
    NOT_TESTED = "NOT_TESTED"
    EXAMPLE = "EXAMPLE"
    PENDING = "PENDING"


VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.PASS: "✅ Passed the full gate",
    Verdict.CANDIDATE: "🟡 Hard gate passed, robustness marginal",
    Verdict.FORWARD_FAILED: "❌ Passed the gate, failed the forward test",
    Verdict.SHELVED: "⏸️ Passed, then shelved",
    Verdict.LEAD: "🔎 Open lead, not validated",
    Verdict.NEAR_MISS: "🟠 Real but underpowered",
    Verdict.PARKED: "⏸️ Parked",
    Verdict.REJECT: "❌ Rejected",
    Verdict.NOT_TESTED: "⚪ Not tested",
    Verdict.EXAMPLE: "📘 Worked example only",
    Verdict.PENDING: "⏳ Built, not yet run",
}


class Visibility(StrEnum):
    PUBLIC = "public"
    """Safe to publish as written."""
    REVIEW = "review"
    """The user decides — a surviving edge, or tied to the real-money account."""
    PRIVATE = "private"
    """The user's own system or journal — never published."""


class SourceType(StrEnum):
    PAPER = "paper"
    VENDOR = "vendor"
    SOCIAL = "social"
    USER = "user"
    INTERNAL = "internal"


_ANONYMISED_SOURCES = frozenset({SourceType.SOCIAL, SourceType.VENDOR, SourceType.USER})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_Model):
    type: SourceType
    name: str
    url: str | None = None


class Variant(_Model):
    name: str
    verdict: Verdict
    result: str


class Refs(_Model):
    ledger: str | None = None
    prereg: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    prs: tuple[int, ...] = ()


class Study(_Model):
    id: str = Field(pattern=r"^S\d{3}$")
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str
    public_title: str | None = None
    """Title for the public feed when ``title`` names a person, vendor or account."""
    family: Family
    mechanism: str
    source: Source
    public_source: str | None = None
    """Anonymised source label for the public feed (required for social / vendor /
    user sources — the public feed never names individuals, vendors or accounts)."""
    paper: str | None = Field(default=None, pattern=r"^P\d{3}$")
    strategies: tuple[str, ...] = ()
    instruments: tuple[str, ...]
    products: tuple[str, ...]
    timeframe: str
    data: str
    tested: dt.date
    closed: dt.date | None = None
    verdict: Verdict
    headline: str
    why: str
    lesson: str | None = None
    variants: tuple[Variant, ...] = ()
    refs: Refs = Refs()
    visibility: Visibility
    public_summary: str | None = None

    @model_validator(mode="after")
    def _summary_when_publishable(self) -> Study:
        if self.visibility is not Visibility.PRIVATE and not self.public_summary:
            raise ValueError(f"{self.id}: a {self.visibility} study needs a public_summary")
        if (self.visibility is Visibility.PUBLIC and self.public_source is None
                and self.source.type in _ANONYMISED_SOURCES):
            raise ValueError(f"{self.id}: a public {self.source.type} study needs a public_source")
        return self


def load_studies(directory: Path = CATALOGUE_DIR) -> list[Study]:
    """Load every study, sorted by id."""
    studies: list[Study] = []
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
        for item in raw:
            studies.append(Study.model_validate(item))
    return sorted(studies, key=lambda s: s.id)


# ── Rendering ────────────────────────────────────────────────────────────────

def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render_markdown(studies: list[Study]) -> str:
    """The full human view — every study, grouped by family."""
    by_family: dict[Family, list[Study]] = {f: [] for f in Family}
    for s in studies:
        by_family[s.family].append(s)
    n_variants = sum(len(s.variants) for s in studies)
    counts: dict[Verdict, int] = {}
    for s in studies:
        counts[s.verdict] = counts.get(s.verdict, 0) + 1

    out: list[str] = [
        "# Strategy Catalogue",
        "",
        "<!-- GENERATED by research/catalogue/build_catalogue.py from studies/*.yaml"
        " — edit the YAML, not this file. -->",
        "",
        "One record per tested study, grouped by strategy family, for publishing. The"
        " research record behind each one is `STRATEGY_LEDGER.md` and"
        " `src/trading_hub/optimize/mechanisms.py` in the trading_hub repo.",
        "",
        f"**{len(studies)} studies, {n_variants} named variants.**",
        "",
        "| Verdict | Studies |",
        "|---|---|",
    ]
    for v in Verdict:
        if counts.get(v):
            out.append(f"| {VERDICT_LABELS[v]} | {counts[v]} |")
    out += [
        "",
        "Visibility: `public` = safe to publish as written; `review` = your call (a"
        " surviving edge, or tied to the real-money account); `private` = your own"
        " system or journal, never published.",
        "",
        "## Index",
        "",
        "| ID | Study | Family | Source | Verdict | Visibility |",
        "|---|---|---|---|---|---|",
    ]
    for s in studies:
        out.append(
            f"| [{s.id}](#{s.id.lower()}) | {_cell(s.title)} | {s.family.value} | "
            f"{s.source.type.value} | {VERDICT_LABELS[s.verdict]} | {s.visibility.value} |"
        )
    for fam in Family:
        group = by_family[fam]
        if not group:
            continue
        out += ["", f"## {FAMILY_TITLES[fam]}", ""]
        for s in group:
            out += [
                f"### {s.id}",
                "",
                f"**{s.title}** — {VERDICT_LABELS[s.verdict]} · `{s.visibility.value}`",
                "",
                f"- **Source:** {s.source.type.value} — {s.source.name}"
                + (f" ({s.source.url})" if s.source.url else "")
                + (f" · paper {s.paper}" if s.paper else ""),
                f"- **Tested:** {s.tested.isoformat()}"
                + (f" → closed {s.closed.isoformat()}" if s.closed else "")
                + f" · {', '.join(s.instruments)} · {', '.join(s.products)} · {s.timeframe}",
                f"- **Data:** {s.data}",
                f"- **Mechanism:** `{s.mechanism}`"
                + (f" · strategies: {', '.join(f'`{x}`' for x in s.strategies)}"
                   if s.strategies else ""),
                f"- **Headline:** {' '.join(s.headline.split())}",
                f"- **Why:** {' '.join(s.why.split())}",
            ]
            if s.lesson:
                out.append(f"- **Lesson:** {' '.join(s.lesson.split())}")
            if s.variants:
                out += ["", "| Variant | Verdict | Result |", "|---|---|---|"]
                for v in s.variants:
                    out.append(f"| {_cell(v.name)} | {v.verdict.value} | {_cell(v.result)} |")
            refs = []
            if s.refs.prereg:
                refs.append("pre-reg " + ", ".join(f"`{p}`" for p in s.refs.prereg))
            if s.refs.scripts:
                refs.append("scripts " + ", ".join(f"`{p}`" for p in s.refs.scripts))
            if s.refs.prs:
                refs.append("PRs " + ", ".join(f"#{n}" for n in s.refs.prs))
            if s.refs.ledger:
                refs.append(f"ledger: {s.refs.ledger}")
            if refs:
                out += ["", "_Refs: " + "; ".join(refs) + "_"]
            if s.public_summary:
                out += ["", f"> {' '.join(s.public_summary.split())}"]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_public_json(studies: list[Study]) -> str:
    """The website / X feed: public studies only, internal refs stripped."""
    public = []
    for s in studies:
        if s.visibility is not Visibility.PUBLIC:
            continue
        public.append({
            "id": s.id,
            "slug": s.slug,
            "title": s.public_title or s.title,
            "family": s.family.value,
            "family_title": FAMILY_TITLES[s.family],
            "source_type": s.source.type.value,
            "source": s.public_source or s.source.name,
            "source_url": None if s.source.type in _ANONYMISED_SOURCES else s.source.url,
            "paper": s.paper,
            "instruments": list(s.instruments),
            "products": list(s.products),
            "timeframe": s.timeframe,
            "data": " ".join(s.data.split()),
            "tested": s.tested.isoformat(),
            "verdict": s.verdict.value,
            "verdict_label": VERDICT_LABELS[s.verdict],
            "headline": " ".join(s.headline.split()),
            "why": " ".join(s.why.split()),
            "lesson": " ".join(s.lesson.split()) if s.lesson else None,
            "summary": " ".join((s.public_summary or "").split()),
            "variants": [
                {"name": v.name, "verdict": v.verdict.value,
                 "result": " ".join(v.result.split())}
                for v in s.variants
            ],
        })
    return json.dumps(public, indent=2, ensure_ascii=False) + "\n"

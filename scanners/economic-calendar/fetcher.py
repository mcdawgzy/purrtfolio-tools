"""Data fetcher for the Economic Calendar scanner.

Sources (all free):
  1. FOMC meeting schedule — scraped from federalreserve.gov HTML
  2. US economic releases (CPI, PPI, NFP, etc.) — Finnhub free API
     (optional; falls back to curated static list in config.py)
  3. ECB / BOE / BOJ rate decisions — scraped from central bank websites
     (with curated static fallback in config.py)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import urllib.request
import urllib.error
from typing import Any
from zoneinfo import ZoneInfo

from config import (
    HTTP_HEADERS,
    FINNHUB_API_KEY,
    HIGH_IMPACT_US_EVENTS_2026,
    ECB_RATE_DATES_2026,
    BOE_RATE_DATES_2026,
    BOJ_RATE_DATES_2026,
    IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW,
    UPCOMING_DAYS,
)

logger = logging.getLogger("econ-cal-fetcher")

# ── Helpers ────────────────────────────────────────────────

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_RE = "|".join(MONTHS.keys())


def _http_get(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL with browser-like headers. Returns text or None on error."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"HTTP GET failed for {url}: {e}")
        return None


def _parse_date_range(text: str) -> tuple[int, int, int] | None:
    """Parse 'Month DD-DD' or 'Month DD' from text. Returns (month, start_day, end_day)."""
    # Range: "September 16-17"
    m = re.search(
        rf"({MONTH_RE})\s+(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})",
        text, re.IGNORECASE,
    )
    if m:
        month = MONTHS.get(m.group(1).lower())
        if month:
            return month, int(m.group(2)), int(m.group(3))
    # Single day: "September 16"
    m = re.search(rf"({MONTH_RE})\s+(\d{{1,2}})", text, re.IGNORECASE)
    if m:
        month = MONTHS.get(m.group(1).lower())
        if month:
            return month, int(m.group(2)), int(m.group(2))
    return None


def _to_utc(date_str: str, time_str: str, tz_name: str) -> tuple[str, str]:
    """Convert a local date+time+tz to UTC. Returns (utc_date_str, utc_time_str)."""
    if not time_str:
        time_str = "12:00"
    if not tz_name:
        tz_name = "America/New_York"
    try:
        tz = ZoneInfo(tz_name)
        parts = date_str.split("-")  # YYYY-MM-DD
        local_dt = dt.datetime(
            int(parts[0]), int(parts[1]), int(parts[2]),
            int(time_str.split(":")[0]), int(time_str.split(":")[1]),
            tzinfo=tz,
        )
        utc_dt = local_dt.astimezone(dt.timezone.utc)
        return utc_dt.strftime("%Y-%m-%d"), utc_dt.strftime("%H:%M")
    except Exception:
        # Fallback: just return the date as-is
        return date_str, time_str


# ── FOMC ──────────────────────────────────────────────────

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHLY_PATTERN = re.compile(
    rf"({MONTH_RE})\s+(\d{{1,2}})",
    re.IGNORECASE,
)


def fetch_fomc_meetings() -> list[dict[str, Any]]:
    """Scrape FOMC meeting dates from the Fed's calendar page.

    Returns a list of event dicts with keys:
      event_name, event_date, event_time, category, impact, timezone_id, source, url
    """
    html = _http_get(FOMC_URL)
    if not html:
        logger.warning("FOMC page fetch failed — no FOMC events added")
        return []

    # The page has year-section headers like "<h3>2026 FOMC Meetings</h3>"
    # followed by meeting entries with dates like "January 27-28"
    events: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    this_year = dt.datetime.now().year

    # Split HTML by year-section headers
    # Pattern: year followed by "FOMC Meetings"
    year_section_re = re.compile(
        r"<(?:h[23]|>)\s*[^>]*?(20\d{2})\s+FOMC\s+Meetings",
        re.IGNORECASE,
    )
    year_matches = list(year_section_re.finditer(html))

    if not year_matches:
        # Fallback: look for any standalone year header
        year_matches = list(re.finditer(r">\s*(20\d{2})\s+FOMC", html, re.IGNORECASE))

    for i, m in enumerate(year_matches):
        year = int(m.group(1))
        if year < this_year:
            continue
        start_pos = m.end()
        end_pos = year_matches[i + 1].start() if i + 1 < len(year_matches) else len(html)
        year_html = html[start_pos:end_pos]

        # FOMC meetings are always date ranges: "January 27-28", "March 17-18*"
        # The regex requires a dash between two numeric days.
        # We deliberately do NOT match single-day patterns like "Released February 18"
        for m in re.finditer(
            rf"({MONTH_RE})\s+(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})",
            year_html, re.IGNORECASE,
        ):
            month_str = m.group(1).lower()
            end_day = int(m.group(3))  # use the end (decision) day
            month = MONTHS.get(month_str)
            if not month or end_day < 1 or end_day > 31:
                continue

            # Validate the date is real
            try:
                dt.datetime(year, month, end_day)
            except ValueError:
                continue

            # Use the last day of the range as the decision/meeting day
            # FOMC meetings that produce a statement typically end with a
            # press conference on the final day
            decision_date = f"{year:04d}-{month:02d}-{end_day:02d}"
            if decision_date in seen_dates:
                continue
            seen_dates.add(decision_date)

            # Determine if this is likely an "important" meeting
            # (statement + press conference, usually every other meeting)
            # We mark all as high impact; the frontend can filter later
            utc_date, utc_time = _to_utc(
                decision_date, "14:00", "America/New_York"
            )

            events.append({
                "event_name": "FOMC Rate Decision",
                "event_date": utc_date,
                "event_time": utc_time,
                "category": "FOMC",
                "impact": IMPACT_HIGH,
                "actual": None,
                "prior": None,
                "forecast": None,
                "timezone_id": "America/New_York",
                "source": "FOMC",
                "url": FOMC_URL,
            })

    logger.info(f"FOMC: scraped {len(events)} upcoming meetings")
    return events


# ── Finnhub (optional, for US economic releases) ──────────

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"

# Finnhub event-name patterns we care about (case-insensitive substring match)
# Maps Finnhub event → (display_name, category)
FINNHUB_EVENT_MAP = {
    "nonfarm payroll": ("US Non-Farm Payrolls", "US Economics"),
    "non-farm payroll": ("US Non-Farm Payrolls", "US Economics"),
    "employment change": ("US Non-Farm Payrolls", "US Economics"),
    "cpi": ("US CPI (MoM)", "US Economics"),
    "consumer price index": ("US CPI (MoM)", "US Economics"),
    "ppi": ("US PPI (MoM)", "US Economics"),
    "producer price index": ("US PPI (MoM)", "US Economics"),
    "gdp": ("US GDP (QoQ)", "US Economics"),
    "gdp growth rate": ("US GDP (QoQ)", "US Economics"),
    "personal consumption": ("US PCE Deflator (MoM)", "US Economics"),
    "retail sales": ("US Retail Sales (MoM)", "US Economics"),
    "pmi": ("US PMI", "US Economics"),
    "ism non-manufacturing": ("US ISM Services PMI", "US Economics"),
    "ism manufacturing": ("US ISM Mfg PMI", "US Economics"),
    "consumer confidence": ("US Consumer Confidence", "US Economics"),
    "jolts": ("US Job Openings (JOLTS)", "US Economics"),
    "factory orders": ("US Factory Orders (MoM)", "US Economics"),
    "durables": ("US Durable Goods (MoM)", "US Economics"),
    "initial jobless": ("US Initial Jobless Claims", "US Economics"),
    "continue jobless": ("US Continuing Jobless Claims", "US Economics"),
    "fed funds": ("US Fed Funds Rate", "FOMC"),
    "fomc minutes": ("FOMC Minutes", "FOMC"),
    "federal funds target": ("US Fed Funds Rate", "FOMC"),
}

# Keywords to filter (only US, high impact)
_US_ECON_KEYWORDS = [
    "nonfarm", "non-farm", "payroll", "cpi", "consumer price",
    "ppi", "producer price", "gdp", "retail sales", "pmi",
    "employment", "unemployment", "confidence", "initial jobless",
    "continuing jobless", "factory orders", "durables",
    "ism", "jolts", "fed funds", "fomc minutes", "federal funds",
    "core cpi", "core pce", "existing home", "new home",
    "building permits", "housing starts", "vehicle sales",
    "trade balance", "current account",
]


def fetch_finnhub_events(
    days_ahead: int = 60,
) -> list[dict[str, Any]]:
    """Fetch upcoming US economic releases from Finnhub (free tier).

    Requires FINNHUB_API_KEY (free signup at finnhub.io).
    Falls back gracefully if key is absent or request fails.
    """
    if not FINNHUB_API_KEY:
        logger.info("Finnhub key not set — skipping API; using curated fallback")
        return _finnhub_fallback_events(days_ahead)

    now = dt.datetime.now(dt.timezone.utc)
    from_date = now.strftime("%Y-%m-%d")
    to_date = (now + dt.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    url = f"{FINNHUB_URL}?from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"

    text = _http_get(url, timeout=20)
    if not text:
        logger.warning("Finnhub fetch failed — using curated fallback")
        return _finnhub_fallback_events(days_ahead)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Finnhub returned non-JSON — using curated fallback")
        return _finnhub_fallback_events(days_ahead)

    calendar = data.get("economicCalendar", [])
    if not calendar:
        logger.info("Finnhub returned empty calendar — using curated fallback")
        return _finnhub_fallback_events(days_ahead)

    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in calendar:
        if item.get("country") != "US":
            continue
        # Finnhub impact: low/medium/high (or 1/2/3)
        impact_raw = str(item.get("impact", "")).lower().strip()
        if "low" in impact_raw:
            continue  # skip low-impact for the calendar tab

        event_name_raw = item.get("event", "").lower()
        # Match against our keyword map
        matched_name = None
        category = "US Economics"
        for kw, (mapped_name, mapped_cat) in FINNHUB_EVENT_MAP.items():
            if kw in event_name_raw:
                matched_name = mapped_name
                category = mapped_cat
                break
        if not matched_name:
            # Generic match for any of our keywords
            if not any(kw in event_name_raw for kw in _US_ECON_KEYWORDS):
                continue
            matched_name = item.get("event", "")
            category = "US Economics"

        time_str = item.get("time", "")
        if " " in time_str:
            # "YYYY-MM-DD HH:MM:SS" (UTC)
            date_part = time_str.split(" ")[0]
            time_part = ":".join(time_str.split(" ")[1].split(":")[0:2])
        else:
            date_part = time_str
            time_part = "08:30"  # default US econ release time in ET

        key = (date_part, matched_name)
        if key in seen:
            continue
        seen.add(key)

        # Map impact
        if "high" in impact_raw:
            impact = IMPACT_HIGH
        elif "medium" in impact_raw or "moderate" in impact_raw:
            impact = IMPACT_MEDIUM
        else:
            impact = IMPACT_HIGH  # default to high for NFP/CPI/PPI

        events.append({
            "event_name": matched_name,
            "event_date": date_part,
            "event_time": time_part,
            "category": category,
            "impact": impact,
            "actual": item.get("actual"),
            "prior": item.get("previous"),
            "forecast": item.get("forecast"),
            "timezone_id": "America/New_York",
            "source": "Finnhub",
            "url": None,
        })

    logger.info(f"Finnhub: {len(events)} US econ events fetched")
    return events


def _finnhub_fallback_events(days_ahead: int = 60) -> list[dict[str, Any]]:
    """Curated static list of high-impact US events (from config.py).

    Used when Finnhub API key is unavailable.
    """
    now = dt.datetime.now()
    cutoff = now + dt.timedelta(days=days_ahead)
    events: list[dict[str, Any]] = []

    for name, month, day, time_et in HIGH_IMPACT_US_EVENTS_2026:
        year = now.year
        try:
            event_dt = dt.datetime(year, month, day)
        except ValueError:
            continue
        now_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if event_dt < now_date or event_dt > cutoff:
            continue
        try:
            utc_date, utc_time = _to_utc(
                f"{year:04d}-{month:02d}-{day:02d}",
                time_et,
                "America/New_York",
            )
        except ValueError:
            continue

        events.append({
            "event_name": name,
            "event_date": utc_date,
            "event_time": utc_time,
            "category": "US Economics",
            "impact": IMPACT_HIGH,
            "actual": None,
            "prior": None,
            "forecast": None,
            "timezone_id": "America/New_York",
            "source": "curated",
            "url": None,
        })

    logger.info(f"Curated fallback: {len(events)} upcoming US econ events")
    return events


# ── ECB ───────────────────────────────────────────────────

ECB_URL = "https://www.ecb.europa.eu/press/calendars/html/mgcgc2025.en.html"

# Fallback ECB dates from config (used when scraping fails)
def _ecb_fallback_events() -> list[dict[str, Any]]:
    now = dt.datetime.now()
    events: list[dict[str, Any]] = []
    for name, month, day in ECB_RATE_DATES_2026:
        year = now.year
        event_dt = dt.datetime(year, month, day)
        if event_dt < now:
            continue
        utc_date, utc_time = _to_utc(
            f"{year:04d}-{month:02d}-{day:02d}", "14:15", "Europe/Berlin"
        )
        events.append({
            "event_name": name,
            "event_date": utc_date,
            "event_time": utc_time,
            "category": "ECB",
            "impact": IMPACT_HIGH,
            "actual": None,
            "prior": None,
            "forecast": None,
            "timezone_id": "Europe/Berlin",
            "source": "ECB",
            "url": ECB_URL,
        })
    return events


def fetch_ecb_events() -> list[dict[str, Any]]:
    """Try scraping ECB rate decision dates; fall back to curated list."""
    html = _http_get(ECB_URL)
    if html:
        # Look for date patterns in the HTML
        text = re.sub(r"<[^>]+>", " ", html)
        # Find year markers
        year_matches = [(int(m.group(1)), m.start()) for m in re.finditer(r"\b(20\d{2})\b", text)]
        events: list[dict[str, Any]] = []
        this_year = dt.datetime.now().year

        for i, (year, pos) in enumerate(year_matches):
            if year < this_year:
                continue
            end = year_matches[i + 1][1] if i + 1 < len(year_matches) else len(text)
            year_text = text[pos:end]
            # Parse "Day Month" or "Month Day" patterns
            for m in re.finditer(rf"(\d{{1,2}})\s+({MONTH_RE})", year_text, re.IGNORECASE):
                day = int(m.group(1))
                month = MONTHS.get(m.group(2).lower())
                if month:
                    try:
                        event_dt = dt.datetime(year, month, day, 14, 15)
                    except ValueError:
                        continue
                    if event_dt < dt.datetime.now():
                        continue
                    utc_date, utc_time = _to_utc(
                        f"{year:04d}-{month:02d}-{day:02d}", "14:15", "Europe/Berlin"
                    )
                    events.append({
                        "event_name": "ECB Rate Decision",
                        "event_date": utc_date,
                        "event_time": utc_time,
                        "category": "ECB",
                        "impact": IMPACT_HIGH,
                        "actual": None,
                        "prior": None,
                        "forecast": None,
                        "timezone_id": "Europe/Berlin",
                        "source": "ECB",
                        "url": ECB_URL,
                    })
            if events:
                break
        if events:
            logger.info(f"ECB: scraped {len(events)} rate decisions")
            return events

    logger.info("ECB: scraping failed, using curated fallback")
    return _ecb_fallback_events()


# ── BOE ───────────────────────────────────────────────────

BOE_URL = "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates"


def fetch_boe_events() -> list[dict[str, Any]]:
    """Try scraping BOE MPC dates; fall back to curated list."""
    html = _http_get(BOE_URL)
    if html:
        text = re.sub(r"<[^>]+>", " ", html)
        # Parse date patterns
        events: list[dict[str, Any]] = []
        this_year = dt.datetime.now().year

        # Look for patterns like "8 February 2026" or "February 8, 2026"
        for m in re.finditer(
            rf"(\d{{1,2}})\s+({MONTH_RE})\s+(20\d{{2}})",
            text, re.IGNORECASE,
        ):
            day = int(m.group(1))
            month = MONTHS.get(m.group(2).lower())
            year = int(m.group(3))
            if not month:
                continue
            try:
                event_dt = dt.datetime(year, month, day, 12, 0)
            except ValueError:
                continue
            if event_dt < dt.datetime.now():
                continue
            utc_date, utc_time = _to_utc(
                f"{year:04d}-{month:02d}-{day:02d}", "12:00", "Europe/London"
            )
            events.append({
                "event_name": "BOE Rate Decision",
                "event_date": utc_date,
                "event_time": utc_time,
                "category": "BOE",
                "impact": IMPACT_HIGH,
                "actual": None,
                "prior": None,
                "forecast": None,
                "timezone_id": "Europe/London",
                "source": "BOE",
                "url": BOE_URL,
            })
        if events:
            logger.info(f"BOE: scraped {len(events)} MPC decisions")
            return events

    logger.info("BOE: scraping failed, using curated fallback")
    events: list[dict[str, Any]] = []
    now = dt.datetime.now()
    for name, month, day in BOE_RATE_DATES_2026:
        year = now.year
        try:
            event_dt = dt.datetime(year, month, day)
        except ValueError:
            continue
        if event_dt < now:
            continue
        utc_date, utc_time = _to_utc(
            f"{year:04d}-{month:02d}-{day:02d}", "12:00", "Europe/London"
        )
        events.append({
            "event_name": name,
            "event_date": utc_date,
            "event_time": utc_time,
            "category": "BOE",
            "impact": IMPACT_HIGH,
            "actual": None,
            "prior": None,
            "forecast": None,
            "timezone_id": "Europe/London",
            "source": "BOE",
            "url": BOE_URL,
        })
    return events


# ── BOJ ───────────────────────────────────────────────────

BOJ_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"


def fetch_boj_events() -> list[dict[str, Any]]:
    """BOJ schedule page is JS-rendered (unparseable). Use curated fallback."""
    events: list[dict[str, Any]] = []
    now = dt.datetime.now()
    for name, month, day in BOJ_RATE_DATES_2026:
        year = now.year
        try:
            event_dt = dt.datetime(year, month, day)
        except ValueError:
            continue
        if event_dt < now:
            continue
        utc_date, utc_time = _to_utc(
            f"{year:04d}-{month:02d}-{day:02d}", "11:00", "Asia/Tokyo"
        )
        events.append({
            "event_name": name,
            "event_date": utc_date,
            "event_time": utc_time,
            "category": "BOJ",
            "impact": IMPACT_HIGH,
            "actual": None,
            "prior": None,
            "forecast": None,
            "timezone_id": "Asia/Tokyo",
            "source": "BOJ",
            "url": BOJ_URL,
        })
    return events


# ── Master fetch ──────────────────────────────────────────

def fetch_all_events() -> list[dict[str, Any]]:
    """Fetch events from all sources. Returns a deduplicated list."""
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()  # (date, name, category)

    for fetcher in [fetch_fomc_meetings, fetch_finnhub_events,
                    fetch_ecb_events, fetch_boe_events, fetch_boj_events]:
        try:
            fetched = fetcher()
            for ev in fetched:
                key = (ev["event_date"], ev["event_name"], ev["category"])
                if key not in seen:
                    seen.add(key)
                    events.append(ev)
        except Exception as e:
            logger.warning(f"Fetcher {fetcher.__name__} failed: {e}")

    # Sort by date
    events.sort(key=lambda e: (e["event_date"], e["event_time"] or "00:00"))
    logger.info(f"Total events fetched: {len(events)}")
    return events

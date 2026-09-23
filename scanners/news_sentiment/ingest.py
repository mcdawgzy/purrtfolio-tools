"""
Data ingestion pipeline for News Sentiment Scanner.

Fetches financial news from free RSS feeds, matches headlines to
curated tickers, scores sentiment (VADER + financial lexicon), and
stores results in the unified purrtfolio.db.

Usage:
  asyncio.run(ingest_latest())         # fetch latest from all feeds
  asyncio.run(ingest_date(target_date))  # fetch for a specific date
"""
import asyncio
import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional, Set

import httpx
from xml.etree import ElementTree
from email.utils import parsedate_to_datetime

from .config import (
    DB_PATH, RSS_FEEDS, HTTP_HEADERS, MAX_HEADLINES_PER_FEED,
    MAX_HEADLINE_AGE_HOURS, BULLISH_THRESHOLD, BEARISH_THRESHOLD,
    MIN_HEADLINES_FOR_AGGREGATE, TICKER_HISTORY_DAYS,
)
from .db import get_db, init_db
from .sentiment import score_headline

logger = logging.getLogger(__name__)


def load_watchlist() -> List[str]:
    """Load tickers from the short-interest watchlist JSON.

    Falls back to a built-in list if the file is missing.
    """
    import json
    from pathlib import Path

    watchlist_path = (
        Path(__file__).parent.parent / "short_interest_scanner" / "ticker_watchlist.json"
    )
    if watchlist_path.exists():
        with open(watchlist_path) as f:
            wl = json.load(f)
        return sorted(set(wl.get("all_tickers", [])))

    # Fallback — a compact curated list
    return [
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
        "BRK.B", "JPM", "V", "JNJ", "WMT", "MA", "UNH", "HD", "DIS",
        "BAC", "XOM", "AVGO", "ADBE", "INTC", "CRM", "NFLX", "PFE",
        "SPY", "QQQ", "IWM", "VTI", "GLD", "SLV", "BTC-USD", "ETH-USD",
    ]


def _build_ticker_regex(tickers: List[str]):
    """Build regex patterns for matching tickers in headlines.

    Returns a tuple ``(bare_regex, format_pattern, ticker_set)`` where:
      * bare_regex — matches 4+ char tickers as standalone words (high precision;
        avoids false positives like 'ON' in 'drops on a Yosemite fire').
      * format_pattern — matches tickers inside $TICKER, (TICKER) or [TICKER]
        wrappers (validated against *ticker_set*).
      * ticker_set — the raw set for O(1) lookup.
    """
    ticker_set = set(tickers)

    # Bare-word matching only for tickers with 4+ chars (and no dots,
    # since a '.' breaks \b matching for 'BRK.B')
    bare_list = sorted(
        [t for t in tickers if len(t) >= 4 and '.' not in t],
        key=len, reverse=True,
    )
    bare_regex = re.compile(
        r'\b(' + '|'.join(re.escape(t) for t in bare_list) + r')\b'
    ) if bare_list else None

    # Format-based: $TICKER, (TICKER), [TICKER]
    format_pattern = re.compile(
        r'\$([A-Z]{1,5}(?:\.[A-Z])?)'   # $AAPL, $BRK.B
        r'|\(([^)]+)\)'                  # (LMT)
        r'|\[([^\]]+)\]'                # [NVDA]
    )
    return bare_regex, format_pattern, ticker_set


def match_tickers(text: str, patterns) -> List[str]:
    """Extract all tickers mentioned in *text* (deduplicated, uppercased).

    Uses two strategies:
      1. Bare-word matching — 4+ char tickers only (avoids false positives
         like standalone 'ON', 'C', 'LOW').
      2. Format-based matching — any ticker inside $TICKER, (TICKER) or
         [TICKER], validated against the known watchlist.
    """
    text_upper = text.upper()
    bare_regex, format_pattern, ticker_set = patterns
    matches = set()

    # 1. Bare word matching (4+ char tickers)
    if bare_regex:
        for m in bare_regex.finditer(text_upper):
            matches.add(m.group(1))

    # 2. Format-based matching — validate captured text against ticker set
    for m in format_pattern.finditer(text_upper):
        for group in m.groups():
            if group and group.strip() in ticker_set:
                matches.add(group.strip())

    return sorted(matches)


# ── Company-name matching ───────────────────────────────────────────

# Common suffixes to strip from company names before matching
_NAME_SUFFIXES = re.compile(
    r'\s*(?:INC\.?|CORPORATION|CORP\.?|CO\.?|LLC|LTD\.?|LIMITED|'
    r'HOLDINGS?|COMPANIES|COMPANY|GROUP|TRUST|ETF|FUND|'
    r'CAPITAL|PARTNERS|MANAGEMENT|TECHNOLOGIES|SYSTEMS|'
    r'SERVICES?|PRODUCTS?|ENTERPRISES|CORP|PLC|NV|SA|AG)$'
    r', re.IGNORECASE,'
)

# Ticker → common abbreviation overrides (manual curation for well-known names)
_ABBREVIATIONS: Dict[str, List[str]] = {
    "JNJ": ["J&J", "Johnson"],
    "BAC": ["BofA", "Bank of America"],
    "HD":  ["Home Depot"],
    "LOW": ["Lowe\'s", "Lowes"],
    "SBUX": ["Starbucks"],
    "MCD":  ["McDonald", "McDonald\'s"],
    "KO":   ["Coca-Cola", "Coke"],
    "PEP":  ["Pepsi", "PepsiCo"],
    "DIS":  ["Disney", "Walt Disney"],
    "WMT":  ["Walmart", "Wal-Mart"],
    "TGT":  ["Target Corporation", "Target Corp"],  # exclude bare "Target" (false positives)
    "TSLA": ["Tesla"],
    "GM":   ["General Motors"],
    "F":    ["Ford"],
    "CAT":  ["Caterpillar"],
    "BA":   ["Boeing"],
    "MMM":  ["3M", "Minnesota Mining"],
    "ABT":  ["Abbott"],
    "ACN":  ["Accenture"],
    "ADS":  ["Altria", "Philip Morris"],
    "SYY":  ["Sysco"],
    "HSY":  ["Hershey"],
    "KHC":  ["Kraft Heinz", "Kraft"],
    "K":    ["Kellogg", "Kellog"],
    "LUV":  ["Southwest Airlines", "Southwest"],
    "DAL":  ["Delta Air"],
    "UAL":  ["United Airlines", "United"],
    "LMT":  ["Lockheed Martin", "Lockheed"],
    "NEE":  ["NextEra Energy", "NextEra"],
    "DUK":  ["Duke Energy", "Duke"],
    "SO":   ["Southern Co", "Southern Company"],
    "NGG":  ["National Grid"],
    "TOT":  ["TotalEnergies", "Total"],
    "CVS":  ["CVS Health", "CVS"],
    "CI":   ["Cigna"],
    "EL":   ["Estee Lauder", "Est\u00e9e"],
    "T":    ["AT&T", "AT and T"],
    "TMUS": ["T-Mobile", "TMobile"],
    "CMCSA":["Comcast", "NBCUniversal", "NBC"],
    "CHTR": ["Charter Communications", "Charter"],
    "ORCL": ["Oracle"],
    "IBM":  ["IBM", "International Business Machines"],
    "HPQ":  ["HP", "Hewlett Packard"],
    "CSCO": ["Cisco", "Cisco Systems"],
    "INTC": ["Intel"],
    "AMD":  ["AMD"],
    "NVDA": ["NVIDIA", "Nvidia"],
    "META": ["Meta", "Facebook", "Meta Platforms"],
    "AMZN": ["Amazon", "Amazon.com"],
    "GOOGL": ["Google", "Alphabet", "Alphabet Inc"],
    "GOOG":  ["Google", "Alphabet"],
    "MSFT": ["Microsoft", "MSFT"],
    "AAPL": ["Apple"],
    "AVGO": ["Broadcom", "AVGO"],
    "ADBE": ["Adobe"],
    "CRM":  ["Salesforce"],
    "NFLX": ["Netflix"],
    "ASML": ["ASML"],
    "QCOM": ["Qualcomm"],
    "TXN":  ["Texas Instruments", "TI"],
    "MU":   ["Micron"],
    "AMAT": ["Applied Materials"],
    "LRCX": ["Lam Research"],
    "KLAC": ["KLA"],
    "MRVL": ["Marvell"],
    "ON":   ["onsemi", "ON Semiconductor"],
    "ADI":  ["Analog Devices"],
    "SWKS": ["Skyworks"],
    "QRVO": ["Qorvo"],
    "V":    ["Visa"],
    "MA":   ["Mastercard", "Master Card"],
    "PYPL": ["PayPal", "Pay Pal"],
    "NOW":  ["ServiceNow", "Service Now"],
    "SHOP": ["Shopify"],
    "OKTA": ["Okta"],
    "FTNT": ["Fortinet"],
    "DOCU": ["DocuSign"],
    "ZOOM": ["Zoom Video"],
    "PLTR": ["Palantir"],
    "SNOW": ["Snowflake"],
    "RIVN": ["Rivian"],
    "LCID": ["Lucid"],
    "NIO":  ["NIO", "NIO Inc"],
    "XPEV": ["Xpeng", "Xpeng Motors"],
    "LI":   ["Li Auto", "Li Motors"],
    "BABA": ["Alibaba", "Alibaba Group"],
    "JD":   ["JD.com", "Jingdong"],
    "PDD":  ["Pinduoduo", "PDD"],
    "BIDU": ["Baidu"],
    "NTES": ["NetEase"],
    "TME":  ["Tencent Music", "TME"],
    "BILI": ["Bilibili", "Bilibili"],
    "TTM":  ["Tata Motors"],
    "MRNA": ["Moderna"],
    "BNTX": ["BioNTech"],
    "NVAX": ["Novavax"],
    "VRTX": ["Vertex"],
    "REGN": ["Regeneron"],
    "BIIB": ["Biogen"],
    "ALNY": ["Alnylam"],
    "IONS": ["Ionis"],
    "SRPT": ["Sarepta"],
    "CRSP": ["CRISPR"],
    "BEAM": ["Beam Therapeutics"],
    "PACB": ["Pacific Biosciences"],
    "TWST": ["Twist Bioscience", "Twist"],
    "GILD": ["Gilead"],
    "VEEV": ["Veeva"],
    "HLF":  ["Herbalife"],
    "SNDL": ["Sundial"],
    "TLRY": ["Tilray"],
    "PLUG": ["Plug Power"],
    "FCEL": ["FuelCell"],
    "BLNK": ["Blink"],
    "CHPT": ["ChargePoint"],
    "RIDE": ["Lordstown"],
    "WKHS": ["Workhorse"],
    "GME":  ["GameStop"],
    "AMC":  ["AMC Entertainment", "AMC"],
    "BB":   ["BlackBerry"],
    "NOK":  ["Nokia"],
    "KOSS": ["Koss"],
    "NAKD": ["Naked Brand"],
    "BBBY": ["Bed Bath & Beyond", "Bed Bath"],
    "SPY":  ["S&P 500", "Spyder", "SPDR S&P 500"],
    "QQQ":  ["Nasdaq 100", "Invesco QQQ"],
    "IWM":  ["Russell 2000", "iShares Russell"],
    "VTI":  ["Total Stock Market", "Vanguard Total"],
    "GLD":  ["Gold Spot", "SPDR Gold"],
    "SLV":  ["Silver Trust", "iShares Silver"],
    "USO":  ["USOil", "United States Oil"],
    "XLE":  ["Energy Select Sector", "XLE"],
    "XLF":  ["Financial Select Sector"],
    "XLK":  ["Technology Select Sector"],
    "XLV":  ["Health Care Select Sector"],
    "XLI":  ["Industrials Select Sector"],
    "AGG":  ["Aggregate Bond", "iShares Core U.S. Aggregate"],
    "TLT":  ["Long-Term Treasury", "iShares 20+ Year"],
    "DIA":  ["Dow Jones", "Dow Industrial Average"],
}


def load_company_name_map(tickers: List[str]) -> List[tuple]:
    """Build a list of (search_term, ticker) pairs from the tickers table.

    For each watchlist ticker, resolve the company name from the DB and
    generate search terms: full name (suffix-stripped), first word, and
    curated abbreviations.
    """
    name_pairs: List[tuple] = []
    seen_pairs: set = set()

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"SELECT ticker, name FROM tickers WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()

        for row in rows:
            ticker = row["ticker"]
            name = (row["name"] or "").strip()
            if not name:
                continue

            stripped = _NAME_SUFFIXES.sub("", name).strip().rstrip(",").strip()
            terms: List[str] = []

            # Full stripped company name — use only if multi-word (avoids
            # single-word false positives like "Target", "Wells")
            words = stripped.split()
            if len(words) >= 2 and len(stripped) >= 6:
                terms.append(stripped)
                # Also try first-two-words for partial headline matches
                if len(words) >= 3:
                    terms.append(" ".join(words[:2]))
            elif len(words) == 1:
                # Single-word names like "Apple", "Microsoft" are handled
                # by the curated _ABBREVIATIONS dict below
                pass
            # Curated abbreviations — covers single-word company names
            terms.extend(_ABBREVIATIONS.get(ticker, []))

            for term in terms:
                term_clean = term.strip()
                if len(term_clean) >= 3 and (term_clean, ticker) not in seen_pairs:
                    seen_pairs.add((term_clean, ticker))
                    name_pairs.append((term_clean, ticker))
    except sqlite3.Error as e:
        logger.error(f"Error loading company names from DB: {e}")
    finally:
        if conn:
            conn.close()

    return name_pairs


def match_company_names(text: str, name_pairs: List[tuple]) -> List[str]:
    """Extract tickers by matching company names in *text*.

    *name_pairs* is a list of (search_term, ticker) from
    :func:`load_company_name_map`.
    """
    matches: List[str] = []
    text_lower = text.lower()
    for search_term, ticker in name_pairs:
        if re.search(r'\b' + re.escape(search_term.lower()) + r'\b', text_lower):
            matches.append(ticker)
    return sorted(set(matches))


def fetch_feed(url: str, max_items: int = MAX_HEADLINES_PER_FEED) -> List[Dict[str, Any]]:
    """Fetch and parse an RSS/Atom feed using httpx + stdlib XML.

    Handles both RSS 2.0 (``<item>``) and Atom (``{http://www.w3.org/2005/Atom}entry``)
    formats.  Returns a list of entry dicts with: ``title``, ``link``, ``published``.
    No third-party feed-parsing library required.
    """
    entries: List[Dict[str, Any]] = []
    _ATOM_NS = "http://www.w3.org/2005/Atom"

    try:
        resp = httpx.get(url, timeout=30, headers=HTTP_HEADERS, follow_redirects=True)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)

        # Detect format
        items = root.findall(".//item")  # RSS 2.0
        is_atom = False
        if not items:
            items = root.findall(f".//{{{_ATOM_NS}}}entry")  # Atom
            is_atom = True
            if not items:  # try generic <entry>
                items = root.findall(".//entry")

        for item in items[:max_items]:
            title = ""
            link = ""
            published: Optional[datetime] = None

            if is_atom:
                t = item.find(f"{{{_ATOM_NS}}}title")
                ln = item.find(f"{{{_ATOM_NS}}}link")
                up = item.find(f"{{{_ATOM_NS}}}updated") or item.find(f"{{{_ATOM_NS}}}published")
                if t is not None and t.text:
                    title = t.text.strip()
                if ln is not None:
                    link = ln.get("href", "") or (ln.text or "").strip()
                date_str = up.text.strip() if up is not None and up.text else ""
            else:
                t = item.find("title")
                ln = item.find("link")
                pd = item.find("pubDate") or item.find("dc:date")
                if t is not None and t.text:
                    title = t.text.strip()
                if ln is not None and ln.text:
                    link = ln.text.strip()
                date_str = pd.text.strip() if pd is not None and pd.text else ""

            if not title:
                continue

            if date_str:
                try:
                    if is_atom:
                        published = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    else:
                        published = parsedate_to_datetime(date_str)
                    # Normalise to naive datetime (strip tzinfo for consistent comparison)
                    if published and published.tzinfo is not None:
                        published = published.replace(tzinfo=None)
                except Exception:
                    published = datetime.now()
            else:
                published = datetime.now()

            entries.append({
                "title": title,
                "link": link,
                "published": published,
            })

        logger.info(f"Fetched {len(entries)} entries from {url}")
    except Exception as e:
        logger.error(f"Error fetching feed {url}: {e}")

    return entries


def _headline_id(source: str, url: str, published: Optional[datetime]) -> str:
    """Generate a stable ID for a headline (for deduplication)."""
    raw = f"{source}:{url}:{published.isoformat() if published else ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def ingest_date(target_date: date, tickers: List[str]) -> Dict[str, Any]:
    """Ingest headlines from all feeds for a given date.

    Since RSS feeds are live streams (not date-filtered), we fetch the
    latest entries from each feed and filter to those published on or
    near `target_date`.  In practice, this fetches whatever is fresh.
    """
    init_db()
    ticker_patterns = _build_ticker_regex(tickers)
    name_pairs = load_company_name_map(tickers)
    cutoff = datetime.now() - timedelta(hours=MAX_HEADLINE_AGE_HOURS)

    log_id: Optional[int] = None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ingestion_log_news (started_at, status) VALUES (CURRENT_TIMESTAMP, 'started')"
        )
        log_id = cursor.lastrowid
        conn.commit()

    urls_checked = 0
    headlines_found = 0

    all_headlines: List[Dict[str, Any]] = []

    for feed_cfg in RSS_FEEDS:
        urls_checked += 1
        source_name = feed_cfg["name"]
        entries = fetch_feed(feed_cfg["url"], MAX_HEADLINES_PER_FEED)

        for entry in entries:
            title = entry["title"]
            link = entry["link"]
            published = entry["published"]

            # Skip if too old
            if published and published < cutoff:
                continue

            # Skip if we already have this headline (dedup by ID)
            hid = _headline_id(source_name, link, published)

            # Score sentiment
            result = score_headline(title)
            compound = result["compound"]
            label = result["label"]

            # Match tickers (symbol-format + company-name matching)
            ticker_match = match_tickers(title, ticker_patterns)
            name_match = match_company_names(title, name_pairs)
            mentioned = sorted(set(ticker_match) | set(name_match))

            all_headlines.append({
                "id": hid,
                "source": source_name,
                "title": title,
                "url": link,
                "published_at": published.isoformat() if published else None,
                "sentiment_score": compound,
                "sentiment_label": label,
                "tickers_mentioned": ",".join(mentioned) if mentioned else "",
            })
            headlines_found += 1

    # Store in DB
    stored = 0
    with get_db() as conn:
        cursor = conn.cursor()
        for h in all_headlines:
            cursor.execute("""
                INSERT OR IGNORE INTO news_headlines
                    (id, source, title, url, published_at,
                     sentiment_score, sentiment_label, tickers_mentioned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                h["id"], h["source"], h["title"], h["url"], h["published_at"],
                h["sentiment_score"], h["sentiment_label"], h["tickers_mentioned"],
            ))
            stored += cursor.rowcount

        # Recompute daily aggregations for today
        agg_count = _rebuild_daily_aggregates(conn, tickers)

        cursor.execute(
            "UPDATE ingestion_log_news SET status='completed', urls_checked=?, "
            "headlines_found=?, headlines_stored=?, completed_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (urls_checked, headlines_found, stored, log_id),
        )
        conn.commit()

    return {
        "status": "completed",
        "date": str(target_date),
        "urls_checked": urls_checked,
        "headlines_found": headlines_found,
        "headlines_stored": stored,
        "aggregated_tickers": agg_count,
    }


def _rebuild_daily_aggregates(
    conn: sqlite3.Connection,
    tickers: List[str],
) -> int:
    """Rebuild the ticker_news_sentiment table for the latest date.

    For each ticker in the watchlist, compute the daily aggregate:
    - headline_count, avg_sentiment, bullish/bearish/neutral counts
    """
    today = date.today().isoformat()
    # Build per-ticker aggregates from today's headlines
    ticker_scores: Dict[str, List[float]] = {}
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sentiment_score, sentiment_label, tickers_mentioned
        FROM news_headlines
        WHERE date(datetime(retrieved_at, 'localtime')) = ?
    """, (today,))

    for row in cursor.fetchall():
        score = row[0]
        label = row[1]
        tickers_str = row[2] or ""
        if not tickers_str:
            continue
        for ticker in tickers_str.split(","):
            ticker = ticker.strip()
            if ticker:
                ticker_scores.setdefault(ticker, []).append((score, label))

    count = 0
    for ticker, entries in ticker_scores.items():
        if len(entries) < MIN_HEADLINES_FOR_AGGREGATE:
            continue

        scores = [e[0] for e in entries if e[0] is not None]
        labels = [e[1] for e in entries]
        if not scores:
            continue

        avg_sent = sum(scores) / len(scores)
        bullish = sum(1 for l in labels if l == "bullish")
        bearish = sum(1 for l in labels if l == "bearish")
        neutral = sum(1 for l in labels if l == "neutral")

        cursor.execute("""
            INSERT OR REPLACE INTO ticker_news_sentiment
                (ticker, date, headline_count, avg_sentiment,
                 bullish_count, bearish_count, neutral_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, today, len(entries), round(avg_sent, 4),
            bullish, bearish, neutral,
        ))
        count += 1

    return count


async def ingest_latest() -> Dict[str, Any]:
    """Fetch latest headlines from all RSS feeds and store in DB."""
    tickers = load_watchlist()
    today = date.today()
    return ingest_date(today, tickers)


async def ingest_date_async(target_date: date) -> Dict[str, Any]:
    """Async wrapper for ingest_date (kept for API compatibility)."""
    return ingest_date(target_date, load_watchlist())

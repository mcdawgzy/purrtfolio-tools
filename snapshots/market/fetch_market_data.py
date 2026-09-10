#!/usr/bin/env python3
"""
Fetch market data for curated 24-ticker watchlist and generate narrative drivers.

Output: output/market_report_YYYYMMDD.json
"""

import json
import os
import random
from datetime import datetime, timedelta

import yfinance as yf


# ─── Curated Watchlist (24 tickers, 7 sections) ───────────────────────────
WATCHLIST = {
    "US Equities": [
        ("S&P 500",       "^GSPC"),
        ("Nasdaq 100",    "^NDX"),
        ("Russell 2000",  "^RUT"),
    ],
    "Global Equities": [
        ("Nikkei 225",    "^N225"),
        ("DAX",           "^GDAXI"),
        ("FTSE 100",      "^FTSE"),
    ],
    "US Rates": [
        ("2Y Yield",      "^IRX"),
        ("5Y Yield",      "^FVX"),
        ("10Y Yield",     "^TNX"),
        ("30Y Yield",     "^TYX"),
    ],
    "FX": [
        ("Dollar Index",  "DX-Y.NYB"),
        ("USD/JPY",       "USDJPY=X"),
        ("EUR/USD",       "EURUSD=X"),
        ("AUD/USD",       "AUDUSD=X"),
    ],
    "Commodities": [
        ("Gold",          "GC=F"),
        ("Silver",        "SI=F"),
        ("Crude Oil",     "CL=F"),
        ("Copper",        "HG=F"),
    ],
    "Internals & Credit": [
        ("VIX",           "^VIX"),
        ("HY Credit",     "HYG"),
        ("IG Credit",     "LQD"),
        ("5Y5Y Breakeven", "TIP"),
    ],
    "Crypto": [
        ("Bitcoin",       "BTC-USD"),
        ("Ethereum",      "ETH-USD"),
    ],
}


# ─── Narrative Engine ─────────────────────────────────────────────────────
# Catalysts keyed by category + direction. Top 5 movers use 3-clause sentences
# with cross-asset context; rest get 1-liners.

CATALYSTS = {
    "US Equities": {
        "up": [
            ("strong earnings from mega-cap tech", "with breadth broadening beyond the Magnificent Seven", "as the Russell 2000's rally confirmed market-wide strength"),
            ("risk-on positioning", "as soft-landing optimism grew", "with cyclical sectors leading the move higher"),
            ("AI-driven momentum and easing inflation fears", "with the buy-the-dip crowd re-emerging", "as futures signal continued strength into the close"),
        ],
        "down": [
            ("hawkish Fed minutes and growth concerns", "with defensives outperforming cyclicals", "as Treasury yields jumped and weigh on multiples"),
            ("rising recession fears", "with breadth deteriorating sharply", "as small caps led the move lower"),
            ("profit-taking after recent highs", "with bond yields climbing in tandem", "as the VIX spiked on risk-off flows"),
        ],
    },
    "Global Equities": {
        "up": [
            ("yen weakness supporting exporter earnings", "as BoJ policy uncertainty persists", "with foreign buyers returning to Tokyo"),
            ("weaker euro boosting DAX exporters", "as ECB rate cut bets firm up", "with the auto sector leading gains"),
            ("energy and mining sector strength", "as commodity prices rebound", "with the pound's slide aiding multinationals"),
        ],
        "down": [
            ("stronger yen repatriation flows", "as BoJ signals further tightening", "with exporters leading the decline"),
            ("energy sector weakness and ECB hawkishness", "as bund yields rise", "with industrials dragging the index lower"),
            ("stronger pound weighing on multinationals", "as energy and miners sold off", "with defensives providing only modest support"),
        ],
    },
    "US Rates": {
        "up": [
            ("sticky inflation prints and resilient economic data", "as traders pare Fed cut bets", "with the curve steepening on long-end selling"),
            ("hawkish Fed communication", "as QT concerns resurface", "with term premium rebuilding across the curve"),
        ],
        "down": [
            ("cooling inflation and rising unemployment claims", "as Fed cut bets rebuild", "with the curve bull-steepening as the front end rallies harder"),
            ("safe-haven flows and risk-off sentiment", "as growth concerns intensify", "with the long end outperforming on flight-to-quality bids"),
            ("dovish Fed speak and softer economic data", "as recession fears resurface", "with the 2s10s steepening modestly"),
        ],
    },
    "FX": {
        "dxy_up": [
            ("safe-haven demand and stronger US data", "as Fed cut bets ease", "with EUR and JPY selling off in tandem"),
            ("rising Treasury yields", "as US exceptionalism narrative strengthens", "with risk currencies underperforming"),
        ],
        "dxy_down": [
            ("softer US data and rising Fed cut expectations", "as risk-on flows return", "with EUR and commodity currencies rallying"),
            ("trade tensions and weaker yields", "as global growth concerns resurface", "with the dollar giving back recent gains"),
        ],
        "usdjpy_up": [
            ("BoJ caution and Fed hawkishness", "as rate differential widens", "with carry trades attracting flows"),
            ("strong US yields and risk appetite", "as Japanese intervention fears fade", "with the pair testing key resistance"),
        ],
        "usdjpy_down": [
            ("BoJ intervention threats and hawkish hints", "as carry trades unwind", "with exporters repatriating overseas earnings"),
            ("safe-haven yen demand and risk-off flows", "as global growth fears resurface", "with the pair breaking key support"),
        ],
        "eur_up": [
            ("stronger eurozone data and ECB hawkishness", "as rate cut bets ease", "with peripheral spreads tightening"),
        ],
        "eur_down": [
            ("dovish ECB and weaker eurozone data", "as rate cut bets firm", "with periphery spreads widening modestly"),
        ],
        "aud_up": [
            ("stronger China data and risk-on sentiment", "as commodity demand outlook improves", "with iron ore prices supporting"),
        ],
        "aud_down": [
            ("China growth concerns and risk-off flows", "as commodity prices weaken", "with iron ore dragging the pair lower"),
        ],
    },
    "Commodities": {
        "Gold_up": [
            ("weaker dollar and rising Fed cut expectations", "as central bank buying continues", "with safe-haven demand adding support"),
            ("geopolitical risk premium and inflation hedge demand", "as real yields fall", "with ETF inflows accelerating"),
        ],
        "Gold_down": [
            ("stronger dollar and rising real yields", "as risk appetite reduces safe-haven demand", "with ETF outflows resuming"),
        ],
        "Silver_up": [
            ("gold's strength and industrial demand pickup", "as solar panel demand improves", "with the gold-silver ratio compressing"),
        ],
        "Silver_down": [
            ("stronger dollar and weaker industrial demand", "as the gold-silver ratio widens", "with industrial metals dragging silver lower"),
        ],
        "Crude_up": [
            ("OPEC+ supply discipline and stronger demand outlook", "as inventories draw faster than expected", "with risk premium returning to the market"),
            ("Middle East tensions and supply disruption fears", "as US stockpiles decline", "with refiners ramping up ahead of driving season"),
        ],
        "Crude_down": [
            ("demand concerns and OPEC+ production uncertainty", "as inventories build", "with refiners pulling back on maintenance"),
            ("stronger dollar and recession fears", "as speculative longs unwind", "with WTI breaking key technical support"),
        ],
        "Copper_up": [
            ("China stimulus hopes and supply concerns", "as Dr. Copper signals global growth optimism", "with mine disruptions adding to tightness"),
        ],
        "Copper_down": [
            ("China growth concerns and stronger dollar", "as industrial demand outlook weakens", "with inventories building at major warehouses"),
        ],
    },
    "Internals & Credit": {
        "vix_up": [
            ("risk-off flows and hedge demand", "as equity selloff accelerates", "with realized vol rising across the curve"),
            ("macro uncertainty and dealer gamma positioning", "as put demand spikes", "with the VVIX also lifting"),
        ],
        "vix_down": [
            ("risk-on flows and complacency", "as buy-the-dip orders absorb supply", "with realized vol normalizing"),
            ("stable macro backdrop and earnings calm", "as call selling caps upside", "with the term structure flattening"),
        ],
        "hy_up": [
            ("risk-on sentiment and strong demand for yield", "as credit conditions ease", "with default expectations falling"),
        ],
        "hy_down": [
            ("risk-off flows and widening credit concerns", "as recession fears grow", "with defaults ticking higher"),
        ],
        "ig_up": [
            ("flight-to-quality and rate volatility", "as safe-haven demand lifts Treasuries", "with IG spreads tightening to long-term tights"),
        ],
        "ig_down": [
            ("credit spread widening and risk-off flows", "as growth concerns mount", "with defensive demand returning"),
        ],
    },
    "Crypto": {
        "up": [
            ("ETF inflows and institutional adoption", "as risk appetite returns to digital assets", "with ETH/BTC ratio also lifting on rotation"),
            ("dovish Fed expectations and dollar weakness", "as risk-on flows return", "with leverage in futures turning long"),
        ],
        "down": [
            ("stronger dollar and risk-off sentiment", "as leveraged longs unwind", "with funding rates turning negative"),
            ("regulatory concerns and profit-taking", "as ETF outflows resume", "with altcoins underperforming on rotation"),
        ],
    },
}


# ─── 1-liner fallbacks for Tier 2 ─────────────────────────────────────────
ONE_LINERS = {
    "US Equities": {
        "up": "S&P {dir} on {pct}% as risk appetite returned to Wall Street.",
        "down": "S&P {dir} on {pct}% as growth concerns pressured valuations.",
    },
    "Global Equities": {
        "up": "{name} {dir} on {pct}% tracking broader global risk-on sentiment.",
        "down": "{name} {dir} on {pct}% as risk-off flows hit global equities.",
    },
    "US Rates": {
        "up": "{name} {dir} on {pct}% as inflation expectations re-anchored higher.",
        "down": "{name} {dir} on {pct}% as Fed cut expectations rebuilt.",
    },
    "FX": {
        "up": "Dollar {dir} on {pct}% as US yields and safe-haven demand supported.",
        "down": "Dollar {dir} on {pct}% as risk-on flows weighed on the greenback.",
    },
    "Commodities": {
        "up": "{name} {dir} on {pct}% on supply concerns and broader commodity strength.",
        "down": "{name} {dir} on {pct}% on demand concerns and stronger dollar.",
    },
    "Internals & Credit": {
        "up": "VIX {dir} on {pct}% as risk-off flows lifted volatility demand.",
        "down": "VIX {dir} on {pct}% as risk appetite returned to markets.",
    },
    "Crypto": {
        "up": "{name} {dir} on {pct}% as risk appetite returned to digital assets.",
        "down": "{name} {dir} on {pct}% as risk-off flows pressured crypto markets.",
    },
}


def make_sentence(name: str, direction_word: str, abs_pct: float, catalyst_tuple: tuple) -> str:
    """Build 3-clause Tier 1 sentence: 'Name moved X% on [start], [middle], [end].'"""
    start, middle, end = catalyst_tuple
    # Lowercase mid-sentence clauses if they start with a capital
    if middle and middle[0].isupper():
        middle = middle[0].lower() + middle[1:]
    if end and end[0].isupper():
        end = end[0].lower() + end[1:]
    # Note: start is expected WITHOUT leading "on" (the sentence already prepends it)
    return f"{name} {direction_word} {abs_pct:.1f}% on {start}, {middle}, {end}."


def get_direction(pct: float) -> tuple:
    """Return (arrow, word, abs_color)."""
    if pct is None:
        return ("▬", "flat", 0)
    if abs(pct) < 0.05:
        return ("▬", "held flat at", abs(pct))
    if pct > 0:
        return ("▲", "rallied", pct)
    return ("▼", "fell", abs(pct))


def select_catalyst(category: str, name: str, pct: float) -> tuple:
    """Pick a catalyst tuple for a ticker based on category, direction, and ticker overrides."""
    if pct is None or abs(pct) < 0.05:
        return None  # flat, use special handling

    direction = "up" if pct > 0 else "down"

    # FX category has sub-categories
    if category == "FX":
        if "Dollar" in name:
            key = "dxy_up" if pct > 0 else "dxy_down"
        elif "USD/JPY" in name or "USDJPY" in name:
            key = "usdjpy_up" if pct > 0 else "usdjpy_down"
        elif "EUR" in name:
            key = "eur_up" if pct > 0 else "eur_down"
        elif "AUD" in name:
            key = "aud_up" if pct > 0 else "aud_down"
        else:
            key = direction
    elif category == "Commodities":
        if "Gold" in name:
            key = "Gold_up" if pct > 0 else "Gold_down"
        elif "Silver" in name:
            key = "Silver_up" if pct > 0 else "Silver_down"
        elif "Crude" in name or "Oil" in name:
            key = "Crude_up" if pct > 0 else "Crude_down"
        elif "Copper" in name:
            key = "Copper_up" if pct > 0 else "Copper_down"
        else:
            key = direction
    elif category == "Internals & Credit":
        if name == "VIX":
            key = "vix_up" if pct > 0 else "vix_down"
        elif "HY" in name:
            key = "hy_up" if pct > 0 else "hy_down"
        elif "IG" in name:
            key = "ig_up" if pct > 0 else "ig_down"
        else:
            key = direction
    else:
        key = direction

    options = CATALYSTS.get(category, {}).get(key, [])
    if not options:
        return None
    # Deterministic-ish selection: hash of name + date so each run is fresh but consistent
    seed_str = f"{name}-{datetime.now().strftime('%Y%m%d')}-{key}"
    rng = random.Random(hash(seed_str) % (2**32))
    return rng.choice(options)


def make_one_liner(name: str, category: str, pct: float) -> str:
    """Generate a short 1-liner for Tier 2 (non-top-mover) tickers."""
    if pct is None or abs(pct) < 0.05:
        return f"{name} held flat as markets awaited catalysts."
    direction = "up" if pct > 0 else "down"
    word = "rose" if pct > 0 else "fell"
    return f"{name} {word} {abs(pct):.1f}% on broader market {direction}move"


# ─── Data Fetching ────────────────────────────────────────────────────────
def fetch_ticker_data(name: str, symbol: str) -> dict:
    """Fetch current price and 24h change for a single ticker."""
    try:
        ticker = yf.Ticker(symbol)
        # Use 5-day hourly history to reliably get 24h-ago comparison
        hist = ticker.history(period="5d", interval="1h", prepost=True)
        if hist.empty or len(hist) < 2:
            return None
        current = float(hist["Close"].iloc[-1])
        # 24h ago: try ~24 bars back
        ref_idx = max(0, len(hist) - 25)
        ref = float(hist["Close"].iloc[ref_idx])
        pct = ((current - ref) / ref) * 100 if ref else 0
        return {
            "name": name,
            "symbol": symbol,
            "price": current,
            "ref_price": ref,
            "pct_change": pct,
        }
    except Exception as e:
        print(f"  [skip] {name} ({symbol}): {e}")
        return None


def fetch_all() -> list:
    """Fetch data for entire watchlist."""
    results = []
    print(f"Fetching {sum(len(v) for v in WATCHLIST.values())} tickers...")
    for category, tickers in WATCHLIST.items():
        for name, symbol in tickers:
            data = fetch_ticker_data(name, symbol)
            if data:
                data["category"] = category
                results.append(data)
    print(f"  Got {len(results)} tickers")
    return results


# ─── Report Assembly ──────────────────────────────────────────────────────
def build_report() -> dict:
    """Fetch all data, generate narratives, return report dict."""
    raw = fetch_all()
    if not raw:
        raise RuntimeError("No data fetched")

    # Identify top 5 movers (excluding VIX where up = bad; rank by abs %)
    ranked = sorted(raw, key=lambda x: abs(x.get("pct_change", 0)), reverse=True)
    top5_names = {r["name"] for r in ranked[:5]}

    rows = []
    for category in WATCHLIST.keys():
        rows.append({"type": "section", "name": category})
        cat_tickers = [r for r in raw if r["category"] == category]
        # Preserve watchlist order within each section
        for name, _ in WATCHLIST[category]:
            for t in cat_tickers:
                if t["name"] == name:
                    pct = t["pct_change"]
                    arrow, dir_word, abs_pct = get_direction(pct)
                    level_move = f"{t['price']:,.2f} ({arrow}{abs_pct:.1f}%)"
                    is_top = name in top5_names

                    if is_top and abs(pct) >= 0.05:
                        # Tier 1: 3-clause sentence
                        catalyst = select_catalyst(category, name, pct)
                        if catalyst:
                            driver = make_sentence(name, dir_word, abs(pct), catalyst)
                        else:
                            driver = make_one_liner(name, category, pct)
                    else:
                        # Tier 2: 1-liner
                        driver = make_one_liner(name, category, pct)

                    rows.append({
                        "type": "row",
                        "name": name,
                        "level_move": level_move,
                        "pct_change": pct,
                        "driver": driver,
                        "category": category,
                        "is_top": is_top,
                    })
                    break

    report = {
        "timestamp": datetime.now().isoformat(),
        "date_str": datetime.now().strftime("%Y%m%d"),
        "rows": rows,
    }
    return report


def save_report(report: dict, output_dir: str = "output") -> str:
    os.makedirs(output_dir, exist_ok=True)
    date_str = report["date_str"]
    path = os.path.join(output_dir, f"market_report_{date_str}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved: {path}")
    return path


if __name__ == "__main__":
    report = build_report()
    save_report(report)

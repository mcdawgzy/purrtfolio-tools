#!/usr/bin/env python3
"""
Macro Market Update Data Fetcher - Curated Edition
Fetches 24h changes for a focused set of macro indicators with fresh daily narratives.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import requests
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

# ─── CURATED TICKER LIST (~32 tickers, focused but comprehensive) ──────────────────────
# Each entry: (display_name, yfinance_symbol, category, tier)
# tier=1: top movers get 2-3 sentence narratives; tier=2: 1-liner
CURATED_TICKERS = [
    # === US EQUITIES (4) ===
    ("S&P 500", "^GSPC", "US Equities", 1),
    ("Nasdaq 100", "^NDX", "US Equities", 1),
    ("Dow Jones", "^DJI", "US Equities", 2),
    ("Russell 2000", "^RUT", "US Equities", 2),

    # === GLOBAL EQUITIES (5) ===
    ("Nikkei 225", "^N225", "Global Equities", 1),
    ("DAX", "^GDAXI", "Global Equities", 1),
    ("FTSE 100", "^FTSE", "Global Equities", 2),
    ("STOXX 600", "^STOXX", "Global Equities", 2),
    ("Hang Seng", "^HSI", "Global Equities", 2),

    # === US RATES (4) ===
    ("US 2Y Yield", "^IRX", "US Rates", 1),      # 13W T-bill proxy for policy
    ("US 5Y Yield", "^FVX", "US Rates", 1),      # Belly - rate hike expectations
    ("US 10Y Yield", "^TNX", "US Rates", 1),     # Benchmark - growth/inflation
    ("US 30Y Yield", "^TYX", "US Rates", 2),     # Long end - term premium

    # === FX (7) ===
    ("DXY", "DX-Y.NYB", "FX", 1),                # Dollar index (cash)
    ("USD/JPY", "USDJPY=X", "FX", 1),            # Carry/risk proxy, BoJ policy
    ("EUR/USD", "EURUSD=X", "FX", 1),            # Major pair
    ("GBP/USD", "GBPUSD=X", "FX", 2),            # Cable - BoE policy
    ("AUD/USD", "AUDUSD=X", "FX", 2),            # China/commodity proxy
    ("USD/CAD", "USDCAD=X", "FX", 2),            # Oil correlation
    ("USD/CNY", "USDCNY=X", "FX", 2),            # China policy proxy

    # === COMMODITIES (5) ===
    ("Gold", "GC=F", "Commodities", 1),          # Safe haven, real rates
    ("Silver", "SI=F", "Commodities", 1),        # Industrial precious, leverage to gold
    ("WTI Crude", "CL=F", "Commodities", 1),     # Energy, global growth
    ("Brent Crude", "BZ=F", "Commodities", 2),   # Global benchmark
    ("Copper", "HG=F", "Commodities", 2),        # Dr. Copper, manufacturing

    # === MARKET INTERNALS / CREDIT (4) ===
    ("VIX", "^VIX", "Market Internals", 1),      # Volatility / regime gauge
    ("HYG", "HYG", "Market Internals", 1),       # HY credit spreads / risk appetite
    ("LQD", "LQD", "Market Internals", 2),       # IG credit spreads
    ("5Y5Y Breakeven", "TIP", "Market Internals", 1),  # TIP/IEF proxy for inflation expectations

    # === CRYPTO (2) ===
    ("Bitcoin", "BTC-USD", "Crypto", 1),
    ("Ethereum", "ETH-USD", "Crypto", 2),
]

# Display order grouped by category
DISPLAY_GROUPS = [
    ("US Equities", ["S&P 500", "Nasdaq 100", "Dow Jones", "Russell 2000"]),
    ("Global Equities", ["Nikkei 225", "DAX", "FTSE 100", "STOXX 600", "Hang Seng"]),
    ("US Rates", ["US 2Y Yield", "US 5Y Yield", "US 10Y Yield", "US 30Y Yield"]),
    ("FX", ["DXY", "USD/JPY", "EUR/USD", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CNY"]),
    ("Commodities", ["Gold", "Silver", "WTI Crude", "Brent Crude", "Copper"]),
    ("Market Internals / Credit", ["VIX", "HYG", "LQD", "5Y5Y Breakeven"]),
    ("Crypto", ["Bitcoin", "Ethereum"]),
]

# Symbol -> (name, category, tier) lookup
TICKER_META = {sym: (name, cat, tier) for name, sym, cat, tier in CURATED_TICKERS}


@dataclass
class MarketData:
    name: str
    symbol: str
    category: str
    tier: int
    price: Optional[float]
    change: Optional[float]
    pct_change: Optional[float]
    error: Optional[str] = None


def fetch_24h_change(ticker: str) -> Dict[str, Any]:
    """Fetch current price and 24h change for a ticker using 1h bars."""
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="2d", interval="1h", prepost=True)
        if hist.empty:
            return {"price": None, "change": None, "pct_change": None, "error": "No data"}

        current_price = hist["Close"].iloc[-1]
        target_idx = max(0, len(hist) - 25)  # ~24h ago
        price_24h_ago = hist["Close"].iloc[target_idx]

        change = current_price - price_24h_ago
        pct_change = (change / price_24h_ago) * 100 if price_24h_ago != 0 else 0

        return {
            "price": round(current_price, 4),
            "change": round(change, 4),
            "pct_change": round(pct_change, 2),
            "error": None
        }
    except Exception as e:
        return {"price": None, "change": None, "pct_change": None, "error": str(e)}


def fetch_all_data() -> Dict[str, MarketData]:
    """Fetch data for all curated tickers."""
    results = {}
    print(f"Fetching data for {len(CURATED_TICKERS)} curated tickers...")

    for name, symbol, category, tier in CURATED_TICKERS:
        print(f"  {name} ({symbol})...", end=" ")
        data = fetch_24h_change(symbol)
        results[name] = MarketData(
            name=name,
            symbol=symbol,
            category=category,
            tier=tier,
            price=data["price"],
            change=data["change"],
            pct_change=data["pct_change"],
            error=data["error"]
        )
        if data["error"]:
            print(f"ERROR: {data['error']}")
        else:
            print(f"{data['price']} ({data['pct_change']:+.2f}%)")

    return results


def format_level_move(name: str, price: float, change: float, pct: float) -> str:
    """Format price/change for display based on asset class."""
    if "Yield" in name:
        return f"{price:.2f}% ({change:+.2f}bps)"
    elif "/" in name and "USD" in name:  # FX pairs
        return f"{price:.4f} ({pct:+.2f}%)"
    elif "DXY" in name or "Dollar Index" in name:
        return f"{price:.2f} ({pct:+.2f}%)"
    elif "Bitcoin" in name or "Ethereum" in name:
        return f"${price:,.0f} ({pct:+.2f}%)"
    elif name == "VIX":
        return f"{price:.2f} ({change:+.2f})"
    elif name in ["HYG", "LQD"]:
        return f"${price:.2f} ({pct:+.2f}%)"
    elif name == "5Y5Y Breakeven":
        return f"{price:.2f}% ({change:+.2f}bps)"
    else:
        return f"{price:,.2f} ({pct:+.2f}%)"


# ─── NARRATIVE GENERATION (LLM-powered) ─────────────────────────────────────
# All driver narratives and the daily caption are now generated fresh by an
# LLM (poolside/laguna-s-2.1:free via OpenRouter) so they are never recycled
# from a static template.  See llm_utils.py for the implementation.

from llm_utils import generate_all_drivers


def build_report(data):
    """Build structured report rows with fresh, LLM-powered narratives."""
    rows = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M %Z")

    # Identify top movers for narrative emphasis
    valid_data = {k: v for k, v in data.items() if not v.error and v.pct_change is not None}
    sorted_by_move = sorted(valid_data.items(), key=lambda x: abs(x[1].pct_change or 0), reverse=True)
    top_movers = set(k for k, _ in sorted_by_move[:5])

    # Generate all driver narratives in a single batched LLM call
    print("  Generating fresh LLM narratives for all tickers...")
    drivers = generate_all_drivers(data)

    for group_name, items in DISPLAY_GROUPS:
        rows.append({"type": "section", "name": group_name})

        for name in items:
            if name not in data:
                continue
            md = data[name]

            if md.error or md.price is None:
                rows.append({
                    "type": "row",
                    "name": name,
                    "level_move": "N/A",
                    "driver": f"Error: {md.error}",
                    "pct_change": None,
                    "is_top_mover": False
                })
                continue

            level_move = format_level_move(name, md.price, md.change, md.pct_change)
            driver = drivers.get(name, f"on moved {md.pct_change:+.2f}%")

            rows.append({
                "type": "row",
                "name": name,
                "level_move": level_move,
                "driver": driver,
                "pct_change": md.pct_change,
                "is_top_mover": name in top_movers
            })

    return rows, timestamp


def save_json(data: Dict[str, MarketData], rows: List[Dict], timestamp: str, output_dir: str = "output"):
    """Save raw data and report as JSON."""
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")

    # Raw data (serializable)
    raw = {k: asdict(v) for k, v in data.items()}
    with open(f"{output_dir}/market_data_{date_str}.json", "w") as f:
        json.dump(raw, f, indent=2, default=str)

    # Formatted report
    report = {"timestamp": timestamp, "date": date_str, "rows": rows}
    with open(f"{output_dir}/market_report_{date_str}.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Saved JSON to {output_dir}/")


if __name__ == "__main__":
    data = fetch_all_data()
    rows, timestamp = build_report(data)
    save_json(data, rows, timestamp)

    # Print summary
    print(f"\n{'='*80}")
    print(f"MACRO MARKET UPDATE — {timestamp}")
    print(f"{'='*80}")
    for row in rows:
        if row["type"] == "section":
            print(f"\n▶ {row['name']}")
        else:
            pct = row.get("pct_change", 0)
            color = "🟢" if pct and pct > 0 else ("🔴" if pct and pct < 0 else "⚪")
            print(f"  {color} {row['name']:20s} | {row['level_move']:30s} | {row['driver']}")
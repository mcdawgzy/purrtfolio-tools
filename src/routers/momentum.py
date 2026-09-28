"""Price momentum scanner — scanner DB when populated, yfinance on-demand otherwise."""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import scanners
from ..scanners import fetch_ohlcv, mom_watchlist, momentum_db_ready

router = APIRouter()


@router.get("/api/momentum/meta")
def momentum_meta():
    """Metadata for the momentum tab."""
    if scanners.SCANNERS_OK:
        momentum_db_ready()  # downloads the slim DB if it's empty
        return scanners.pm_db.get_meta()
    return {"latest_signal_date": None, "bar_count": 0, "ticker_count": 0}


@router.get("/api/momentum/rankings")
def momentum_rankings(
    min_price: float = Query(5.0, description="Min SMA-20d price to filter micro-caps"),
    limit: int = Query(50, ge=1, le=200),
):
    """Top momentum movers by 20-day ROC."""
    # Try DB first (cron-populated)
    if momentum_db_ready():
        return scanners.pm_db.get_momentum_rankings(min_price=min_price, limit=limit)
    # Fallback: on-demand fetch
    data = fetch_ohlcv(mom_watchlist(), days=25)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        closes = sorted(fields.get("Close", {}).items())
        if len(closes) < 22:
            continue
        prices = [c[1] for c in closes]
        sma20 = sum(prices[-20:]) / 20
        if sma20 < min_price:
            continue
        roc20 = (prices[-1] / prices[-21] - 1) if len(prices) >= 21 else 0
        vol = fields.get("Volume", {})
        vol_vals = [v for _, v in sorted(vol.items())][-10:]
        vol_ema10 = sum(vol_vals) / max(len(vol_vals), 1)
        rows.append({
            "ticker": tkr,
            "close": round(prices[-1], 2),
            "sma20": round(sma20, 2),
            "roc20": round(roc20 * 100, 2),
            "vol_vs_ema10": round(vol_vals[-1] / vol_ema10 * 100, 0) if vol_ema10 else 100,
            "signal": "strong_momentum" if roc20 > 0.1 else ("weak_momentum" if roc20 > 0 else "negative_momentum"),
        })
    rows.sort(key=lambda r: r["roc20"], reverse=True)
    return rows[:limit]


@router.get("/api/momentum/volume-spikes")
def momentum_volume_spikes(limit: int = Query(30, ge=1, le=100)):
    """Tickers with volume > 2x the 10-day volume EMA."""
    if momentum_db_ready():
        return scanners.pm_db.get_volume_spike_alerts(limit=limit)
    data = fetch_ohlcv(mom_watchlist(), days=15)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        vol = fields.get("Volume", {})
        if len(vol) < 11:
            continue
        vol_vals = [v for _, v in sorted(vol.items())]
        vol_ema10 = sum(vol_vals[-10:]) / 10
        latest_vol = vol_vals[-1]
        if vol_ema10 > 0 and latest_vol / vol_ema10 > 2:
            rows.append({
                "ticker": tkr,
                "latest_volume": int(latest_vol),
                "volume_ratio": round(latest_vol / vol_ema10, 2),
            })
    rows.sort(key=lambda r: r["volume_ratio"], reverse=True)
    return rows[:limit]


@router.get("/api/momentum/consolidation")
def momentum_consolidation(limit: int = Query(30, ge=1, le=100)):
    """Tickers in consolidation (ATR < 3% of price, inside-day range)."""
    if momentum_db_ready():
        return scanners.pm_db.get_consolidation_scan(limit=limit)
    data = fetch_ohlcv(mom_watchlist(), days=15)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        hi = fields.get("High", {})
        lo = fields.get("Low", {})
        cl = fields.get("Close", {})
        common_dates = sorted(set(hi.keys()) & set(lo.keys()) & set(cl.keys()))
        if len(common_dates) < 10:
            continue
        recent = common_dates[-10:]
        atr = sum((hi[d] - lo[d]) for d in recent) / 10
        prices = [cl[d] for d in recent]
        avg_price = sum(prices) / len(prices)
        if avg_price == 0:
            continue
        atr_pct = atr / avg_price * 100
        if atr_pct < 3:
            rows.append({
                "ticker": tkr,
                "atr_pct": round(atr_pct, 2),
                "price": round(prices[-1], 2),
                "range_10d_pct": round((max(prices) - min(prices)) / avg_price * 100, 2),
            })
    rows.sort(key=lambda r: r["range_10d_pct"])
    return rows[:limit]


@router.get("/api/momentum/earnings-gaps")
def momentum_earnings_gaps(limit: int = Query(30, ge=1, le=100)):
    """Detect overnight gaps (>1%) in recent price action."""
    if momentum_db_ready():
        return scanners.pm_db.get_earnings_gaps(limit=limit)
    data = fetch_ohlcv(mom_watchlist(), days=10)
    if not data:
        return []
    rows = []
    for tkr, fields in data.items():
        opens = sorted(fields.get("Open", {}).items())
        close_map = dict(fields.get("Close", {}))
        gaps = []
        for d, o in opens:
            if d in close_map and close_map[d] > 0:
                gap_pct = (o - close_map[d]) / close_map[d] * 100
                gaps.append({"date": d, "gap_pct": round(gap_pct, 2)})
        big_gaps = [g for g in gaps if abs(g["gap_pct"]) > 1]
        if big_gaps:
            rows.append({
                "ticker": tkr,
                "gap": big_gaps[-1],
            })
    rows.sort(key=lambda r: abs(r["gap"]["gap_pct"]), reverse=True)
    return rows[:limit]


@router.get("/api/momentum/tickers/{ticker}")
def momentum_ticker(ticker: str, limit: int = Query(60, ge=1, le=200)):
    """Daily OHLCV history for a single ticker."""
    if momentum_db_ready():
        bars = scanners.pm_db.price_history_for_ticker(ticker, limit=limit)
        return {"ticker": ticker.upper(), "bars": bars}
    # Fallback: yfinance
    data = fetch_ohlcv([ticker.upper()], days=limit)
    if not data:
        return {"ticker": ticker.upper(), "bars": []}
    fields = next(iter(data.values()))
    bars = sorted(fields.get("Close", {}).items(), reverse=True)[:limit]
    result = []
    for d, v in bars:
        result.append({
            "date": d,
            "open": fields.get("Open", {}).get(d, v),
            "high": fields.get("High", {}).get(d, v),
            "low": fields.get("Low", {}).get(d, v),
            "close": v,
            "volume": int(fields.get("Volume", {}).get(d, 0)),
        })
    return {"ticker": ticker.upper(), "bars": result}


@router.get("/api/momentum/search")
def momentum_search(q: str = Query(..., min_length=1)):
    """Search the momentum watchlist."""
    ql = q.upper().lower()
    results = [{"ticker": t, "name": t} for t in mom_watchlist() if ql in t.lower()]
    return {"results": results}

"""Crowded Trades analysis engine.

Reads from the tables already populated by upstream cron jobs and
computes a per-ticker *crowdedness* score (0-100) broken into six
components:

  1. short_crowd    — short-interest crowding (SI ratio, DTC, WoW change)
  2. options_crowd  — unusual options flow crowding (volume / severity)
  3. iv_crowd       — implied-volatility crowding (IV%Rank / IV%tile)
  4. momentum_crowd — price-momentum crowding (extreme ROC + volume)
  5. pcr_crowd      — put/call ratio market backdrop (sentiment extreme)
  6. corr_crowd     — cross-asset correlation herding

The composite score and directional signal are written to the
``crowded_trades`` table for the web UI / Discord delivery.
"""
import math
import json
import logging
from datetime import date
from typing import Dict, List, Any, Optional, Tuple

from .config import (
    COMPONENT_WEIGHTS,
    SIR_EXTREME, SIR_HIGH,
    DTC_EXTREME, DTC_HIGH,
    SI_CHANGE_SPIKE,
    UA_SEVERITY_EXTREME, UA_SEVERITY_HIGH,
    IVP_HIGH, IVP_LOW,
    ROC_CROWDED, ROC_EXTREME,
    PCR_BEARISH, PCR_BULLISH,
    EXTREME_THRESHOLD, HIGH_THRESHOLD, MEDIUM_THRESHOLD,
    CORR_PIVOT, CORR_HERDING,
    Z_SCORE_SIGNIFICANT,
)
from .db import (
    get_watchlist_tickers,
    get_short_interest_meta,
    get_unusual_activity_latest,
    get_iv_rank_latest,
    get_momentum_latest,
    get_put_call_latest,
    get_correlation_latest,
    get_db_readonly,
    get_db,
    upsert_crowded_trade,
)

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────

def _safe_float(v, default: float = 0.0) -> float:
    """Convert any numeric (incl. numpy/pandas) to float, NaN→default."""
    if v is None:
        return default
    f = float(v)
    return f if math.isfinite(f) else default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _to_signal(score: float) -> str:
    """Map a composite score to a signal tier."""
    if score >= EXTREME_THRESHOLD:
        return "EXTREME"
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "NEUTRAL"


# ─── Component 1: Short-Interest Crowding ──────────────────────────────

def _score_short(
    ticker: str,
    tsm: Optional[Dict],
    float_shares: Optional[int],
) -> Tuple[float, str, Dict[str, Any]]:
    """Score 0-100 for short-interest crowding.

    A high short/float ratio, elevated days-to-cover, and a WoW spike
    in shorts together indicate the crowd is crowded on the *short* side.
    """
    if not tsm:
        return 0.0, "short", {}

    latest_short = _safe_float(tsm.get("latest_short"))
    dtc = _safe_float(tsm.get("latest_dtc"))
    change_pct = _safe_float(tsm.get("latest_change_pct"))
    peak_short = _safe_float(tsm.get("peak_short"))

    details: Dict[str, Any] = {
        "latest_short": latest_short,
        "dtc": dtc,
        "change_pct": change_pct,
    }

    # Short interest ratio (SIR) = short / float
    sir = 0.0
    if float_shares and float_shares > 0:
        sir = latest_short / float_shares
        details["short_interest_ratio"] = round(sir, 4)

    # SIR score: 0-40 points (40 at SIR >= SIR_EXTREME=20%)
    if sir >= SIR_EXTREME:
        sir_score = 40.0
    elif sir >= SIR_HIGH:
        sir_score = 40.0 * (sir - SIR_HIGH) / (SIR_EXTREME - SIR_HIGH)
    else:
        sir_score = 40.0 * (sir / SIR_HIGH) * 0.5  # scaled below high
    sir_score = _clamp(sir_score, 0, 40)
    details["sir_score"] = round(sir_score, 1)

    # DTC score: 0-30 points (30 at DTC >= DTC_EXTREME=10)
    dtc_score = 30.0 * _safe_float(dtc) / DTC_EXTREME
    dtc_score = _clamp(dtc_score, 0, 30)
    details["dtc_score"] = round(dtc_score, 1)

    # Change score: 0-30 points (30 at change >= SI_CHANGE_SPIKE=30%)
    # Only counts *positive* changes (new shorts piling in)
    change_score = 0.0
    if change_pct > 0:
        change_score = 30.0 * change_pct / SI_CHANGE_SPIKE
        change_score = _clamp(change_score, 0, 30)
    details["change_score"] = round(change_score, 1)

    total = sir_score + dtc_score + change_score
    details["short_crowd"] = round(total, 1)
    return round(total, 1), "short", details


# ─── Component 2: Options Flow Crowding ────────────────────────────────

def _score_options(
    ticker: str,
    ua_records: List[Dict],
) -> Tuple[float, float, float, str, Dict[str, Any]]:
    """Score 0-100 for options-flow crowding.

    Returns (options_crowd, call_severity, put_severity, direction, details).
    Large one-directional options flows signal consensus positioning.
    """
    if not ua_records:
        return 0.0, 0.0, 0.0, "neutral", {}

    max_sev = max(r.get("severity_score", 0) for r in ua_records)
    call_sev = max(
        (r.get("severity_score", 0) for r in ua_records if r.get("call_put") == "call"),
        default=0.0,
    )
    put_sev = max(
        (r.get("severity_score", 0) for r in ua_records if r.get("call_put") == "put"),
        default=0.0,
    )
    total_notional = sum(r.get("notional_usd", 0) for r in ua_records)

    options_crowd = _clamp(max_sev / UA_SEVERITY_EXTREME * 100, 0, 100)

    # Direction: which side has more severe flow?
    if call_sev > put_sev + 10:
        direction = "long"
    elif put_sev > call_sev + 10:
        direction = "short"
    else:
        direction = "neutral"

    details = {
        "max_severity": round(_safe_float(max_sev), 1),
        "call_severity": round(_safe_float(call_sev), 1),
        "put_severity": round(_safe_float(put_sev), 1),
        "total_notional": round(_safe_float(total_notional)),
        "activity_count": len(ua_records),
        "direction": direction,
    }
    return round(options_crowd, 1), round(call_sev, 1), round(put_sev, 1), direction, details


# ─── Component 3: IV Crowding ──────────────────────────────────────────

def _score_iv(
    ticker: str,
    iv_data: Optional[Dict],
    peer_iv_pctile: Optional[float] = None,
) -> Tuple[float, Dict[str, Any]]:
    """Score 0-100 for IV crowding (expensive options = crowded).

    Preference order:
      1. iv_pctile  — computed by the IV Rank scanner (most robust)
      2. iv_rank    — computed by the IV Rank scanner
      3. iv_vs_52w  — raw iv relative to its 52-week range
      4. peer_pctile — IV percentile vs category peers (fallback when
         the IV scanner hasn't computed historical ranges)
    """
    if not iv_data:
        return 0.0, {}

    iv = _safe_float(iv_data.get("iv"))
    iv_rank_val = iv_data.get("iv_rank")
    iv_pctile = iv_data.get("iv_pctile")
    iv_min = _safe_float(iv_data.get("iv_min_52w"))
    iv_max = _safe_float(iv_data.get("iv_max_52w"))
    iv_mean = _safe_float(iv_data.get("iv_mean_52w"))

    details: Dict[str, Any] = {
        "iv": round(iv, 2) if iv else None,
        "iv_rank": iv_rank_val,
        "iv_pctile": iv_pctile,
    }

    # Prefer IV Percentile (most robust)
    if iv_pctile is not None:
        iv_crowd = _clamp(iv_pctile / IVP_HIGH * 100, 0, 100)
        details["basis"] = "iv_pctile"
    elif iv_rank_val is not None:
        iv_crowd = _clamp(iv_rank_val / IVP_HIGH * 100, 0, 100)
        details["basis"] = "iv_rank"
    elif iv > 0 and iv_max > 0 and iv_mean > 0:
        # Fallback: iv relative to 52w mean
        ratio = iv / iv_mean
        iv_crowd = _clamp(ratio / 1.5 * 100, 0, 100) if ratio <= 1.5 else 100.0
        details["basis"] = "iv_vs_mean"
        details["iv_vs_mean_ratio"] = round(ratio, 2)
    elif peer_iv_pctile is not None and iv > 0:
        # Fallback: peer-relative IV percentile within category
        iv_crowd = _clamp(peer_iv_pctile / IVP_HIGH * 100, 0, 100)
        details["basis"] = "peer_iv_pctile"
        details["peer_iv_pctile"] = round(peer_iv_pctile, 1)
    else:
        iv_crowd = 0.0
        details["basis"] = "no_data"

    details["iv_crowd"] = round(iv_crowd, 1)
    return round(iv_crowd, 1), details


# ─── Component 4: Momentum Crowding ────────────────────────────────────

def _score_momentum(
    ticker: str,
    m_data: Optional[Dict],
) -> Tuple[float, str, Dict[str, Any]]:
    """Score 0-100 for momentum crowding.

    Extreme price moves + volume spikes = crowded momentum positioning.
    Direction follows the sign of the 20-day ROC.
    """
    if not m_data:
        return 0.0, "neutral", {}

    roc_20d = _safe_float(m_data.get("roc_20d"))
    roc_10d = _safe_float(m_data.get("roc_10d"))
    volume_ratio = _safe_float(m_data.get("volume_ratio"))
    is_vol_spike = m_data.get("is_volume_spike", 0) == 1
    is_consolidating = m_data.get("is_consolidating", 0) == 1
    gap_pct = _safe_float(m_data.get("gap_pct"))

    details: Dict[str, Any] = {
        "roc_20d": round(roc_20d, 4),
        "roc_10d": round(roc_10d, 4),
        "volume_ratio": round(volume_ratio, 2),
        "is_volume_spike": bool(is_vol_spike),
        "is_consolidating": bool(is_consolidating),
        "gap_pct": round(gap_pct, 4) if gap_pct else None,
    }

    # ROC score: 0-50 points (50 at abs(roc_20d) >= ROC_EXTREME=30%)
    roc_score = 50.0 * abs(roc_20d) / ROC_EXTREME
    roc_score = _clamp(roc_score, 0, 50)
    details["roc_score"] = round(roc_score, 1)

    # Volume score: 0-30 points
    vol_score = 0.0
    if is_vol_spike or volume_ratio >= 3.0:
        vol_score = 30.0 * _clamp(volume_ratio / 5.0, 0, 1)
    elif volume_ratio >= 1.5:
        vol_score = 15.0 * _clamp((volume_ratio - 1.5) / 1.5, 0, 1) + 15.0
    details["vol_score"] = round(vol_score, 1)

    # Consolidation / gap score: 0-20 points
    # Consolidation = coiling, building crowded breakout potential
    # Gap = earnings/news event = sudden repositioning
    event_score = 0.0
    if is_consolidating and abs(roc_20d) < ROC_CROWDED:
        event_score = 15.0  # coiling = building crowding
    if gap_pct != 0 and abs(gap_pct) > 0.02:
        event_score = max(event_score, _clamp(abs(gap_pct) / 0.10 * 20, 0, 20))
    details["event_score"] = round(event_score, 1)

    total = roc_score + vol_score + event_score
    direction = "long" if roc_20d > 0 else ("short" if roc_20d < 0 else "neutral")

    details["momentum_crowd"] = round(total, 1)
    return round(total, 1), direction, details


# ─── Component 5: PCR Backdrop ─────────────────────────────────────────

def _score_pcr(
    pcr_latest: Dict[str, Dict],
) -> Tuple[float, str, Dict[str, Any]]:
    """Score 0-100 for the market-level PCR backdrop.

    This is applied to ALL tickers — it's a market-wide crowding signal.
    Extreme EQUITY PCR (high = bearish crowd, low = bullish complacency)
    indicates market-level positioning crowding.
    """
    equity = pcr_latest.get("EQUITY")
    if not equity or equity.get("ratio") is None:
        return 0.0, "neutral", {}

    ratio = _safe_float(equity.get("ratio"))
    z = _safe_float(equity.get("z_score"))
    signal_str = equity.get("signal", "NEUTRAL")

    details: Dict[str, Any] = {
        "equity_pcr": round(ratio, 4),
        "z_score": round(z, 2),
        "signal": signal_str,
    }

    pcr_crowd = 0.0
    direction = "neutral"

    if signal_str in ("EXTREME_HIGH", "EXTREME_LOW"):
        pcr_crowd = 100.0
    elif signal_str in ("HIGH", "LOW"):
        pcr_crowd = 70.0
    elif abs(z) >= Z_SCORE_SIGNIFICANT:
        pcr_crowd = _clamp(abs(z) / 3.0 * 100, 0, 100)
    else:
        pcr_crowd = 0.0

    # Direction: high PCR = bearish crowd (short side), low PCR = bullish crowd
    if ratio >= PCR_BEARISH:
        direction = "short"
    elif ratio <= PCR_BULLISH:
        direction = "long"
    else:
        direction = "neutral"

    details["pcr_crowd"] = round(pcr_crowd, 1)
    details["direction"] = direction
    return round(pcr_crowd, 1), direction, details


# ─── Component 6: Correlation Crowding ─────────────────────────────────

def _score_corr(
    ticker: str,
    corr_data: Optional[Dict],
    pivot: str = CORR_PIVOT,
) -> Tuple[float, str, Dict[str, Any]]:
    """Score 0-100 for correlation herding.

    High correlation to the broad market = herding = crowdedness.
    Direction follows the market's recent direction (from pivot ticker).
    """
    if not corr_data or "corr" not in corr_data:
        return 0.0, "neutral", {}

    corr_map = corr_data["corr"]
    corr_val = corr_map.get(pivot) or corr_map.get(pivot.replace("^", ""))

    if corr_val is None:
        return 0.0, "neutral", {}

    corr_val = _safe_float(corr_val)
    corr_crowd = _clamp(abs(corr_val) / CORR_HERDING * 100, 0, 100)

    details = {
        "corr_to_market": round(corr_val, 3),
        "corr_crowd": round(corr_crowd, 1),
    }
    # Direction: if correlated to market, direction = market direction.
    # We infer market direction from the sign of correlation (positive = same side).
    # The actual direction (long/short) is resolved via momentum below.
    direction = "neutral"
    return round(corr_crowd, 1), direction, details


# ─── Main scoring engine ──────────────────────────────────────────────

def _compute_peer_iv_pctiles(
    iv_data: Dict[str, Dict],
    tickers: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Compute peer-relative IV percentiles for each ticker.

    When the IV scanner hasn't computed its own iv_rank / iv_pctile
    (common on first runs), we fall back to ranking each ticker's raw
    IV within its category (or across all tickers if category is sparse).

    Returns {ticker_upper: percentile_0_to_100}.
    """
    from .config import IVP_HIGH

    # Group tickers by category
    by_cat: Dict[str, List[Tuple[str, float]]] = {}
    all_ivs: List[Tuple[str, float]] = []

    cat_lookup = {t["ticker"].upper(): t.get("category", "uncategorized") for t in tickers}

    for tkr, idata in iv_data.items():
        iv = _safe_float(idata.get("iv"))
        if iv <= 0:
            continue
        cat = cat_lookup.get(tkr.upper(), "uncategorized")
        by_cat.setdefault(cat, []).append((tkr.upper(), iv))
        all_ivs.append((tkr.upper(), iv))

    def _percentile(sorted_ivs: List[float], val: float) -> float:
        """Percentile rank (0-100) of *val* within the sorted list."""
        if not sorted_ivs:
            return 0.0
        import bisect
        pos = bisect.bisect_left(sorted_ivs, val)
        return (pos / (len(sorted_ivs) - 1) * 100) if len(sorted_ivs) > 1 else 50.0

    pctiles: Dict[str, float] = {}
    all_sorted = sorted(v for _, v in all_ivs)
    for tkr, idata in iv_data.items():
        iv = _safe_float(idata.get("iv"))
        if iv <= 0:
            continue
        tkr_up = tkr.upper()
        cat = cat_lookup.get(tkr_up, "uncategorized")
        cat_ivs = sorted(v for _, v in by_cat.get(cat, []))
        # Use category peers if we have >= 5 tickers, else fall back to all
        pool = cat_ivs if len(cat_ivs) >= 5 else all_sorted
        pctiles[tkr_up] = _percentile(pool, iv)

    return pctiles


def score_ticker(
    ticker: str,
    ticker_info: Dict[str, Any],
    tsm: Optional[Dict],
    ua_records: List[Dict],
    iv_data: Optional[Dict],
    m_data: Optional[Dict],
    pcr_latest: Dict[str, Dict],
    corr_map: Dict[str, Dict],
    peer_iv_pctile: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Compute the full crowdedness score for one ticker.

    Returns a dict ready for ``upsert_crowded_trade``, or ``None`` if
    the ticker has no data in any source table.
    """
    has_si = tsm is not None and tsm.get("latest_short") is not None
    has_ua = len(ua_records) > 0
    has_iv = iv_data is not None and iv_data.get("iv") is not None
    has_mom = m_data is not None and m_data.get("roc_20d") is not None
    has_corr = ticker in corr_map

    if not any([has_si, has_ua, has_iv, has_mom, has_corr]):
        return None

    float_shares = ticker_info.get("free_float_shares")

    # ── Component scores ──
    short_crowd, short_dir, short_d = _score_short(ticker, tsm, float_shares)
    options_crowd, call_sev, put_sev, opt_dir, opt_d = _score_options(ticker, ua_records)
    iv_crowd, iv_d = _score_iv(ticker, iv_data, peer_iv_pctile)
    mom_crowd, mom_dir, mom_d = _score_momentum(ticker, m_data)
    pcr_crowd, pcr_dir, pcr_d = _score_pcr(pcr_latest)
    corr_crowd, corr_dir, corr_d = _score_corr(ticker, corr_map.get(ticker.upper()))

    # ── Long / short decomposition ──
    # Each component is split into its long-side and short-side contribution.
    long_components = []
    short_components = []

    # Short-interest always contributes to SHORT side
    if short_crowd > 0:
        short_components.append(("short", short_crowd))

    # Options: calls → long, puts → short
    if options_crowd > 0:
        call_frac = call_sev / max(call_sev + put_sev, 1) if (call_sev + put_sev) > 0 else 0.5
        put_frac = 1 - call_frac
        long_components.append(("options_call", options_crowd * call_frac))
        short_components.append(("options_put", options_crowd * put_frac))

    # Momentum: direction follows ROC
    if mom_crowd > 0:
        if mom_dir == "long":
            long_components.append(("momentum", mom_crowd))
        elif mom_dir == "short":
            short_components.append(("momentum", mom_crowd))

    # PCR: direction from PCR
    if pcr_crowd > 0:
        if pcr_dir == "long":
            long_components.append(("pcr", pcr_crowd))
        elif pcr_dir == "short":
            short_components.append(("pcr", pcr_crowd))

    # IV and correlation are non-directional crowding indicators (applied to both sides equally)
    # They contribute to overall crowdedness but don't bias direction.

    raw_long = sum(v for _, v in long_components)
    raw_short = sum(v for _, v in short_components)

    # ── Composite score (weighted sum of component max-normalised to 100) ──
    composite = _clamp(
        short_crowd * COMPONENT_WEIGHTS["short"]
        + options_crowd * COMPONENT_WEIGHTS["options"]
        + iv_crowd * COMPONENT_WEIGHTS["iv"]
        + mom_crowd * COMPONENT_WEIGHTS["momentum"]
        + pcr_crowd * COMPONENT_WEIGHTS["pcr"]
        + corr_crowd * COMPONENT_WEIGHTS["corr"]
    )

    # ── Direction ──
    # Compare long vs short side contributions. Use a threshold so that
    # a small imbalance doesn't flip direction.
    diff = abs(raw_long - raw_short)
    margin = max(raw_long, raw_short) * 0.25  # 25% margin needed to declare a direction
    if diff < margin or (raw_long < 15 and raw_short < 15):
        direction = "neutral"
    elif raw_long > raw_short:
        direction = "long"
    else:
        direction = "short"

    # If both sides are strongly crowded → bilateral
    if raw_long >= 40 and raw_short >= 40:
        direction = "bilateral"

    # Long / short component scores (for display)
    long_crowd = _clamp(composite * (raw_long / (raw_long + raw_short)) if (raw_long + raw_short) > 0 else 0)
    short_crowd_out = _clamp(composite * (raw_short / (raw_long + raw_short)) if (raw_long + raw_short) > 0 else 0)

    signal = _to_signal(composite)

    details = {
        "short_interest": short_d,
        "options": opt_d,
        "iv": iv_d,
        "momentum": mom_d,
        "pcr": pcr_d,
        "correlation": corr_d,
        "long_side_contributions": [k for k, _ in long_components],
        "short_side_contributions": [k for k, _ in short_components],
        "raw_long": round(raw_long, 1),
        "raw_short": round(raw_short, 1),
    }

    return {
        "ticker": ticker.upper(),
        "date": str(date.today()),
        "crowdedness_score": round(composite, 1),
        "short_crowd": round(short_crowd_out, 1),
        "long_crowd": round(long_crowd, 1),
        "iv_crowd": round(iv_crowd, 1),
        "options_crowd": round(options_crowd, 1),
        "momentum_crowd": round(mom_crowd, 1),
        "pcr_crowd": round(pcr_crowd, 1),
        "corr_crowd": round(corr_crowd, 1),
        "crowd_direction": direction,
        "signal": signal,
        "signal_details": json.dumps(details, default=str),
    }


def analyze_all() -> Dict[str, Any]:
    """Run the full crowded-trades analysis against the unified DB.

    Returns a summary dict with results for every ticker that had at
    least one active signal, plus aggregate counts.
    """
    today = str(date.today())

    # ── Load watchlist ──
    tickers = get_watchlist_tickers()
    if not tickers:
        return {"status": "no_data", "date": today, "tickers_scanned": 0, "signals_found": 0}

    # ── Load all upstream data once (batch reads) ──
    si_meta = get_short_interest_meta()
    ua_latest = get_unusual_activity_latest()
    ua_data = ua_latest.get("data", {})
    ua_date = ua_latest.get("_date")
    iv_latest = get_iv_rank_latest()
    iv_data = iv_latest.get("data", {})
    iv_date = iv_latest.get("_date")
    iv_pctiles = _compute_peer_iv_pctiles(iv_data, tickers)
    mom_latest = get_momentum_latest()
    mom_data = mom_latest.get("data", {})
    mom_date = mom_latest.get("_date")
    pcr_latest = get_put_call_latest()
    corr_latest = get_correlation_latest()
    corr_map = corr_latest.get("data", {})
    corr_date = corr_latest.get("_date")

    logger.info(
        "Crowded Trades analysis — SI:%d, UA:%s, IV:%s, Mom:%s, PCR:%d series, Corr:%s | tickers:%d",
        len(si_meta), ua_date, iv_date, mom_date, len(pcr_latest), corr_date, len(tickers),
    )

    results: List[Dict[str, Any]] = []
    for tinfo in tickers:
        ticker = tinfo["ticker"].upper()
        tsm = si_meta.get(ticker) or si_meta.get(tinfo["ticker"])
        ua_recs = ua_data.get(ticker, [])
        ivd = iv_data.get(ticker) or iv_data.get(tinfo["ticker"])
        md = mom_data.get(ticker) or mom_data.get(tinfo["ticker"])
        peer_iv = iv_pctiles.get(ticker)

        result = score_ticker(
            ticker=ticker,
            ticker_info=tinfo,
            tsm=tsm,
            ua_records=ua_recs,
            iv_data=ivd,
            m_data=md,
            pcr_latest=pcr_latest,
            corr_map=corr_map,  # full {ticker: {"corr": {...}}} dict
            peer_iv_pctile=peer_iv,
        )
        if result:
            results.append(result)

    # ── Persist ──
    written = 0
    with get_db() as conn:
        for row in results:
            conn.execute("""
                INSERT INTO crowded_trades (
                    ticker, date, crowdedness_score, short_crowd, long_crowd,
                    iv_crowd, options_crowd, momentum_crowd, pcr_crowd,
                    corr_crowd, crowd_direction, signal, signal_details
                ) VALUES (
                    :ticker, :date, :crowdedness_score, :short_crowd, :long_crowd,
                    :iv_crowd, :options_crowd, :momentum_crowd, :pcr_crowd,
                    :corr_crowd, :crowd_direction, :signal, :signal_details
                )
                ON CONFLICT(ticker, date) DO UPDATE SET
                    crowdedness_score = excluded.crowdedness_score,
                    short_crowd       = excluded.short_crowd,
                    long_crowd        = excluded.long_crowd,
                    iv_crowd          = excluded.iv_crowd,
                    options_crowd     = excluded.options_crowd,
                    momentum_crowd    = excluded.momentum_crowd,
                    pcr_crowd         = excluded.pcr_crowd,
                    corr_crowd        = excluded.corr_crowd,
                    crowd_direction   = excluded.crowd_direction,
                    signal            = excluded.signal,
                    signal_details    = excluded.signal_details
            """, row)
            written += 1
        conn.commit()

    # ── Aggregate ──
    by_signal = {}
    by_direction = {}
    for r in results:
        by_signal[r["signal"]] = by_signal.get(r["signal"], 0) + 1
        by_direction[r["crowd_direction"]] = by_direction.get(r["crowd_direction"], 0) + 1

    top = sorted(results, key=lambda x: x["crowdedness_score"], reverse=True)[:10]

    return {
        "status": "completed",
        "date": today,
        "tickers_scanned": len(tickers),
        "tickers_with_signals": len(results),
        "signals_found": len([r for r in results if r["signal"] != "NEUTRAL"]),
        "by_signal": by_signal,
        "by_direction": by_direction,
        "top_crowded": [
            {
                "ticker": r["ticker"],
                "score": r["crowdedness_score"],
                "signal": r["signal"],
                "direction": r["crowd_direction"],
            }
            for r in top
        ],
        "source_dates": {
            "short_interest": si_meta.get(next(iter(si_meta), ""), {}).get("latest_settlement") if si_meta else None,
            "unusual_activity": ua_date,
            "iv_rank": iv_date,
            "momentum": mom_date,
            "correlation": corr_date,
            "put_call": pcr_latest.get("EQUITY", {}).get("date") if pcr_latest else None,
        },
    }


def score_single_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """Analyze a single ticker — convenience CLI helper.

    Loads all upstream data and delegates to :func:`score_ticker`.
    """
    ticker = ticker.upper()
    tickers = get_watchlist_tickers()
    tinfo = next((t for t in tickers if t["ticker"].upper() == ticker), {"ticker": ticker, "free_float_shares": None})

    si_meta = get_short_interest_meta()
    tsm = si_meta.get(ticker)
    ua_latest = get_unusual_activity_latest()
    ua_data = ua_latest.get("data", {})
    ua_recs = ua_data.get(ticker, [])
    iv_latest = get_iv_rank_latest()
    iv_data = iv_latest.get("data", {})
    ivd = iv_data.get(ticker)
    peer_iv = _compute_peer_iv_pctiles(iv_data, tickers).get(ticker)
    mom_latest = get_momentum_latest()
    mom_data = mom_latest.get("data", {})
    md = mom_data.get(ticker)
    pcr_latest = get_put_call_latest()
    corr_latest = get_correlation_latest()
    corr_map = corr_latest.get("data", {})

    return score_ticker(
        ticker=ticker,
        ticker_info=tinfo,
        tsm=tsm,
        ua_records=ua_recs,
        iv_data=ivd,
        m_data=md,
        pcr_latest=pcr_latest,
        corr_map=corr_map,
        peer_iv_pctile=peer_iv,
    )


if __name__ == "__main__":
    import pprint
    pprint.pprint(analyze_all())

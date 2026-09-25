"""Data ingestion for Earnings Revision Momentum scanner.

Fetches yfinance earnings history for watchlist tickers and computes:
  - avg_revision_4q: average pct change between estimate and actual over
    the last 4 reported quarters
  - pct_positive: fraction of quarters with positive surprise
  - avg_surprise_pct: mean earnings surprise (actual vs estimate)
  - trend: improving / deteriorating / stable (recent revisions vs older)
  - zscore: standardized momentum score across the universe

Stores results in the unified purrtfolio.db SQLite database.
"""
import logging
import math
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import yfinance as yf

SCANNERS_DIR = Path(__file__).resolve().parent.parent
if str(SCANNERS_DIR) not in sys.path:
    sys.path.insert(0, str(SCANNERS_DIR))
SRC_DIR = SCANNERS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from earnings_revisions.config import DB_PATH, WATCHLIST, MIN_QUARTERS, MAX_WORKERS
from db import init_earnings_revisions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _num(v, default=None):
    """Convert pandas/numpy scalar to float, treating NaN/Inf/None as default."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _fetch_earnings_history(ticker: str):
    """Fetch earnings history DataFrame from yfinance.  Never raises."""
    try:
        yt = yf.Ticker(ticker)
        df = yt.earnings_history
        if df is None or df.empty:
            logger.warning(f"  {ticker}: no earnings_history data")
            return None
        df.attrs["ticker"] = ticker
        return df
    except Exception as e:
        logger.warning(f"  {ticker}: yfinance error — {e}")
        return None


def _compute_revision_metrics(df) -> dict | None:
    """Compute revision metrics from a yfinance earnings_history DataFrame.

    Handles multiple column naming conventions across yfinance versions:
      - surprisePercent / Surprise Percent (already a % surprise)
      - epsActual / Actual  +  epsEstimate / Estimate
    The Period may be in a 'Period' column or in the DataFrame index.
    """
    raw_cols = {c.lower().strip(): c for c in df.columns}

    # ── Resolve surprise_pct column ──
    sp_col = (raw_cols.get("surprisepercent")
              or raw_cols.get("surprise_percent")
              or raw_cols.get("surprise"))

    # ── Resolve actual / estimate columns ──
    actual_col = (raw_cols.get("actual")
                  or raw_cols.get("actual_eps")
                  or raw_cols.get("epsactual")
                  or raw_cols.get("epsactual"))
    est_col = (raw_cols.get("estimate")
               or raw_cols.get("estimate_eps")
               or raw_cols.get("epestimate"))

    # Resolve period — may be in a column or in the index
    period_col = raw_cols.get("period")
    idx_name = str(df.index.name).lower().strip() if df.index.name else ""
    if not period_col and idx_name in ("period", "date", "quarter"):
        period_col = "index"

    if sp_col:
        # yfinance provides surprisePercent directly: (actual-est)/|est|*100
        def _get_surp(row):
            v = _num(row[sp_col])
            return v / 100.0 if v is not None else None
        def _get_period(row):
            if period_col == "index":
                return str(row.name) if row.name else None
            if period_col:
                return str(row[period_col]) if row[period_col] is not None else None
            return None
        revisions = []
        for _, row in df.iterrows():
            sp = _get_surp(row)
            if sp is None:
                continue
            revisions.append({
                "period": _get_period(row),
                "revision_pct": sp,
            })
    elif actual_col and est_col:
        # Compute (actual - estimate) / |estimate|
        revisions = []
        for _, row in df.iterrows():
            actual = _num(row[actual_col])
            est = _num(row[est_col])
            if actual is None or est is None or est == 0:
                continue
            period = None
            if period_col == "index":
                period = str(row.name) if row.name else None
            elif period_col:
                period = str(row[period_col]) if row[period_col] is not None else None
            revisions.append({
                "period": period,
                "revision_pct": (actual - est) / abs(est),
            })
    else:
        logger.warning(f"  Missing expected columns: {list(df.columns)}")
        return None

    if len(revisions) < MIN_QUARTERS:
        logger.info(f"  {df.attrs.get('ticker', '?')}: only {len(revisions)} quarters (need {MIN_QUARTERS})")
        return None

    # Take last 4 quarters
    last4 = revisions[-4:]
    recent = revisions[-2:]
    older = revisions[-4:-2] if len(revisions) >= 4 else []

    avg_revision = sum(r["revision_pct"] for r in last4) / len(last4)
    pct_pos = sum(1 for r in last4 if r["revision_pct"] > 0) / len(last4)
    avg_surprise = sum(r["revision_pct"] for r in last4) / len(last4)  # same as avg_revision

    # Trend: compare recent avg to older avg
    recent_avg = sum(r["revision_pct"] for r in recent) / len(recent) if recent else 0
    older_avg = sum(r["revision_pct"] for r in older) / len(older) if older else 0
    if recent_avg > older_avg + 0.02:
        trend = "improving"
    elif recent_avg < older_avg - 0.02:
        trend = "deteriorating"
    else:
        trend = "stable"

    latest_report = None
    for r in reversed(revisions):
        if r["period"]:
            latest_report = r["period"]
            break

    return {
        "avg_revision_4q": round(avg_revision, 4),
        "pct_positive": round(pct_pos, 3),
        "avg_surprise_pct": round(avg_surprise * 100, 2),
        "trend": trend,
        "latest_report_date": latest_report,
    }


def _upsert_momentum(conn, ticker: str, metrics: dict, zscore: float):
    """Upsert a single ticker's momentum into both tables."""
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO earnings_revision_momentum
            (ticker, latest_report_date, avg_revision_4q, pct_positive,
             avg_surprise_pct, trend, zscore, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        metrics["latest_report_date"],
        metrics["avg_revision_4q"],
        metrics["pct_positive"],
        metrics["avg_surprise_pct"],
        metrics["trend"],
        round(zscore, 3),
        today,
    ))
    conn.execute("""
        INSERT OR REPLACE INTO earnings_revision_history
            (ticker, date, avg_revision_4q, pct_positive,
             avg_surprise_pct, trend, zscore)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker, today,
        metrics["avg_revision_4q"],
        metrics["pct_positive"],
        metrics["avg_surprise_pct"],
        metrics["trend"],
        round(zscore, 3),
    ))


def run_once():
    """Fetch earnings data for all watchlist tickers and update momentum scores."""
    # 1. Ensure tables exist
    init_earnings_revisions()
    logger.info("earnings_revision tables initialized")

    # 2. Fetch + compute per ticker
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_earnings_history, t): t for t in WATCHLIST}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                df = fut.result()
                if df is not None:
                    metrics = _compute_revision_metrics(df)
                    if metrics:
                        results[ticker] = metrics
                        logger.info(f"  {ticker}: rev={metrics['avg_revision_4q']:.4f} "
                                    f"surprise={metrics['avg_surprise_pct']:.1f}% "
                                    f"trend={metrics['trend']}")
            except Exception as e:
                logger.error(f"  {ticker}: failed — {e}")

    if not results:
        logger.warning("No earnings data collected for any ticker")
        return {"updated": 0, "error": "No data collected"}

    # 3. Compute z-scores across the universe
    revs = [v["avg_revision_4q"] for v in results.values()]
    mean_rev = sum(revs) / len(revs)
    var = sum((r - mean_rev) ** 2 for r in revs) / len(revs)
    std_rev = math.sqrt(var)

    # 4. Upsert into DB
    conn = sqlite3.connect(str(DB_PATH))
    for ticker, metrics in results.items():
        if std_rev > 0:
            zscore = (metrics["avg_revision_4q"] - mean_rev) / std_rev
        else:
            zscore = 0.0
        _upsert_momentum(conn, ticker, metrics, zscore)
    conn.commit()

    # 5. Summary
    improving = sum(1 for v in results.values() if v["trend"] == "improving")
    deteriorating = sum(1 for v in results.values() if v["trend"] == "deteriorating")
    conn.close()

    logger.info(f"Done: {len(results)} tickers updated "
                f"(improving={improving}, deteriorating={deteriorating})")
    return {
        "updated": len(results),
        "improving": improving,
        "deteriorating": deteriorating,
        "mean_revision": round(mean_rev, 4),
        "std_revision": round(std_rev, 4),
    }


if __name__ == "__main__":
    import json
    result = run_once()
    print(json.dumps(result, indent=2))

"""Bridge to the scanner packages under <repo>/scanners + yfinance fallbacks.

This is the ONE place the API imports scanner code (as the `scanners`
package, from the repo root). Exposes:
  pm_db, cm_db, SCANNERS_OK   price_momentum / correlation_matrix DB modules
  ensure_momentum_db()        download the slim momentum DB if missing
  momentum_db_ready(), corr_db_ready()
  mom_watchlist(), corr_pivots(), fetch_ohlcv(), compute_corr_on_demand()
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import MOMENTUM_RELEASE_ASSET, ROOT, get_db_path
from .database import _download_db_if_needed as download_db_if_needed
from .database import download_with_redirect, gunzip

log = logging.getLogger("13f-web")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scanners.price_momentum import db as pm_db
    from scanners.correlation_matrix import db as cm_db
    SCANNERS_OK = True
except Exception as e:
    log.warning(f"Scanner modules not importable in API: {e}")
    pm_db, cm_db, SCANNERS_OK = None, None, False

# yfinance is installed via buildCommand — used for on-demand fallback
try:
    import yfinance as _yf
    import pandas as _pd
    _YF_OK = True
except Exception:
    _YF_OK = False
    _yf = _pd = None


# ---------------------------------------------------------------------------
# Slim momentum DB (price_history + corr_matrices)
# ---------------------------------------------------------------------------
def ensure_momentum_db(at_startup: bool = False) -> None:
    """Download the slim momentum DB (price_history + corr_matrices) from the
    GitHub Release if it's missing. Called on startup and lazily from endpoints
    when bar_count() / total_rows() returns 0."""
    if not SCANNERS_OK:
        return
    # Same path the scanner modules read from (MOMENTUM_DB, else the main DB)
    slim_db = Path(pm_db.DB_PATH)
    if slim_db.resolve() == get_db_path().resolve():
        # No separate MOMENTUM_DB: momentum data lives in the main DB. Never put
        # the slim extract there (it would shadow the full DB); fetch the full
        # DB instead, lazily on first request like every other route.
        if not at_startup:
            download_db_if_needed(slim_db)
        return
    if slim_db.exists() and slim_db.stat().st_size > 100_000:
        return
    log.info("Momentum DB missing — downloading...")
    gz = Path(str(slim_db) + ".gz")
    try:
        slim_db.parent.mkdir(parents=True, exist_ok=True)
        download_with_redirect(MOMENTUM_RELEASE_ASSET, str(gz))
        gunzip(gz, slim_db)
        gz.unlink()
        log.info(f"Momentum DB ready ({slim_db.stat().st_size / 1e6:.1f}MB)")
    except Exception as e:
        log.error(f"Momentum DB download failed: {e}")


def momentum_db_ready() -> bool:
    """True if the scanner DB has price bars (downloading it first if empty)."""
    if not SCANNERS_OK:
        return False
    if pm_db.bar_count() > 0:
        return True
    ensure_momentum_db()
    return pm_db.bar_count() > 0


def corr_db_ready() -> bool:
    """True if the scanner DB has correlation rows (downloading it first if empty)."""
    if not SCANNERS_OK:
        return False
    if cm_db.total_rows() > 0:
        return True
    ensure_momentum_db()
    return cm_db.total_rows() > 0


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
def mom_watchlist() -> list[str]:
    """Return the curated momentum watchlist tickers.

    Order of preference:
      1. DB-stored watchlist (from price_momentum DB module)
      2. Hardcoded curated list (always available, ~54 tickers)
    """
    if SCANNERS_OK:
        tickers = pm_db.get_watchlist_tickers()
        if tickers:
            return tickers
    # Hardcoded curated list — mirrors scanners/price_momentum/config.py
    return [
        "^GSPC", "^NDX", "^DJI", "^RUT",
        "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
        "AVGO", "ASML", "AMD", "INTC", "CRM", "ADBE", "NFLX", "ORCL",
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW",
        "JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY",
        "XOM", "CVX", "COP", "EOG", "SLB", "OXY",
        "WMT", "HD", "PG", "KO", "PEP", "COST", "NKE", "MCD",
        "^N225", "^GDAXI", "^FTSE", "^STOXX", "^HSI",
        "DX-Y.NYB", "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X",
        "^IRX", "^FVX", "^TNX", "^TYX",
        "GC=F", "SI=F", "CL=F", "BZ=F", "HG=F",
        "HYG", "LQD", "TIP", "^VIX",
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO",
        "BTC-USD", "ETH-USD",
    ]


def corr_pivots() -> list[str]:
    """Pivot/asset-class tickers for correlation."""
    if SCANNERS_OK:
        pivots = cm_db.get_pivot_tickers()
        if pivots:
            return pivots
    return ["^GSPC", "^NDX", "^RUT", "^TNX", "^IRX", "^VIX", "SPY", "QQQ"]


# ---------------------------------------------------------------------------
# yfinance on-demand fallbacks (used when the scanner DB is empty/unavailable)
# ---------------------------------------------------------------------------
def fetch_ohlcv(tickers: list[str], days: int = 25) -> dict:
    """Fetch recent daily OHLCV for a list of tickers via yfinance.

    Downloads in batches of 20 to avoid yfinance timeouts with large lists.
    Returns {ticker: {field: {YYYY-MM-DD: value}}}.
    """
    if not _YF_OK or not tickers:
        return {}
    result: dict[str, dict] = {}
    batch_size = 20
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            period = f"{max(days + 5, 30)}d"
            df = _yf.download(
                tickers=" ".join(batch),
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
            )
            if df.empty:
                continue
            cols = df.columns
            if isinstance(cols, _pd.MultiIndex):
                for ticker in batch:
                    # group_by="ticker" -> columns are (ticker, field)
                    if ticker not in cols.get_level_values(0):
                        continue
                    sub = df[ticker].dropna(how="all")
                    if sub.empty:
                        continue
                    series = {}
                    for field in ("Open", "High", "Low", "Close", "Volume"):
                        if field in sub.columns:
                            s = sub[field].dropna()
                            series[field] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
                    result[ticker] = series
            else:
                # Single-column DataFrame (single ticker in batch)
                for field in ("Open", "High", "Low", "Close", "Volume"):
                    if field in df.columns:
                        s = df[field].dropna()
                        result.setdefault(batch[0], {})[field] = {
                            d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()
                        }
        except Exception as e:
            log.warning(f"yfinance batch fetch failed for {batch}: {e}")
            continue
    return result


def compute_corr_on_demand(
    target_tickers: list[str],
    pivots: list[str],
    window: str,
) -> dict:
    """Compute correlation of each target vs each pivot, on-demand via yfinance.
    Returns {ticker: {pivot: corr}}."""
    if not _YF_OK:
        return {}
    day_map = {"1_month": 21, "3_month": 63, "6_month": 126, "12_month": 252}
    days = day_map.get(window, 63)
    all_tickers = list(dict.fromkeys(pivots + target_tickers))
    try:
        df = _yf.download(
            tickers=" ".join(all_tickers),
            period=f"{days + 10}d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        log.warning(f"yfinance corr fetch failed: {e}")
        return {}
    if df.empty:
        return {}
    cols = df.columns
    # Get close prices aligned by date
    if isinstance(cols, _pd.MultiIndex):
        # yfinance columns are (field, ticker)
        if "Close" not in cols.get_level_values(0):
            return {}
        price_df = df["Close"].dropna(axis=1, how="all").dropna()
    else:
        price_df = df["Close"].dropna().to_frame("price")
        # Single ticker — can't compute matrix
        if len(all_tickers) == 1:
            return {}
    if price_df.shape[0] < days:
        price_df = price_df.tail(days)
    returns = price_df.pct_change().dropna()
    if returns.empty:
        return {}
    result: dict[str, dict] = {}
    for tk in target_tickers:
        if tk not in returns.columns:
            continue
        tk_ret = returns[tk]
        corr = {}
        for p in pivots:
            if p not in returns.columns:
                continue
            c = tk_ret.corr(returns[p])
            if c is not None and not (c != c):  # not NaN
                corr[p] = round(float(c), 4)
        if corr:
            result[tk] = corr
    return result

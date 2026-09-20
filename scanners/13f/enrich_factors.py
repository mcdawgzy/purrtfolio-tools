#!/usr/bin/env python3
"""Enrich the unified purrtfolio.db with per-ticker factor classification.

Creates a `ticker_factors` table that classifies each holding by the three
style factors the Factor Exposure dashboard needs:

  - Size:        market-cap bucket  (Large / Mid / Small)
  - Value/Growth: book-to-market     (Value / Blend / Growth)
  - Momentum:    20-day rate-of-change (Momentum / Neutral / Contrarian)

Follows the exact pattern of ``enrich_sectors.py``: prioritise tickers by
latest-quarter AUM so the largest positions are classified first, pull
characteristics from yfinance, and upsert into the DB.

Data sources
------------
* market_cap, trailingPE, priceToBook  ->  ``yf.Ticker(t).info`` (per-ticker)
* 20d price ROC (momentum)             ->  ``yf.download`` bulk (fast, one call)

The enrichment is idempotent and safe to re-run: rows are only refreshed when
missing or older than ``STALE_DAYS`` (default 30).  A single run classifies the
top ``--limit`` tickers by AUM (default 300, ~78% of total AUM).

Cron-compatible — drop this in the quarterly 13F pipeline right after
``compare.py`` + ``enrich_sectors.py``:

    python enrich_factors.py --db C:/Users/cho_i/purrtfolio.db
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

DEFAULT_DB = Path(r"C:/Users/cho_i/purrtfolio.db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enrich_factors")

# ─── Classification thresholds (Fama-French style) ──────────────────
SIZE_LARGE = 10e9     # ≥ $10B
SIZE_MID = 2e9        # $2B–$10B
# book-to-market (1 / P-B)
BTM_VALUE = 0.7       # ≥ 0.7  -> Value
BTM_GROWTH = 0.4      # ≤ 0.4  -> Growth  (0.4 < btm < 0.7 -> Blend)
# fallback by P/E when B/M unavailable
PE_VALUE = 15.0       # ≤ 15  -> Value
PE_GROWTH = 25.0      # ≥ 25  -> Growth
# momentum 20-day ROC
MOM_UP = 5.0          # > +5%  -> Momentum
MOM_DOWN = -5.0       # < -5%  -> Contrarian


def classify_size(market_cap: float | None) -> str:
    if market_cap is None or market_cap <= 0:
        return "Unknown"
    if market_cap >= SIZE_LARGE:
        return "Large"
    if market_cap >= SIZE_MID:
        return "Mid"
    return "Small"


def classify_vg(pe: float | None, pb: float | None) -> str:
    """Value / Growth / Blend using book-to-market, P/E fallback."""
    btm = (1.0 / pb) if (pb and pb > 0) else None
    if btm is not None:
        if btm >= BTM_VALUE:
            return "Value"
        if btm <= BTM_GROWTH:
            return "Growth"
        return "Blend"
    # P/E fallback
    if pe is not None and pe > 0:
        if pe <= PE_VALUE:
            return "Value"
        if pe >= PE_GROWTH:
            return "Growth"
        return "Blend"
    return "Unknown"


def classify_mom(roc_20d: float | None) -> str:
    if roc_20d is None:
        return "Unknown"
    if roc_20d > MOM_UP:
        return "Momentum"
    if roc_20d < MOM_DOWN:
        return "Contrarian"
    return "Neutral"


# ─── DB helpers ─────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ticker_factors (
    ticker         TEXT PRIMARY KEY,
    market_cap     BIGINT,
    pe_ratio       REAL,
    price_to_book  REAL,
    size_bucket    TEXT,
    value_bucket   TEXT,
    momentum_bucket TEXT,
    momentum_roc_20d REAL,
    sector         TEXT,
    enriched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tf_size   ON ticker_factors(size_bucket);
CREATE INDEX IF NOT EXISTS idx_tf_value  ON ticker_factors(value_bucket);
CREATE INDEX IF NOT EXISTS idx_tf_mom    ON ticker_factors(momentum_bucket);
"""


def latest_quarter(conn: sqlite3.Connection) -> str | None:
    r = conn.execute(
        "SELECT MAX(report_period) FROM filings_13f WHERE has_infotable=1"
    ).fetchone()
    return r[0] if r else None


def tickers_needing_factors(conn: sqlite3.Connection, quarter: str, limit: int,
                            staleness_days: int = 30) -> list[str]:
    """Top tickers by latest-quarter AUM that lack (or have stale) factor data."""
    sql = f"""
        SELECT h.ticker, SUM(h.market_value_usd) AS aum
        FROM holdings_13f h
        WHERE h.report_period = ?
          AND h.ticker IS NOT NULL AND h.ticker != ''
          AND h.put_call = ''
          AND h.ticker NOT IN (SELECT ticker FROM ticker_factors
                               WHERE enriched_at > date('now', '-{staleness_days} days'))
        GROUP BY h.ticker
        ORDER BY aum DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (quarter, limit)).fetchall()
    return [r[0] for r in rows]


def upsert_factors(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany("""
        INSERT INTO ticker_factors
          (ticker, market_cap, pe_ratio, price_to_book, size_bucket,
           value_bucket, momentum_bucket, momentum_roc_20d, sector, enriched_at)
        VALUES
          (:ticker, :market_cap, :pe_ratio, :price_to_book, :size_bucket,
           :value_bucket, :momentum_bucket, :momentum_roc_20d, :sector, :enriched_at)
        ON CONFLICT(ticker) DO UPDATE SET
          market_cap        = excluded.market_cap,
          pe_ratio          = excluded.pe_ratio,
          price_to_book     = excluded.price_to_book,
          size_bucket       = excluded.size_bucket,
          value_bucket      = excluded.value_bucket,
          momentum_bucket   = excluded.momentum_bucket,
          momentum_roc_20d  = excluded.momentum_roc_20d,
          sector            = excluded.sector,
          enriched_at       = excluded.enriched_at
    """, [{
        "ticker": r["ticker"], "market_cap": r.get("market_cap"),
        "pe_ratio": r.get("pe_ratio"), "price_to_book": r.get("price_to_book"),
        "size_bucket": r.get("size_bucket"), "value_bucket": r.get("value_bucket"),
        "momentum_bucket": r.get("momentum_bucket"),
        "momentum_roc_20d": r.get("roc_20d"), "sector": r.get("sector"),
        "enriched_at": datetime.utcnow().isoformat(timespec="seconds"),
    } for r in rows])
    conn.commit()
    return len(rows)


# ─── yfinance fetches ───────────────────────────────────────────────
def fetch_info(ticker: str) -> dict | None:
    """Single-ticker yfinance info for market cap / PE / PB.  Never raises."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "price_to_book": info.get("priceToBook"),
            "sector": info.get("sector"),
        }
    except Exception as e:
        log.warning(f"  ✗ {ticker} info: {e}")
        return None


def fetch_momentum_all(tickers: list[str], slim_conn: sqlite3.Connection | None = None) -> dict[str, float]:
    """Compute 20-day ROC for every ticker in ``tickers``.

    Strategy (maximises coverage, minimises yfinance calls):
      1. Reuse the momentum scanner's already-computed ``roc_20d`` from
         ``price_momentum_signals`` (latest date) for watchlist tickers.
      2. Reuse ``price_history`` (close prices) in the slim DB where present.
      3. Bulk-download the remainder in chunks of 50 via ``yf.download``
         (a single call per chunk) and compute ROC from close prices.

    Returns ``{ticker: roc_20d_pct}``.  Tickers that still can't be resolved
    are simply omitted (caller leaves momentum = Unknown).
    """
    out: dict[str, float] = {}
    remaining: list[str] = list(tickers)

    # 1) + 2) reuse existing slim-DB data (momentum scanner already ran)
    if slim_conn is not None:
        try:
            sig_rows = slim_conn.execute(
                "SELECT ticker, roc_20d FROM price_momentum_signals "
                "WHERE date = (SELECT MAX(date) FROM price_momentum_signals) "
                "AND roc_20d IS NOT NULL"
            ).fetchall()
            for tk, roc in sig_rows:
                if tk in tickers and roc is not None:
                    out[tk] = roc * 100  # db stores fractional, we want pct
        except sqlite3.Error:
            pass
        # price_history: compute roc_20d (last vs 21 days prior) for covered tickers
        ph_rows = slim_conn.execute(
            "SELECT ticker, date, close FROM price_history ORDER BY ticker, date"
        ).fetchall()
        ph_map: dict[str, list[tuple[str, float]]] = {}
        for tk, dt, close in ph_rows:
            if close is not None:
                ph_map.setdefault(tk, []).append((dt, close))
        for tk, series in ph_map.items():
            if tk not in tickers or tk in out:
                continue
            series.sort()
            if len(series) >= 21:
                out[tk] = (series[-1][1] / series[-21][1] - 1) * 100
        remaining = [t for t in remaining if t not in out]

    if not remaining:
        return out

    # 3) bulk download in chunks (robust: one bad ticker won't kill the batch)
    import pandas as pd
    chunk = 50
    for i in range(0, len(remaining), chunk):
        batch = remaining[i:i + chunk]
        log.info(f"  bulk price download chunk {i // chunk + 1}: {len(batch)} tickers")
        try:
            df = yf.download(
                tickers=" ".join(batch), period="35d", interval="1d",
                progress=False, auto_adjust=False, timeout=60,
            )
        except Exception as e:
            log.warning(f"  chunk {i // chunk + 1} download failed: {e}")
            time.sleep(2)
            continue
        if df.empty or "Close" not in df.columns:
            continue
        closes = df["Close"]
        is_multi = isinstance(closes.columns, pd.MultiIndex)
        level = closes.columns.get_level_values(1) if is_multi else None
        for tk in batch:
            if tk in out:
                continue
            try:
                s = closes[tk] if not is_multi else closes[tk]
                if is_multi and tk not in level:
                    continue
                s = s.dropna()
                if len(s) >= 21:
                    out[tk] = (s.iloc[-1] / s.iloc[-21] - 1) * 100
            except Exception:
                continue
        time.sleep(0.5)
    return out


def fetch_info_batched(tickers: list[str]) -> dict[str, dict]:
    """Fetch yfinance info for a list of tickers with retry + rate limiting."""
    results: dict[str, dict] = {}
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i + 50]
        log.info(f"  yfinance info batch {i // 50 + 1}: {len(batch)} tickers")
        for tk in batch:
            # retry once
            for attempt in range(2):
                info = fetch_info(tk)
                if info:
                    results[tk] = info
                    break
                time.sleep(1)
        time.sleep(1)  # be polite
    return results


def main():
    parser = argparse.ArgumentParser(description="Enrich ticker_factors for the Factor Exposure dashboard")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to purrtfolio.db")
    parser.add_argument("--limit", type=int, default=300, help="Max tickers to (re)classify by AUM")
    parser.add_argument("--stale-days", type=int, default=30, help="Re-enrich rows older than this")
    parser.add_argument("--refresh", action="store_true", help="Ignore staleness -- re-enrich everything")
    parser.add_argument("--slim-db", default=r"C:/Users/cho_i/13f-scanner-web/scanners/price_momentum/momentum_data.db",
                        help="Path to slim momentum_data.db (reuse signals/history)")
    parser.add_argument("--batch", type=int, default=50, help="yfinance.info batch size")
    args = parser.parse_args()

    if args.refresh:
        args.stale_days = 0

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)

    quarter = latest_quarter(conn)
    if not quarter:
        print("ERROR: no 13F filings found in DB", file=sys.stderr)
        conn.close()
        sys.exit(1)
    log.info(f"Latest quarter: {quarter}")

    already = conn.execute("SELECT COUNT(*) FROM ticker_factors").fetchone()[0]
    log.info(f"Existing ticker_factors rows: {already}")

    targets = tickers_needing_factors(conn, quarter, args.limit, args.stale_days)
    log.info(f"Tickers needing enrichment (top {args.limit} by AUM): {len(targets)}")
    if not targets:
        log.info("All target tickers already enriched within window.")
        conn.close()
        return

    # open slim momentum DB to reuse already-computed momentum signals/history
    slim_conn = sqlite3.connect(args.slim_db) if Path(args.slim_db).exists() else None
    if slim_conn:
        sig_count = slim_conn.execute("SELECT COUNT(*) FROM price_momentum_signals").fetchone()[0]
        log.info(f"Reusing momentum signals from slim DB ({sig_count} signal rows).")

    # 1) momentum via reuse + bulk download
    log.info("Fetching 20-day momentum ...")
    momentum = fetch_momentum_all(targets, slim_conn)
    log.info(f"  momentum computed for {len(momentum)} tickers")

    # 2) per-ticker info → market cap / PE / PB
    log.info("Fetching market cap / PE / P-B via yfinance.info (batched)...")
    infos = fetch_info_batched(targets)
    log.info(f"  info fetched for {len(infos)} tickers")

    # 3) classify + upsert
    rows: list[dict] = []
    for tk in targets:
        info = infos.get(tk, {})
        mc = info.get("market_cap")
        pe = info.get("pe_ratio")
        pb = info.get("price_to_book")
        roc = momentum.get(tk)
        rows.append({
            "ticker": tk,
            "market_cap": mc,
            "pe_ratio": pe,
            "price_to_book": pb,
            "size_bucket": classify_size(mc),
            "value_bucket": classify_vg(pe, pb),
            "momentum_bucket": classify_mom(roc),
            "roc_20d": roc,
            "sector": info.get("sector"),
        })

    n = upsert_factors(conn, rows)
    log.info(f"Upserted {n} ticker_factors rows.")

    # coverage summary
    cov = conn.execute("""
        SELECT SUM(h.market_value_usd) AS covered
        FROM holdings_13f h
        JOIN ticker_factors tf ON h.ticker = tf.ticker
        WHERE h.report_period = ?
    """, (quarter,)).fetchone()[0] or 0
    total = conn.execute(
        "SELECT SUM(market_value_usd) FROM holdings_13f WHERE report_period=? AND put_call=''",
        (quarter,)).fetchone()[0] or 0
    log.info(f"AUM coverage: ${cov/1e9:.1f}B / ${total/1e9:.1f}B = {cov/total*100:.1f}%")

    # distribution preview
    sd = f"-{args.stale_days} days" if args.stale_days else "-1 day"
    for dim, col in [("Size", "size_bucket"), ("Value/Growth", "value_bucket"), ("Momentum", "momentum_bucket")]:
        dist = conn.execute(
            f"SELECT {col}, COUNT(*) FROM ticker_factors WHERE enriched_at > date('now','{sd}') GROUP BY {col}"
        ).fetchall()
        log.info(f"  {dim} distribution: {dict(dist)}")

    conn.close()
    if slim_conn:
        slim_conn.close()
    log.info("✓ Factor enrichment complete.")


if __name__ == "__main__":
    main()

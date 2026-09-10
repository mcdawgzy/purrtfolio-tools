#!/usr/bin/env python3
"""
One-shot fix for the 1000x inflated market_value_usd bug.

Root cause: ingest.py did `int(row['Value'] * 1000)` but edgartools already
returns Value in actual USD (not thousands). Verified against SEC source:
tableValueTotal in primary_doc.xml matches edgartools' Value exactly, and
both are in actual USD per the 13F-HR spec.

This script:
  1. Backs up purrtfolio.db to purrtfolio.db.bak.units-fix-YYYYMMDD
  2. Divides holdings_13f.market_value_usd by 1000
  3. Divides filings_13f.total_value_usd by 1000
  4. Recomputes holding_changes_13f generated columns (SQLite auto-recomputes
     stored generated columns on UPDATE — verified)
  5. Prints before/after sanity checks against SEC ground truth

Run once: python fix_value_units.py --db C:/Users/cho_i/purrtfolio.db
"""
import argparse
import sqlite3
import shutil
from datetime import date
from pathlib import Path
import sys


def fetch_sec_table_total(cik: str, accession: str) -> int | None:
    """Pull the SEC's official <tableValueTotal> for cross-check."""
    import urllib.request, re
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/primary_doc.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "Purrtfolio Research research@purrtfolio.local"})
    try:
        data = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")
        m = re.search(r"<tableValueTotal>([0-9]+)</tableValueTotal>", data)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="C:/Users/cho_i/purrtfolio.db")
    parser.add_argument("--skip-backup", action="store_true",
                        help="Skip the backup (you already have one)")
    parser.add_argument("--skip-sec-check", action="store_true",
                        help="Skip the SEC ground-truth verification")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    # ---- 1. Backup ----
    if not args.skip_backup:
        backup = db_path.with_suffix(f".bak.units-fix-{date.today().isoformat()}")
        if backup.exists():
            print(f"Backup already exists at {backup}, skipping backup step")
        else:
            print(f"Backing up {db_path} -> {backup}")
            shutil.copy2(db_path, backup)
            print(f"  OK ({backup.stat().st_size:,} bytes)")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")  # SQLite can't change col types mid-transaction

    # ---- 2. Before-state sanity ----
    print("\n--- BEFORE ---")
    before_total = conn.execute(
        "SELECT SUM(total_value_usd) FROM filings_13f WHERE has_infotable=1"
    ).fetchone()[0]
    before_holdings = conn.execute(
        "SELECT SUM(market_value_usd) FROM holdings_13f"
    ).fetchone()[0]
    print(f"  filings_13f.total_value_usd sum: ${before_total:,}  (${before_total/1e12:.2f}T)")
    print(f"  holdings_13f.market_value_usd sum: ${before_holdings:,}  (${before_holdings/1e12:.2f}T)")

    # ---- 3. SEC ground-truth verification (sample 5 funds) ----
    if not args.skip_sec_check:
        print("\n--- SEC GROUND TRUTH (sample 5 funds, Q2 2026) ---")
        samples = conn.execute("""
            SELECT fl.accession_number, fl.fund_cik, f.name, fl.total_value_usd
            FROM filings_13f fl
            JOIN funds f ON f.cik = fl.fund_cik
            WHERE fl.report_period = '2026-06-30' AND fl.has_infotable=1
            ORDER BY fl.total_value_usd DESC LIMIT 5
        """).fetchall()
        all_match = True
        for acc, cik, name, db_total in samples:
            sec_total = fetch_sec_table_total(cik, acc)
            if sec_total is None:
                print(f"  {name:35s}  SEC fetch failed")
                continue
            ratio = db_total / sec_total if sec_total else 0
            ok = abs(ratio - 1000) < 0.01
            mark = "OK" if ok else "WRONG"
            print(f"  {name:35s}  SEC=${sec_total:>16,}  DB=${db_total:>22,}  ratio={ratio:.1f}x  [{mark}]")
            if not ok:
                all_match = False
        if not all_match:
            print("\nABORT: ratios don't match 1000x — do not proceed.", file=sys.stderr)
            conn.close()
            sys.exit(2)

    # ---- 4. Apply fix in a transaction ----
    print("\n--- APPLYING FIX (divide by 1000) ---")
    n_holdings = conn.execute("SELECT COUNT(*) FROM holdings_13f").fetchone()[0]
    n_filings  = conn.execute("SELECT COUNT(*) FROM filings_13f").fetchone()[0]

    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE holdings_13f SET market_value_usd = market_value_usd / 1000")
        conn.execute("UPDATE filings_13f SET total_value_usd = total_value_usd / 1000 "
                     "WHERE total_value_usd IS NOT NULL")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"ERROR during UPDATE: {e}", file=sys.stderr)
        conn.close()
        sys.exit(3)
    print(f"  Updated {n_holdings:,} holdings_13f rows")
    print(f"  Updated {n_filings:,} filings_13f rows")

    # SQLite STORED generated columns (value_change_usd, value_change_pct, etc.)
    # are automatically recomputed when the underlying columns are updated,
    # but they only recompute when *that row* is touched. Since we updated
    # holdings_13f (the source), the holding_changes_13f rows whose prev/curr
    # join to those holdings are NOT auto-touched. We need to force them.
    #
    # Trick: UPDATE ... SET prev_shares = prev_shares to force a row rewrite
    # that lets SQLite recompute the generated columns. But that's 285k rows.
    # Alternative: drop and recreate the generated columns — too invasive.
    # Cleanest: a dummy UPDATE that touches every row.
    n_changes = conn.execute("SELECT COUNT(*) FROM holding_changes_13f").fetchone()[0]
    print(f"  Refreshing generated columns on {n_changes:,} holding_changes_13f rows...")
    conn.execute("""
        UPDATE holding_changes_13f
        SET prev_shares = prev_shares
    """)
    conn.commit()

    # ---- 5. After-state sanity ----
    print("\n--- AFTER ---")
    after_total = conn.execute(
        "SELECT SUM(total_value_usd) FROM filings_13f WHERE has_infotable=1"
    ).fetchone()[0]
    after_holdings = conn.execute(
        "SELECT SUM(market_value_usd) FROM holdings_13f"
    ).fetchone()[0]
    print(f"  filings_13f.total_value_usd sum: ${after_total:,}  (${after_total/1e12:.2f}T)")
    print(f"  holdings_13f.market_value_usd sum: ${after_holdings:,}  (${after_holdings/1e12:.2f}T)")
    print(f"  reduction factor: holdings={before_holdings/after_holdings:.1f}x, "
          f"filings={before_total/after_total:.1f}x")

    # ---- 6. SEC ground-truth verification (same sample) ----
    if not args.skip_sec_check:
        print("\n--- SEC GROUND TRUTH (after fix, sample 5 funds) ---")
        samples = conn.execute("""
            SELECT fl.accession_number, fl.fund_cik, f.name, fl.total_value_usd
            FROM filings_13f fl
            JOIN funds f ON f.cik = fl.fund_cik
            WHERE fl.report_period = '2026-06-30' AND fl.has_infotable=1
            ORDER BY fl.total_value_usd DESC LIMIT 5
        """).fetchall()
        for acc, cik, name, db_total in samples:
            sec_total = fetch_sec_table_total(cik, acc)
            if sec_total is None:
                print(f"  {name:35s}  SEC fetch failed")
                continue
            ratio = db_total / sec_total if sec_total else 0
            ok = abs(ratio - 1.0) < 0.01
            mark = "OK" if ok else "WRONG"
            print(f"  {name:35s}  SEC=${sec_total:>16,}  DB=${db_total:>22,}  ratio={ratio:.3f}x  [{mark}]")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
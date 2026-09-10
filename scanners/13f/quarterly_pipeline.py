#!/usr/bin/env python3
"""
Quarterly 13F ingestion pipeline - auto-detects latest quarter
Run via cron: 0 6 15 2,5,8,11 *
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path
# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def run_cmd(cmd, desc):
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  Command: {cmd}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=Path(__file__).parent)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"FAILED: {desc} (exit code {result.returncode})")
        return False
    print(f"OK: {desc}")
    return True

def get_latest_quarter_end():
    """Determine the latest quarter end that has filings in the database.

    Uses the unified `purrtfolio.db` (merged 13F + SI store). Falls back to the
    legacy `13f_scanner.db` only when the unified DB is unavailable.
    """
    import sqlite3
    import os

    candidates = [
        Path(r"C:\Users\cho_i\purrtfolio.db"),
        Path(__file__).parent / "13f_scanner.db",
    ]
    db_path = next((p for p in candidates if p.exists() and p.stat().st_size > 0), candidates[0])

    conn = sqlite3.connect(db_path)
    try:
        # unified schema uses filings_13f; legacy schema uses filings
        for table in ("filings_13f", "filings"):
            try:
                row = conn.execute(f"SELECT MAX(report_period) FROM {table}").fetchone()
                if row and row[0]:
                    return row[0]
            except sqlite3.OperationalError:
                continue
    finally:
        conn.close()

    # Fallback: use SEC deadline logic
    now = datetime.now()
    quarters = [
        (3, 31, 5, 15),   # Q1 end Mar 31, deadline May 15
        (6, 30, 8, 14),   # Q2 end Jun 30, deadline Aug 14
        (9, 30, 11, 14),  # Q3 end Sep 30, deadline Nov 14
        (12, 31, 2, 14),  # Q4 end Dec 31, deadline Feb 14 (next year)
    ]
    
    for i, (q_end_month, q_end_day, deadline_month, deadline_day) in enumerate(quarters):
        if deadline_month < q_end_month:
            deadline_year = now.year + 1
        else:
            deadline_year = now.year
        
        deadline = datetime(deadline_year, deadline_month, deadline_day)
        quarter_end = datetime(now.year, q_end_month, q_end_day)
        
        if now >= deadline:
            return quarter_end.strftime("%Y-%m-%d")
    
    return f"{now.year - 1}-12-31"

def main():
    print("=" * 60)
    print("  13F Quarterly Ingestion Pipeline")
    print("=" * 60)
    print(f"Started: {datetime.now().isoformat()}")
    
    # Get latest quarter
    latest_quarter = get_latest_quarter_end()
    print(f"Latest quarter to process: {latest_quarter}")
    
    # All steps target the unified purrtfolio.db explicitly.
    # argparse in main.py expects --db BEFORE the subcommand, so it lives there.
    db_flag = '--db "C:/Users/cho_i/purrtfolio.db"'

    # Step 1: Ingest
    if not run_cmd(
        f'python main.py {db_flag} ingest --email "13f-scanner@example.com" --max-filings 3',
        "Ingest latest filings"
    ):
        sys.exit(1)

    # Step 2: Compare
    if not run_cmd(
        f'python main.py {db_flag} compare --backfill',
        "Run QoQ comparison"
    ):
        sys.exit(1)

    # Step 3: Export
    if not run_cmd(
        f'python main.py {db_flag} export --quarter {latest_quarter} --package --output-dir exports',
        f"Generate Excel exports for {latest_quarter}"
    ):
        sys.exit(1)

    # Step 4: Enrich sectors (for sector rotation view on web dashboard)
    run_cmd(
        f'python enrich_sectors.py --db "C:/Users/cho_i/purrtfolio.db" --limit 500',
        "Enrich tickers with GICS sector data"
    )

    print(f"\n{'='*60}")
    print("  Pipeline completed successfully!")
    print(f"  Completed: {datetime.now().isoformat()}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
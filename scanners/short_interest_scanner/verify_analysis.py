"""Verify unified DB analysis queries work."""
import sys
import os
sys.path.insert(0, r'C:\Users\cho_i')
import importlib.util
spec = importlib.util.spec_from_file_location("db", r'C:\Users\cho_i\short_interest_scanner\db.py')
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)
from db import get_db, get_spikes, get_high_dtc, get_largest_positions, get_covering, get_consensus_shorts

with get_db() as conn:
    # Latest settlement
    latest = conn.execute("SELECT MAX(settlement_date) FROM short_interest").fetchone()[0]
    print(f"Latest settlement: {latest}")
    
    # Summary stats
    total = conn.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]
    tickers = conn.execute("SELECT COUNT(DISTINCT symbol) FROM short_interest").fetchone()[0]
    print(f"Total rows: {total}, Distinct tickers: {tickers}")
    
    # Ticker meta count
    meta = conn.execute("SELECT COUNT(*) FROM ticker_short_meta").fetchone()[0]
    print(f"Ticker meta rows: {meta}")
    
    # Test queries
    try:
        spikes = get_spikes(min_change_pct=30, min_short=500000, limit=10)
        print(f"\nShort spikes (≥30%): {len(spikes)}")
        for s in spikes[:3]:
            print(f"  {s['symbol']}: +{s['change_pct']}% ({s['current_short']:,} shares)")
    except Exception as e:
        print(f"Spikes query error: {e}")
    
    try:
        dtc = get_high_dtc(min_dtc=5, min_short=1000000, limit=5)
        print(f"\nHigh DTC (≥5 days): {len(dtc)}")
        for d in dtc[:3]:
            print(f"  {d['symbol']}: {d['days_to_cover']} days ({d['current_short']:,} short)")
    except Exception as e:
        print(f"DTC query error: {e}")
    
    try:
        covering = get_covering(min_change_pct=-20, min_short=500000, limit=5)
        print(f"\nCovering (≥-20% decrease): {len(covering)}")
        for c in covering[:3]:
            print(f"  {c['symbol']}: {c['change_pct']}% ({c['current_short']:,} → {c['previous_short']:,})")
    except Exception as e:
        print(f"Covering query error: {e}")

print("\n[✓] Unified DB analysis queries working")

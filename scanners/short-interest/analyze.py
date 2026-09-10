"""
Analysis engine for short interest signals
"""
from typing import List, Dict, Any, Optional
from datetime import date, timedelta
import pandas as pd

from .config import (
    SPIKE_THRESHOLD_PCT, HIGH_DTC_THRESHOLD, MIN_SHORT_POSITION,
    COVERING_THRESHOLD_PCT, NEW_SHORT_MULTIPLIER
)
from .db import (
    get_spikes, get_high_dtc, get_largest_positions, get_covering,
    get_new_shorts, get_consensus_shorts, get_ticker_history,
    get_latest_snapshot, get_categories, get_category_summary,
    get_db
)


def analyze_ticker(symbol: str) -> Dict[str, Any]:
    """Comprehensive analysis for a single ticker"""
    snapshot = get_latest_snapshot(symbol)
    if not snapshot:
        return {'error': f'No data for {symbol}'}

    history = get_ticker_history(symbol, limit=26)

    # Calculate derived metrics
    current_short = snapshot['current_short'] or 0
    previous_short = snapshot['previous_short'] or 0
    days_to_cover = snapshot['days_to_cover'] or 0
    change_pct = snapshot['change_pct'] or 0

    # Short interest ratio (days to cover) interpretation
    if days_to_cover > 10:
        dtc_signal = "HIGH - Potential squeeze candidate"
    elif days_to_cover > 5:
        dtc_signal = "ELEVATED"
    elif days_to_cover > 2:
        dtc_signal = "NORMAL"
    else:
        dtc_signal = "LOW"

    # Change interpretation
    if change_pct > SPIKE_THRESHOLD_PCT:
        change_signal = "SPIKE - Major short increase"
    elif change_pct > 20:
        change_signal = "SIGNIFICANT INCREASE"
    elif change_pct > 5:
        change_signal = "MODERATE INCREASE"
    elif change_pct < COVERING_THRESHOLD_PCT:
        change_signal = "COVERING - Major short decrease"
    elif change_pct < -15:
        change_signal = "SIGNIFICANT COVERING"
    elif change_pct < -5:
        change_signal = "MODERATE COVERING"
    else:
        change_signal = "STABLE"

    # Trend analysis (last 4 periods)
    recent = history[:4] if len(history) >= 4 else history
    trend = "INSUFFICIENT_DATA"
    if len(recent) >= 3:
        changes = [h['change_pct'] for h in recent if h['change_pct'] is not None]
        if all(c > 0 for c in changes):
            trend = "CONSISTENTLY_INCREASING"
        elif all(c < 0 for c in changes):
            trend = "CONSISTENTLY_DECREASING"
        elif sum(changes) > 10:
            trend = "NET_INCREASING"
        elif sum(changes) < -10:
            trend = "NET_DECREASING"
        else:
            trend = "MIXED"

    return {
        'symbol': symbol,
        'name': snapshot['issue_name'],
        'exchange': snapshot['exchange'],
        'market_class': snapshot['market_class'],
        'settlement_date': snapshot['settlement_date'],
        'current_short': current_short,
        'previous_short': previous_short,
        'change_pct': change_pct,
        'change_abs': snapshot['change_abs'],
        'days_to_cover': days_to_cover,
        'avg_daily_volume': snapshot['avg_daily_volume'],
        'dtc_signal': dtc_signal,
        'change_signal': change_signal,
        'trend': trend,
        'history': history,
        'signals': {
            'is_spike': change_pct > SPIKE_THRESHOLD_PCT and current_short >= MIN_SHORT_POSITION,
            'is_high_dtc': days_to_cover >= HIGH_DTC_THRESHOLD and current_short >= MIN_SHORT_POSITION,
            'is_covering': change_pct <= COVERING_THRESHOLD_PCT and current_short >= MIN_SHORT_POSITION,
            'is_new_short': previous_short > 0 and current_short >= previous_short * NEW_SHORT_MULTIPLIER and current_short >= MIN_SHORT_POSITION,
            'is_large_position': current_short >= 50_000_000,
        }
    }


def get_all_signals(latest_date: Optional[date] = None) -> Dict[str, List[Dict]]:
    """Get all signal types for the latest period"""
    return {
        'spikes': get_spikes(SPIKE_THRESHOLD_PCT, MIN_SHORT_POSITION),
        'high_dtc': get_high_dtc(HIGH_DTC_THRESHOLD, MIN_SHORT_POSITION),
        'largest': get_largest_positions(MIN_SHORT_POSITION),
        'covering': get_covering(COVERING_THRESHOLD_PCT, MIN_SHORT_POSITION),
        'new_shorts': get_new_shorts(NEW_SHORT_MULTIPLIER, MIN_SHORT_POSITION),
        'consensus': get_consensus_shorts(5_000_000),
    }


def get_market_summary() -> Dict[str, Any]:
    """Get overall market summary"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Latest settlement date
        cursor.execute("SELECT MAX(settlement_date) FROM short_interest")
        latest = cursor.fetchone()[0]

        # Total short interest
        cursor.execute("""
            SELECT SUM(current_short) as total_short, COUNT(*) as count
            FROM short_interest WHERE settlement_date = ?
        """, (latest,))
        total = cursor.fetchone()

        # By exchange
        cursor.execute("""
            SELECT exchange, SUM(current_short) as total, COUNT(*) as count
            FROM short_interest WHERE settlement_date = ?
            GROUP BY exchange ORDER BY total DESC
        """, (latest,))
        by_exchange = [dict(r) for r in cursor.fetchall()]

        # By category
        cursor.execute("""
            SELECT t.category, SUM(si.current_short) as total, COUNT(*) as count
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = ?
            GROUP BY t.category ORDER BY total DESC
        """, (latest,))
        by_category = [dict(r) for r in cursor.fetchall()]

        # Signal counts
        signals = get_all_signals()

        return {
            'latest_settlement': latest,
            'total_short_interest': total[0] if total else 0,
            'ticker_count': total[1] if total else 0,
            'by_exchange': by_exchange,
            'by_category': by_category,
            'signal_counts': {k: len(v) for k, v in signals.items()},
        }


def detect_divergences(lookback: int = 4) -> List[Dict]:
    """Detect price/short interest divergences (placeholder - needs price data)"""
    # This would require price data integration
    # For now, return empty - could be extended with yfinance
    return []


def get_watchlist_performance(category: Optional[str] = None) -> List[Dict]:
    """Get performance metrics for watchlist"""
    with get_db() as conn:
        cursor = conn.cursor()

        base_query = """
            SELECT t.symbol, t.name, t.category,
                   si.current_short, si.previous_short, si.change_pct,
                   si.days_to_cover, si.avg_daily_volume,
                   LAG(si.current_short) OVER (PARTITION BY si.symbol ORDER BY si.settlement_date) as prev_short
            FROM short_interest si
            JOIN tickers t ON si.symbol = t.ticker
            WHERE si.settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
        """
        if category:
            base_query += f" AND t.category = '{category}'"
        base_query += " ORDER BY si.current_short DESC"

        cursor.execute(base_query)
        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python -m short_interest_scanner.analyze <command> [args]")
        print("Commands:")
        print("  ticker SYMBOL          - Analyze single ticker")
        print("  signals                - Get all signals")
        print("  summary                - Market summary")
        print("  category CAT           - Category summary")
        print("  watchlist [CAT]        - Watchlist performance")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "ticker":
        symbol = sys.argv[2].upper()
        result = analyze_ticker(symbol)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "signals":
        result = get_all_signals()
        for k, v in result.items():
            print(f"\n=== {k.upper()} ({len(v)}) ===")
            for item in v[:10]:
                print(f"  {item['symbol']}: {item.get('change_pct', item.get('days_to_cover', item.get('current_short')))}")

    elif cmd == "summary":
        result = get_market_summary()
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "category":
        cat = sys.argv[2]
        result = get_category_summary(cat)
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "watchlist":
        cat = sys.argv[2] if len(sys.argv) > 2 else None
        result = get_watchlist_performance(cat)
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown command: {cmd}")
#!/usr/bin/env python3
"""Economic Calendar Scanner — CLI entry point.

Usage:
  python main.py ingest            # Fetch upcoming events (next 30 days) and upsert into DB
  python main.py backfill          # Fetch events for the next 90 days
  python main.py stats             # Show DB stats
  python main.py export            # Export to CSV
  python main.py --help

Follows the same CLI pattern as scanners/short_interest_scanner/main.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make sibling modules importable
sys.path.insert(0, os.path.dirname(__file__))

from config import DB_PATH, EXPORTS_DIR, UPCOMING_DAYS
from db import init_db, upsert_event, db_conn
from fetcher import fetch_all_events


def get_utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def ingest(days_ahead: int = None) -> int:
    """Fetch upcoming events and upsert into the database."""
    if days_ahead is None:
        days_ahead = UPCOMING_DAYS

    print(f"{'='*60}")
    print(f"ECONOMIC CALENDAR INGEST")
    print(f"{'='*60}")
    print(f"DB: {DB_PATH}")
    print(f"Days ahead: {days_ahead}")
    print(f"UTC now: {get_utc_now()}")
    print(f"{'='*60}\n")

    # Ensure DB + table exist
    init_db()

    # Fetch events
    events = fetch_all_events()
    if not events:
        print("⚠️  No events fetched. Check network/connection.")
        return 1

    # Filter to upcoming window
    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_ahead)
    upcoming = [
        e for e in events
        if datetime.fromisoformat(e["event_date"]) <= cutoff
        and datetime.fromisoformat(e["event_date"]) >= now - timedelta(days=1)
    ]

    if not upcoming:
        print("⚠️  No upcoming events in the next "
              f"{days_ahead} days after filtering.")
        return 1

    # Upsert
    inserted = 0
    updated = 0
    for ev in upcoming:
        row_id = upsert_event(
            event_date=ev["event_date"],
            event_time=ev["event_time"],
            event_name=ev["event_name"],
            category=ev["category"],
            impact=ev["impact"],
            actual=ev.get("actual"),
            prior=ev.get("prior"),
            forecast=ev.get("forecast"),
            timezone_id=ev.get("timezone_id"),
            source=ev.get("source"),
            url=ev.get("url"),
        )
        if row_id:
            inserted += 1

    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"{'='*60}")
    print(f"  Fetched:     {len(events)} total events")
    print(f"  Upcoming:    {len(upcoming)} events (next {days_ahead} days)")
    print(f"  Upserted:    {inserted}")
    print(f"  Categories:  {sorted(set(e['category'] for e in upcoming))}")
    print(f"  DB:          {DB_PATH}")
    print()

    # Also store the events in a JSON file for debugging
    json_path = EXPORTS_DIR / f"economic_events_{datetime.now().strftime('%Y%m%d')}.json"
    with open(json_path, "w") as f:
        json.dump({"fetched_at": get_utc_now(), "events": events}, f, indent=2)
    print(f"  Debug JSON:  {json_path}")

    return 0


def stats() -> int:
    """Print stats about the economic_events table."""
    init_db()
    with db_conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM economic_events"
        ).fetchone()[0]

        upcoming = c.execute(
            "SELECT COUNT(*) FROM economic_events WHERE event_date >= date('now')"
        ).fetchone()[0]

        by_category = c.execute(
            "SELECT category, COUNT(*) FROM economic_events GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()

        by_impact = c.execute(
            "SELECT impact, COUNT(*) FROM economic_events GROUP BY impact ORDER BY impact"
        ).fetchall()

        top_upcoming = c.execute("""
            SELECT event_date, event_time, event_name, category, impact
            FROM economic_events
            WHERE event_date >= date('now')
            ORDER BY event_date, event_time
            LIMIT 20
        """).fetchall()

    print(f"\n{'='*60}")
    print(f"ECONOMIC EVENTS DB STATS")
    print(f"{'='*60}")
    print(f"  Total events:  {total}")
    print(f"  Upcoming:      {upcoming}")
    print(f"\n  By category:")
    for cat, cnt in by_category:
        print(f"    {cat:20s} {cnt:>5}")
    print(f"\n  By impact:")
    for imp, cnt in by_impact:
        print(f"    {imp:20s} {cnt:>5}")
    print(f"\n  Next 20 upcoming events:")
    print(f"  {'Date':<12} {'Time':<6} {'Event':<30} {'Cat':<10} {'Impact':<8}")
    print(f"  {'-'*12} {'-'*6} {'-'*30} {'-'*10} {'-'*8}")
    for row in top_upcoming:
        print(f"  {row[0]:<12} {row[1] or '':<6} {row[2]:<30.30s} {row[3]:<10} {row[4]:<8}")
    print()
    return 0


def export_csv() -> int:
    """Export upcoming events to CSV."""
    init_db()
    with db_conn() as c:
        rows = c.execute("""
            SELECT event_date, event_time, event_name, category,
                   impact, actual, prior, forecast, source
            FROM economic_events
            WHERE event_date >= date('now')
            ORDER BY event_date, event_time
        """).fetchall()

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = EXPORTS_DIR / f"economic_calendar_{datetime.now().strftime('%Y%m%d')}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "time_utc", "event", "category",
                         "impact", "actual", "prior", "forecast", "source"])
        for r in rows:
            writer.writerow(r)

    print(f"Exported {len(rows)} upcoming events to {csv_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Economic Calendar Scanner — free macro event data"
    )
    parser.add_argument(
        "--days", type=int, default=UPCOMING_DAYS,
        help=f"Days ahead to fetch (default: {UPCOMING_DAYS})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("ingest", help="Fetch and store upcoming events")
    subparsers.add_parser("stats", help="Show DB stats")
    subparsers.add_parser("export", help="Export to CSV")

    args = parser.parse_args()

    if args.command == "ingest":
        return ingest(days_ahead=args.days)
    elif args.command == "stats":
        return stats()
    elif args.command == "export":
        return export_csv()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())

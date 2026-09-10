#!/usr/bin/env python3
"""
Market Snapshot Pipeline - main orchestrator.

Usage:
  python main.py                          # Run and save locally
  python main.py --post-discord           # Run, save, and post to Discord webhook
  python main.py --date 20260905          # Run for specific date
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from fetch_market_data import build_report, save_report
from render_snapshot import load_report, render_market_snapshot


def post_to_discord(webhook_url: str, png_path: str, content: str = None) -> bool:
    """Post PNG to Discord via webhook. Returns True on success."""
    import requests
    try:
        with open(png_path, "rb") as f:
            payload = {}
            if content:
                payload["content"] = content
            files = {"file": (os.path.basename(png_path), f, "image/png")}
            resp = requests.post(webhook_url, data=payload, files=files, timeout=30)
        if resp.status_code in (200, 204):
            print(f"Posted to Discord: {png_path}")
            return True
        else:
            print(f"Discord post failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"Discord post error: {e}")
        return False


def run_pipeline(date_str: str = None) -> str:
    """Run fetch → render. Returns PNG path."""
    print("=" * 60)
    print("Market Snapshot Pipeline")
    print("=" * 60)

    # Fetch + report
    report = build_report()
    json_path = save_report(report)

    # Render
    if date_str is None:
        date_str = report["date_str"]
    png_path = render_market_snapshot(report, date_str=date_str)

    return png_path


def main():
    parser = argparse.ArgumentParser(description="Daily Market Snapshot Pipeline")
    parser.add_argument("--date", help="Date string (YYYYMMDD), defaults to today")
    parser.add_argument("--discord-webhook", help="Discord webhook URL (overrides .env)")
    parser.add_argument("--post-discord", action="store_true",
                        help="Post PNG to Discord webhook after rendering")
    parser.add_argument("--content", default=None,
                        help="Optional text content to include with Discord post")
    args = parser.parse_args()

    # Load .env
    load_dotenv()

    # Run pipeline
    png_path = run_pipeline(args.date)

    # Discord post
    if args.post_discord:
        webhook = args.discord_webhook or os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook:
            print("ERROR: --post-discord set but no webhook URL provided.")
            print("       Use --discord-webhook URL or set DISCORD_WEBHOOK_URL in .env")
            sys.exit(1)
        success = post_to_discord(webhook, png_path, args.content)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

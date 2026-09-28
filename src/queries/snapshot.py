"""Macro market snapshot (PNG + report JSON written by the macro pipeline)."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import get_snapshot_dir


def empty_snapshot(date_str: str | None) -> dict:
    """Response shape when no snapshot is available."""
    return {
        "date_str": date_str,
        "png_filename": None,
        "caption": None,
        "top_movers": [],
        "timestamp": None,
    }


def _find_latest_report_json(out_dir: Path) -> Path | None:
    """Find the latest market_report JSON in a directory.

    Checks for both dated names (market_report_YYYYMMDD.json) and
    the latest symlink/copy (market_report_latest.json).
    """
    # Prefer dated files (newest first), then fall back to _latest.
    # Filter to digits: "market_report_latest.json" sorts after any date.
    dated = sorted(
        (p for p in out_dir.glob("market_report_*.json") if p.stem[len("market_report_"):].isdigit()),
        reverse=True,
    )
    if dated:
        return dated[0]
    latest = out_dir / "market_report_latest.json"
    return latest if latest.exists() else None


def _resolve_snapshot_filenames(out_dir: Path, date_str: str) -> tuple[str | None, str]:
    """Return (png_filename or None, caption or "") for a given date_str,
    trying both dated and '_latest' naming conventions."""
    png_dated = out_dir / f"market_snapshot_{date_str}.png"
    png_latest = out_dir / "market_snapshot.png"
    caption_dated = out_dir / f"market_caption_{date_str}.txt"
    caption_latest = out_dir / "market_caption_latest.txt"

    png_filename = None
    if png_dated.exists():
        png_filename = png_dated.name
    elif png_latest.exists():
        png_filename = png_latest.name

    caption = ""
    if caption_dated.exists():
        caption = caption_dated.read_text().strip()
    elif caption_latest.exists():
        caption = caption_latest.read_text().strip()

    return png_filename, caption


def _read_snapshot(out_dir: Path, json_path: Path, date_str: str) -> dict:
    """Build the snapshot response: files + top 3 movers by absolute pct_change
    (with their driver narratives)."""
    with open(json_path, "r") as f:
        report = json.load(f)

    png_filename, caption = _resolve_snapshot_filenames(out_dir, date_str)

    data_rows = [r for r in report["rows"] if r.get("pct_change") is not None]
    top3 = sorted(data_rows, key=lambda x: abs(x["pct_change"]), reverse=True)[:3]

    top_movers = [
        {
            "name": r["name"],
            "pct_change": r["pct_change"],
            "driver": r["driver"],
            "level_move": r["level_move"],
        }
        for r in top3
    ]

    return {
        "date_str": date_str,
        "png_filename": png_filename,
        "caption": caption,
        "top_movers": top_movers,
        "timestamp": report.get("timestamp", ""),
    }


def get_latest_snapshot() -> dict | None:
    """Latest macro market snapshot, or None if none is available yet."""
    out_dir = get_snapshot_dir()
    if not out_dir.exists():
        return None
    json_path = _find_latest_report_json(out_dir)
    if not json_path:
        return None
    date_str = json_path.stem.replace("market_report_", "").replace("_latest", "")
    return _read_snapshot(out_dir, json_path, date_str)


def get_snapshot_by_date(date_str: str) -> dict | None:
    """A specific snapshot by date (YYYYMMDD), or None."""
    out_dir = get_snapshot_dir()
    json_path = out_dir / f"market_report_{date_str}.json"
    if not json_path.exists():
        return None
    return _read_snapshot(out_dir, json_path, date_str)

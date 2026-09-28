"""All environment-driven configuration for the web backend.

Env vars:
  PURRTFOLIO_DB          main SQLite DB (default ~/purrtfolio.db)
  MOMENTUM_DB            slim momentum DB (default: the main DB; see scanners/common.py)
  DB_RELEASE_BASE        override the GitHub Release URL the DBs are downloaded from
  CORS_ALLOWED_ORIGINS   comma-separated origins (default "*")
  SNAPSHOT_OUTPUT_DIR    macro snapshot output dir (absolute, or relative to the repo root)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

# Default to the user's home purrtfolio.db. Override with PURRTFOLIO_DB env var.
DEFAULT_DB = Path.home() / "purrtfolio.db"

# GitHub Release holding the production DBs. The tag is bumped daily by the
# DB release job, which regex-rewrites the db-vYYYY-MM-DD tag in THIS file
# (and render.yaml); override with
# DB_RELEASE_BASE if needed.
RELEASE_BASE = os.environ.get(
    "DB_RELEASE_BASE",
    "https://github.com/mcdawgzy/purrtfolio-tools/releases/download/db-v2026-09-28",
)
PURRTFOLIO_RELEASE_ASSET = f"{RELEASE_BASE}/purrtfolio.db.gz"
MOMENTUM_RELEASE_ASSET = f"{RELEASE_BASE}/momentum_data.db.gz"

# CORS: open by default for development; tighten via env vars in production
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",")

# Server-side cache for /api/meta (changes only on quarterly ingestion)
META_CACHE_TTL = 300  # 5 minutes


def get_db_path() -> Path:
    """Main DB path; read on every call so tests/tools can set the env late."""
    p = os.environ.get("PURRTFOLIO_DB")
    return Path(p) if p else DEFAULT_DB


def get_snapshot_dir() -> Path:
    """Directory where the macro pipeline saves its output (PNG + JSON).

    On Render (production), the macro output directory won't exist — the
    macro pipeline runs locally and copies its output into static/snapshots/
    via the cron job. On local dev, the pipeline writes to
    snapshots/macro/output/ directly.
    """
    # Prefer a SNAPSHOT_OUTPUT_DIR env var (production), fall back to the local
    # snapshots/macro/output directory relative to the project.
    env_dir = os.environ.get("SNAPSHOT_OUTPUT_DIR")
    if env_dir:
        p = Path(env_dir)
        return p if p.is_absolute() else ROOT / p
    # Local development: macro pipeline output
    local_dir = ROOT / "snapshots" / "macro" / "output"
    if local_dir.exists():
        return local_dir
    # Fallback: snapshots copied into static/ by the cron pipeline (Render)
    return STATIC_DIR / "snapshots"

"""SQLite connection helpers + download-if-missing logic for purrtfolio.db.

All reads are read-only (URI mode=ro) so concurrent reads are safe and won't
block the write cron jobs. If the DB file is missing it's downloaded from the
GitHub Release asset (see config.RELEASE_BASE). Replacing an *existing* file
that looks stale only happens when DB_AUTO_REFRESH=1 (set on Render), so a
local API never overwrites the cron host's master purrtfolio.db.
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import PURRTFOLIO_RELEASE_ASSET, get_db_path

logger = logging.getLogger(__name__)


def download_with_redirect(url: str, dest: str) -> None:
    """Download a URL to dest, following HTTP redirects.

    Tries curl first (available on Render Linux), falls back to
    urllib with a proper HTTPRedirectHandler.
    """
    curl = shutil.which("curl")
    if curl:
        result = subprocess.run(
            [curl, "-fSL", "-o", dest, url],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"curl failed (exit {result.returncode}): "
                f"{result.stderr.decode()[:500]}"
            )
        return
    # Fallback: urllib with redirect handler
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
    with opener.open(url) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


def gunzip(src: str | Path, dest: str | Path) -> None:
    with gzip.open(src, "rb") as f_in, open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


_REQUIRED_TABLES = ("price_history", "price_momentum_signals", "corr_matrices",
                    "earnings_revision_momentum", "crowded_trades")


def _db_has_new_tables(db_path: Path) -> bool:
    """Check whether the existing DB contains the new scanner tables
    AND has actual data (not just empty schema from a partial build)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(_REQUIRED_TABLES) <= names:
                return False
            return all(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in _REQUIRED_TABLES)
        finally:
            conn.close()
    except Exception:
        return False


_db_validated_path: str | None = None
_download_lock = threading.Lock()


def _auto_refresh_enabled() -> bool:
    return os.environ.get("DB_AUTO_REFRESH", "").lower() in ("1", "true", "yes")


def _download_db_if_needed(db_path: Path) -> Path:
    """Download DB from GitHub Release if it doesn't exist locally.

    The release asset is gzip-compressed (purrtfolio.db.gz) to keep the
    download fast on Render's free tier. We decompress on the fly.

    With DB_AUTO_REFRESH=1 (Render), also re-downloads if the existing DB
    lacks the scanner tables (stale build). Without it, an existing file is
    never replaced.

    Caches the validation result per-process so we don't re-open 4 SQLite
    connections on every request just to verify the DB hasn't changed.
    """
    global _db_validated_path
    if _db_validated_path == str(db_path) and db_path.exists():
        return db_path
    with _download_lock:  # concurrent first requests must not race the download
        if _db_validated_path == str(db_path) and db_path.exists():
            return db_path
        if db_path.exists() and (not _auto_refresh_enabled() or _db_has_new_tables(db_path)):
            _db_validated_path = str(db_path)
            return db_path
        _fetch_release_db(db_path)
        _db_validated_path = str(db_path)
        return db_path


def _fetch_release_db(db_path: Path) -> None:
    """Download + decompress the release DB and atomically swap it into place."""
    logger.info(f"DB stale or missing at {db_path}, downloading fresh copy...")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Download the .gz file to a temp path, decompress, then swap
    gz_path = str(db_path) + ".gz.new"
    tmp_db = str(db_path) + ".new"
    download_with_redirect(PURRTFOLIO_RELEASE_ASSET, gz_path)
    logger.info(f"Downloaded ({os.path.getsize(gz_path) / 1e6:.1f}MB compressed)")

    gunzip(gz_path, tmp_db)
    os.remove(gz_path)
    logger.info(f"Decompressed DB ({os.path.getsize(tmp_db) / 1e6:.1f}MB)")

    # Replace the old DB atomically (os.replace is atomic on Linux/Windows)
    if db_path.exists():
        os.chmod(db_path, 0o644)  # ensure writable
    os.replace(tmp_db, db_path)
    logger.info(f"DB swapped to {db_path}")


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Read-only connection. Use as: with db_conn() as c: c.execute(...)"""
    path = _download_db_if_needed(get_db_path())
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    # Open read-only (no write contention with cron jobs)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def row_dicts(cur_or_rows) -> list[dict[str, Any]]:
    """Accept either a Cursor (still pending fetchall) or an iterable of Rows."""
    rows = cur_or_rows
    if hasattr(rows, "fetchall"):
        rows = rows.fetchall()
    return [dict(r) for r in rows]


def table_exists(c: sqlite3.Connection, name: str) -> bool:
    """Check if a table exists (for graceful degradation when DB not yet populated)."""
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None

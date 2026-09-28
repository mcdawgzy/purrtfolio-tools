"""SQLite connection helpers + download-if-missing logic for purrtfolio.db.

All reads are read-only (URI mode=ro) so concurrent reads are safe and won't
block the write cron jobs. On first use (in production on Render), if the DB
is missing locally or stale, it's downloaded from the GitHub Release asset
(see config.RELEASE_BASE).
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
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


def _db_has_new_tables(db_path: Path) -> bool:
    """Check whether the existing DB contains the new scanner tables
    AND has actual data (not just empty schema from a partial build)."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        names = {t[0] for t in tables}
        required = {"price_history", "price_momentum_signals", "corr_matrices",
                    "earnings_revision_momentum", "crowded_trades"}
        if not required.issubset(names):
            return False
        # Verify the tables have data
        for tbl in required:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            conn.close()
            if count == 0:
                return False
        return True
    except Exception:
        return False


_db_validated_path: str | None = None


def _download_db_if_needed(db_path: Path) -> Path:
    """Download DB from GitHub Release if it doesn't exist locally.

    The release asset is gzip-compressed (purrtfolio.db.gz) to keep the
    download fast on Render's free tier. We decompress on the fly.

    Also re-downloads if the existing DB lacks the new tables (stale build).

    Caches the validation result per-process so we don't re-open 4 SQLite
    connections on every request just to verify the DB hasn't changed.
    """
    global _db_validated_path
    if _db_validated_path == str(db_path) and db_path.exists() and db_path.stat().st_size > 10_000_000:
        return db_path
    if db_path.exists() and _db_has_new_tables(db_path):
        _db_validated_path = str(db_path)
        return db_path
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
    return db_path


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


def writable_conn() -> sqlite3.Connection:
    """Plain read-write connection to the main DB (schema init by cron scripts).
    Deliberately skips the download check."""
    return sqlite3.connect(str(get_db_path()))


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

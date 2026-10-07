#!/usr/bin/env python3
"""Publish a new GitHub Release for the unified purrtfolio.db.

Runs as a no_agent Hermes cron job (script-only). After all daily ingest
cron jobs finish, this script:

  1. Queries purrtfolio.db for the latest data date (MAX across key tables)
  2. Compresses purrtfolio.db -> purrtfolio.db.gz (~67MB from 511MB)
  3. Builds a slim momentum DB (price_history + corr_matrices only) ->
     momentum_data.db.gz (~0.3MB) for Render cold-start fast path
  4. Creates a GitHub Release tagged db-vYYYY-MM-DD with both assets
  5. Updates version tag references in src/config.py and render.yaml
     (audit_qa_bot.py reads the tag from src/config.py)
  6. Commits just those files and pushes to master, which redeploys Render
     with the new release (set PUBLISH_PUSH=0 to skip, e.g. for manual runs)

Idempotent: skips release creation if the tag already exists.
Only updates source references when the tag changes.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import gzip
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date

# ── Paths ─────────────────────────────────────────────────────────────────
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))
WEBROOT = REPO
GITHUB_REPO = "mcdawgzy/purrtfolio-tools"

# Files that hardcode the release tag/URL — updated when tag changes
TAG_REFS = [
    (WEBROOT / "src" / "config.py", r"db-v\d{4}-\d{2}-\d{2}", "db-v{tag}"),
    (WEBROOT / "render.yaml", r"db-v\d{4}-\d{2}-\d{2}", "db-v{tag}"),
]


def log(msg: str):
    print(f"[publish_db_release] {msg}", flush=True)


def get_latest_data_date(db_path: Path) -> str:
    """Return the latest data date across key tables as YYYY-MM-DD."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        # Conditionally include crowded_trades — it may not exist in older DBs
        ct_clause = ""
        has_ct = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='crowded_trades'"
        ).fetchone()
        if has_ct:
            ct_clause = " UNION ALL SELECT MAX(date) AS d FROM crowded_trades"
        rows = conn.execute("""
            SELECT MAX(d) FROM (
                SELECT MAX(created_at) AS d FROM filings_13f
                UNION ALL SELECT MAX(created_at) AS d FROM holdings_13f
                UNION ALL SELECT MAX(completed_at) AS d FROM ingestion_log_si
                UNION ALL SELECT MAX(filing_date) AS d FROM insider_submissions
                UNION ALL SELECT MAX(date) AS d FROM price_history
                UNION ALL SELECT MAX(updated_at) AS d FROM corr_matrices
                UNION ALL SELECT MAX(enriched_at) AS d FROM ticker_factors
                UNION ALL SELECT MAX(date(datetime(retrieved_at, 'localtime'))) AS d FROM news_headlines
                UNION ALL SELECT MAX(date) AS d FROM ticker_news_sentiment
                UNION ALL SELECT MAX(date) AS d FROM unusual_activity
                UNION ALL SELECT MAX(date) AS d FROM iv_rank
                UNION ALL SELECT MAX(date) AS d FROM put_call_ratio
                UNION ALL SELECT MAX(created_at) AS d FROM earnings_revision_momentum
                {ct}
            )
        """.format(ct=ct_clause)).fetchone()
        d = rows[0]
        if d is None:
            raise RuntimeError("No data found in any table")
        return d[:10]
    finally:
        conn.close()


def compress_db(src_db: Path, dest_gz: Path):
    """Compress a SQLite DB to .gz.

    Checkpoints any WAL before reading so that recent writes
    (which live in the WAL file, not the main DB) are merged
    into the main DB file before compression.
    """
    log(f"Compressing {src_db.name} -> {dest_gz.name}...")
    _checkpoint_wal(src_db)
    with open(src_db, "rb") as f_in, gzip.open(dest_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    log(f"  {dest_gz.stat().st_size / 1e6:.1f}MB compressed")


def _checkpoint_wal(db_path: Path):
    """Flush WAL pages into the main DB file so open() sees all changes."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()
        conn.close()
        log(f"  WAL checkpointed for {db_path.name}")
    except Exception as e:
        log(f"  WAL checkpoint skipped: {e}")


def build_slim_momentum_db(src_db: Path, dest_db: Path):
    """Extract price_history + corr_matrices + price_momentum_signals + tickers into a slim standalone DB.

    The slim DB lets Render's api.py cold-start quickly without
    downloading the 67MB main DB asset every time (per-process cache check).
    Includes price_momentum_signals so momentum signal endpoints work, plus
    tickers for JOINs in signal queries.
    """
    log(f"Building slim momentum DB from {src_db.name}...")
    dest_db.unlink(missing_ok=True)
    # uri=True so ATTACH DATABASE can parse file: URIs (for read-only mode)
    dst = sqlite3.connect(str(dest_db), uri=True)
    # ATTACH source DB read-only via URI (forward-slash path for URI compliance)
    src_uri = f"file:{src_db.as_posix()}?mode=ro"
    dst.execute(f"ATTACH DATABASE '{src_uri}' AS src")
    try:
        for table in ("price_history", "corr_matrices", "price_momentum_signals", "tickers"):
            try:
                cnt = dst.execute(f"SELECT COUNT(*) FROM src.{table}").fetchone()[0]
                # Create table with data (CREATE TABLE AS SELECT copies schema + data)
                dst.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{table}")
                # Copy indexes/triggers from source
                for ddl_row in dst.execute(
                    "SELECT sql FROM src.sqlite_master "
                    "WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL",
                    (table,)
                ).fetchall():
                    if ddl_row[0]:
                        try:
                            dst.execute(ddl_row[0])
                        except sqlite3.OperationalError:
                            pass  # index name conflict, skip
                log(f"  {table}: {cnt:,} rows copied")
            except sqlite3.OperationalError:
                log(f"  {table}: table not found, skipping")
        dst.commit()
    finally:
        dst.execute("DETACH DATABASE src")
        dst.close()
    log(f"  Slim DB: {dest_db.stat().st_size / 1e6:.1f}MB")


def gh_release_exists(tag: str) -> bool:
    """Check if a GitHub Release with the given tag already exists."""
    result = subprocess.run(
        ["gh", "release", "view", f"v{tag}" if not tag.startswith("db-") else tag,
         "--repo", GITHUB_REPO, "--json", "id", "-q", ".id"],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode == 0 and result.stdout.strip()


def create_gh_release(tag: str, assets: list[str]):
    """Create a GitHub Release with assets via gh CLI.

    Uses: gh release create <tag> --repo <repo> <assets...>
    """
    log(f"Creating GitHub Release: {tag}")
    args = [
        "gh", "release", "create", tag,
        "--repo", GITHUB_REPO,
        "--title", f"DB {tag.replace('db-v', '')}",
        "--notes", f"Auto-published DB snapshot. Data through {tag.replace('db-v', '')}.",
    ]
    for asset in assets:
        args.append(asset)
    result = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log(f"  ERROR: {result.stderr.strip()[:500]}")
        return False
    log(f"  Release created: {result.stdout.strip()[:200]}")
    return True


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(WEBROOT), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def deploy_tag_refs(new_tag: str) -> bool:
    """Commit the tag-reference files and push them to master (Render autodeploys
    on push). Only those files are committed; other working-tree changes are
    left alone. Safe to re-run: a commit left unpushed by an earlier run is
    pushed on the next one."""
    if os.environ.get("PUBLISH_PUSH", "1") == "0":
        log("PUBLISH_PUSH=0 — not committing/pushing tag refs")
        return True
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "master":
        log(f"Checkout is on '{branch}', not master — not pushing")
        return False

    files = [str(f.relative_to(WEBROOT)) for f, _, _ in TAG_REFS if f.exists()]
    if _git("status", "--porcelain", "--", *files).stdout.strip():
        commit = _git("commit", "-m", f"chore: deploy DB release {new_tag}", "-o", "--", *files)
        if commit.returncode != 0:
            log(f"Commit failed: {(commit.stdout + commit.stderr).strip()[:300]}")
            return False
    _git("fetch", "-q", "origin", "master")
    if not _git("rev-list", "origin/master..HEAD", "--", *files).stdout.strip():
        log("Tag refs already on origin/master — nothing to deploy")
        return True

    for attempt in (1, 2):
        # Never autostash a local edit into a file that also changed upstream:
        # the stash pop would leave conflict markers in the cron checkout.
        _git("fetch", "-q", "origin", "master")
        dirty = {line[3:] for line in _git("status", "--porcelain").stdout.splitlines()
                 if not line.startswith("??")}
        upstream = set(_git("diff", "--name-only", "HEAD...origin/master").stdout.split())
        if dirty & upstream:
            log(f"Local changes overlap upstream ({', '.join(sorted(dirty & upstream))}) — "
                "not rebasing; committed locally, push needs a manual pull")
            return False
        pull = _git("pull", "--rebase", "--autostash", "origin", "master")
        if pull.returncode != 0:
            _git("rebase", "--abort")
            log(f"Rebase onto origin/master failed: {pull.stderr.strip()[:300]}")
            return False
        push = _git("push", "origin", "HEAD:master")
        if push.returncode == 0:
            log(f"Pushed tag refs for {new_tag} — Render will redeploy")
            return True
        log(f"Push attempt {attempt} failed: {push.stderr.strip()[:300]}")
    return False


def update_tag_refs(new_tag: str):
    """Update all files that reference the old release tag."""
    log(f"Updating version references to {new_tag}...")
    pattern = re.compile(r"db-v\d{4}-\d{2}-\d{2}")
    updated = []
    for filepath, _regex, replacement_template in TAG_REFS:
        if not filepath.exists():
            log(f"  SKIP (not found): {filepath}")
            continue
        content = filepath.read_text(errors="replace")
        matches = pattern.findall(content)
        if not matches:
            log(f"  No tag reference found: {filepath}")
            continue
        new_content = pattern.sub(new_tag, content)
        filepath.write_text(new_content)
        updated.append(str(filepath))
        log(f"  Updated {filepath}: {matches} -> {new_tag}")
    return updated


def main() -> int:
    import tempfile, shutil as _shutil
    # Use a unique temp dir per run to avoid file-lock collisions on Windows
    tmpdir = Path(tempfile.mkdtemp(prefix="publish_db_"))
    try:
        # 1. Determine the latest data date
        latest_date = get_latest_data_date(DB_PATH)
        new_tag = f"db-v{latest_date}"
        log(f"Latest data date: {latest_date} -> Release tag: {new_tag}")

        # 2. Check if release already exists (idempotent)
        if gh_release_exists(new_tag):
            log(f"Release {new_tag} already exists — skipping creation.")
            # Still update source references in case they're stale, and retry
            # the deploy push if an earlier run couldn't complete it
            update_tag_refs(new_tag)
            deployed = deploy_tag_refs(new_tag)
            print(f"Status: {'ok' if deployed else 'error'}")
            print(f"Release: {new_tag} (already existed)")
            print(f"Deploy: {'pushed/up to date' if deployed else 'FAILED to push tag refs'}")
            return 0 if deployed else 1

        # 3. Compress main DB
        main_gz = tmpdir / "purrtfolio.db.gz"
        compress_db(DB_PATH, main_gz)

        # 4. Build slim momentum DB
        slim_db = tmpdir / "momentum_data.db"
        build_slim_momentum_db(DB_PATH, slim_db)
        slim_gz = tmpdir / "momentum_data.db.gz"
        compress_db(slim_db, slim_gz)
        slim_db.unlink(missing_ok=True)

        # 5. Create GitHub Release with both assets
        assets = [str(main_gz), str(slim_gz)]
        if not create_gh_release(new_tag, assets):
            log("Release creation failed — cleaning up temp files")
            print(f"Status: error")
            print(f"Error: GitHub Release creation failed")
            return 1

        # 6. Update version references in source files
        updated = update_tag_refs(new_tag)

        # 7. Commit + push the new tag so Render serves this release
        deployed = deploy_tag_refs(new_tag)

        print(f"Status: {'ok' if deployed else 'error'}")
        print(f"Release: {new_tag}")
        print(f"Deploy: {'pushed' if deployed else 'FAILED to push tag refs'}")
        print(f"Files updated: {len(updated)}")
        for f in updated:
            print(f"  - {f}")
        return 0 if deployed else 1

    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print(f"Status: error")
        print(f"Error: {e}")
        return 1
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    # Project retired 2026-10-08: every job is a no-op. Pause it in Hermes.
    print("Status: ok - purrtfolio retired, job skipped")
    sys.exit(0)
    sys.exit(main())

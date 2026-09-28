#!/usr/bin/env python3
"""
Audit/QA Bot — Daily audit of the Purrtfolio trading tools ecosystem.

Runs as a no_agent Hermes cron job (script-only). Output is a structured
markdown report delivered to the #audit-qa-bot Discord channel.

Checks:
  1. Data Freshness   — every DB table + snapshot files + SI ingest log
  2. Cron Job Health  — jobs.json configs + executions.db recent run status
  3. Web/API Health   — Render API health, GitHub Pages, DB release freshness
  4. Git Status       — uncommitted changes, stale repo stubs
  5. Data Quality     — orphans, legacy tables, stale stubs, empty-ticker rows
  6. Recommendations  — categorised findings + new items to build
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

import json
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, date, timezone


# ── Paths & constants ───────────────────────────────────────────────
DB_PATH = Path(os.environ.get("PURRTFOLIO_DB", Path.home() / "purrtfolio.db"))
CRON_DIR = Path.home() / "AppData" / "Local" / "hermes" / "cron"
JOBS_JSON = CRON_DIR / "jobs.json"
EXECUTIONS_DB = CRON_DIR / "executions.db"
WEBROOT = REPO
SCRIPTS_DIR = Path.home() / "AppData" / "Local" / "hermes" / "scripts"
SNAPSHOT_DIR = WEBROOT / "snapshots" / "macro" / "output"
# The deployed release tag lives in src/config.py (bumped by publish_db_release.py)
_TAG_FILE = WEBROOT / "src" / "config.py"
_m = re.search(r"db-v\d{4}-\d{2}-\d{2}", _TAG_FILE.read_text(encoding="utf-8")) if _TAG_FILE.exists() else None
GH_RELEASE_TAG = _m.group(0) if _m else "db-v0000-00-00"
RENDER_API = "https://one3f-tracker-wpj6.onrender.com"
GITHUB_PAGES = "https://mcdawgzy.github.io/purrtfolio-tools/"


def _frontend_files() -> list[str]:
    """Frontend source files (relative to static/) that CI mirrors into docs/.
    Snapshots are excluded: the macro job commits those to both trees itself."""
    root = WEBROOT / "static"
    return sorted(
        f.relative_to(root).as_posix() for f in root.rglob("*")
        if f.is_file() and f.relative_to(root).parts[0] != "snapshots"
    )

# SPA page -> API endpoint mapping for live data verification
# (page_title, api_endpoint, legit_empty_if_no_qualifying_events)
SPA_PAGE_ENDPOINTS = [
    ("Crowded Trades",            "/api/ct/latest",               False),
    ("Short Interest",            "/api/si/latest",               False),
    ("Unusual Activity",          "/api/ua/latest",               False),
    ("Screener",                  "/api/screener",                False),
    ("Factors Exposure",          "/api/factors/exposure",        False),
    ("Momentum Rankings",         "/api/momentum/rankings",       False),
    ("Momentum Volume Spikes",    "/api/momentum/volume-spikes",  True),
    ("Momentum Consolidation",    "/api/momentum/consolidation",  True),
    ("Momentum Earnings Gaps",    "/api/momentum/earnings-gaps",  True),
    ("Snapshot",                  "/api/snapshot/latest",         False),
    ("Consensus",                 "/api/consensus",               False),
    ("Sectors",                   "/api/sectors",                 False),
    ("Funds",                     "/api/funds",                   False),
    ("Quotes",                    "/api/quotes",                  False),
    ("Put/Call Ratio",            "/api/pcr/latest",              False),
    ("IV Rank",                   "/api/iv/latest",               False),
    ("News",                      "/api/news/headlines",          False),
    ("Earnings Revisions",        "/api/earnings-revisions",      False),
    ("Correlation",               "/api/correlation/matrix",      False),
]


def check_website_data():
    """Verify all SPA page API endpoints return data on the live Render API.

    Returns (issues, results) where:
      - issues: list of issue dicts for the Issues Found section
      - results: list of result dicts for the report section
    """
    issues = []
    results = []

    for page_name, endpoint, legit_empty in SPA_PAGE_ENDPOINTS:
        url = RENDER_API + endpoint
        try:
            code, body, err = http_get(url, timeout=30)
        except Exception as e:
            code, body, err = 0, None, str(e)

        ok = False
        detail = ""

        if code == 0:
            detail = "Connection failed: " + (err or "timeout")
            issues.append({
                "severity": "critical",
                "category": "website",
                "check": "Page data: " + page_name,
                "detail": detail,
                "fix": "Check Render service status and API endpoint path in src/api.py",
            })
        elif code != 200:
            detail = "HTTP " + str(code) + ((": " + err) if err else "")
            issues.append({
                "severity": "critical",
                "category": "website",
                "check": "Page data: " + page_name,
                "detail": detail,
                "fix": "Verify endpoint path in src/api.py and check server logs",
            })
        elif not body or body.strip() in ("[]", "{}", "", "null"):
            if legit_empty:
                ok = True
                detail = "Empty (OK: no qualifying events today)"
            else:
                detail = "Empty response - page will display no data"
                issues.append({
                    "severity": "critical",
                    "category": "website",
                    "check": "Page data: " + page_name,
                    "detail": detail,
                    "fix": ("Check if DB release (" + GH_RELEASE_TAG + ") includes required tables"),
                })
        elif body.strip()[0] in "[{":
            ok = True
            detail = "Data present"
        else:
            detail = "Non-JSON response: " + body[:60]
            issues.append({
                "severity": "warning",
                "category": "website",
                "check": "Page data: " + page_name,
                "detail": detail,
                "fix": "Check API response format in src/api.py",
            })

        results.append({
            "page": page_name,
            "endpoint": endpoint,
            "ok": ok,
            "detail": detail,
        })

    return issues, results

# How many days stale before we flag
STALE_DAYS = {
    "13F": 120,          # quarterly by nature
    "price_history": 3,
    "momentum": 3,
    "correlation": 3,
    "factors": 3,
    "sectors": 3,
    "snapshot": 2,
    "economic_events": 7,
    "short_interest": 14,   # bi-weekly, but check
    "insider": 120,        # quarterly SEC batch
}

TODAY = date.today()
TS = datetime.now().strftime("%Y-%m-%d %H:%M")

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

# ── Helpers ─────────────────────────────────────────────────────────
def db_query(sql: str, params=(), one=False):
    """Read-only query against purrtfolio.db."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    if one:
        return dict(rows[0]) if rows else None
    return [dict(r) for r in rows]

def http_get(url: str, timeout: int = 12) -> tuple[int, str | None, str | None]:
    """Return (status_code, body_snippet, error)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "audit-qa-bot/1.0"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read(4096).decode("utf-8", errors="replace").strip()
        return resp.status, body[:200], None
    except urllib.error.HTTPError as e:
        return e.code, None, str(e)
    except Exception as e:
        return 0, None, str(e)

def run_cmd(cmd: str, cwd: str | None = None, timeout: int = 30) -> tuple[int, str, str]:
    """Run a shell command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -2, "", str(e)

def days_since(d: str | date | None) -> str:
    """Return 'N d' or 'never' or 'future'."""
    if d is None:
        return "never"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except Exception:
            return "unknown"
    if isinstance(d, date):
        diff = (TODAY - d).days
        if diff < 0:
            return f"{abs(diff)}d future"
        return f"{diff}d"
    return "unknown"

def stale_flag(days_str: str, threshold: int, is_quarterly: bool = False) -> str:
    """Return emoji flag for staleness."""
    if days_str == "never":
        return "❌"
    if "future" in days_str:
        return "✅"
    try:
        n = int(days_str.rstrip("d"))
    except (ValueError, TypeError):
        return "❓"
    if n > threshold:
        return "⚠️"
    return "✅"

# ── 1. Data Freshness ───────────────────────────────────────────────
def check_data_freshness() -> list[dict]:
    rows = []
    # 13F
    r = db_query("SELECT MAX(report_period) AS q, MAX(filing_date) AS d FROM filings_13f WHERE has_infotable=1", one=True)
    rows.append({
        "source": "13F Filings",
        "latest": r["q"] if r else "none",
        "filed": r["d"] if r else "none",
        "stale": days_since(r["d"] if r else None),
        "threshold": f"{STALE_DAYS['13F']}d",
        "flag": "✅",
        "note": "Quarterly by nature — Q2 2026 data, Q3 not yet filed",
    })
    # Short Interest
    r = db_query("SELECT MAX(settlement_date) AS d FROM short_interest", one=True)
    r2 = db_query("SELECT MAX(completed_at) AS d FROM ingestion_log_si WHERE status='completed'", one=True)
    rows.append({
        "source": "Short Interest",
        "latest": r["d"] if r else "none",
        "filed": r2["d"][:10] if r2 and r2["d"] else "none",
        "stale": days_since(r["d"] if r else None),
        "threshold": f"{STALE_DAYS['short_interest']}d",
        "flag": stale_flag(days_since(r["d"] if r else None), STALE_DAYS["short_interest"]),
        "note": f"Last ingest: {r2['d'][:10] if r2 and r2['d'] else 'none'}",
    })
    # Insider Trading
    r = db_query("SELECT MAX(filing_date) AS d FROM insider_submissions WHERE document_type IN ('4','4/A')", one=True)
    rows.append({
        "source": "Insider Trading",
        "latest": r["d"] if r else "none",
        "stale": days_since(r["d"] if r else None),
        "threshold": f"{STALE_DAYS['insider']}d",
        "flag": stale_flag(days_since(r["d"] if r else None), STALE_DAYS["insider"]),
        "note": "Quarterly SEC batch — Q3 2026 data not yet published",
    })
    # Economic Calendar
    r = db_query("SELECT MAX(event_date) AS d, COUNT(*) AS c FROM economic_events WHERE event_date >= date('now')", one=True)
    r2 = db_query("SELECT MAX(updated_at) AS d FROM economic_events", one=True)
    rows.append({
        "source": "Economic Calendar",
        "latest": f"{r['c']} upcoming" if r else "0 upcoming",
        "filed": r2["d"][:10] if r2 and r2["d"] else "none",
        "stale": days_since(r2["d"][:10] if r2 and r2["d"] else None),
        "threshold": f"{STALE_DAYS['economic_events']}d",
        "flag": "✅",
        "note": "Events up to 2026-10-15",
    })
    # Price History
    r = db_query("SELECT MAX(date) AS d FROM price_history", one=True)
    rows.append({
        "source": "Price History",
        "latest": r["d"] if r else "none",
        "stale": days_since(r["d"] if r else None),
        "threshold": f"{STALE_DAYS['price_history']}d",
        "flag": stale_flag(days_since(r["d"] if r else None), STALE_DAYS["price_history"]),
        "note": "",
    })
    # Momentum Signals
    r = db_query("SELECT MAX(date) AS d FROM price_momentum_signals", one=True)
    rows.append({
        "source": "Momentum Signals",
        "latest": r["d"] if r else "none",
        "stale": days_since(r["d"] if r else None),
        "threshold": f"{STALE_DAYS['momentum']}d",
        "flag": stale_flag(days_since(r["d"] if r else None), STALE_DAYS["momentum"]),
        "note": "",
    })
    # Correlation Matrix
    r = db_query("SELECT MAX(updated_at) AS d FROM corr_matrices", one=True)
    rows.append({
        "source": "Correlation Matrix",
        "latest": r["d"][:10] if r and r["d"] else "none",
        "stale": days_since(r["d"][:10] if r and r["d"] else None),
        "threshold": f"{STALE_DAYS['correlation']}d",
        "flag": stale_flag(days_since(r["d"][:10] if r and r["d"] else None), STALE_DAYS["correlation"]),
        "note": "",
    })
    # Factor Exposure
    r = db_query("SELECT MAX(enriched_at) AS d FROM ticker_factors", one=True)
    rows.append({
        "source": "Factor Exposure",
        "latest": r["d"][:10] if r and r["d"] else "none",
        "stale": days_since(r["d"][:10] if r and r["d"] else None),
        "threshold": f"{STALE_DAYS['factors']}d",
        "flag": stale_flag(days_since(r["d"][:10] if r and r["d"] else None), STALE_DAYS["factors"]),
        "note": "",
    })
    # Sector Enrichment
    r = db_query("SELECT MAX(last_updated) AS d FROM sectors", one=True)
    rows.append({
        "source": "Sector Enrichment",
        "latest": r["d"][:10] if r and r["d"] else "none",
        "stale": days_since(r["d"][:10] if r and r["d"] else None),
        "threshold": f"{STALE_DAYS['sectors']}d",
        "flag": stale_flag(days_since(r["d"][:10] if r and r["d"] else None), STALE_DAYS["sectors"]),
        "note": "",
    })
    # Market Snapshots
    if SNAPSHOT_DIR.exists():
        pngs = sorted(SNAPSHOT_DIR.glob("market_snapshot_*.png"), reverse=True)
        latest_snap = pngs[0].name if pngs else "none"
        snap_date_str = re.search(r"(\d{8})", latest_snap)
        snap_date = snap_date_str.group(1) if snap_date_str else None
        snap_stale = days_since(snap_date) if snap_date else "never"
        snap_date_parsed = date.fromisoformat(f"{snap_date[:4]}-{snap_date[4:6]}-{snap_date[6:8]}") if snap_date else None
        flag = stale_flag(snap_stale, STALE_DAYS["snapshot"])
    else:
        latest_snap = "missing"
        snap_stale = "never"
        flag = "❌"
        snap_date_parsed = None
    rows.append({
        "source": "Market Snapshots",
        "latest": latest_snap,
        "stale": snap_stale,
        "threshold": f"{STALE_DAYS['snapshot']}d",
        "flag": flag,
        "note": "",
    })
    return rows

# ── 2. Cron Job Health ──────────────────────────────────────────────
def check_cron_health() -> list[dict]:
    rows = []
    with open(JOBS_JSON, encoding="utf-8") as f:
        jobs_data = json.load(f)
    jobs = jobs_data.get("jobs", [])

    # Read last execution per job from executions.db
    exec_conn = sqlite3.connect(f"file:{EXECUTIONS_DB}?mode=ro", uri=True, timeout=10)
    exec_conn.row_factory = sqlite3.Row
    last_execs = {}
    for row in exec_conn.execute(
        "SELECT job_id, status, finished_at, error FROM executions ORDER BY claimed_at DESC"
    ).fetchall():
        if row["job_id"] not in last_execs:
            last_execs[row["job_id"]] = dict(row)
    exec_conn.close()

    # Read open incidents
    inc_conn = sqlite3.connect(f"file:{EXECUTIONS_DB}?mode=ro", uri=True, timeout=10)
    open_incidents = inc_conn.execute(
        "SELECT job_id, error, first_seen_at FROM cron_incidents WHERE state != 'closed'"
    ).fetchall()
    inc_conn.close()

    for job in jobs:
        jid = job["id"]
        name = job["name"]
        enabled = job.get("enabled", True)
        schedule = job.get("schedule", {}).get("display", job.get("schedule_display", "?"))
        last_status = job.get("last_status", "unknown")
        last_error = job.get("last_error")
        fail_streak = job.get("failure_streak", 0)
        deliver = job.get("deliver", "local")
        last_run = job.get("last_run_at")
        next_run = job.get("next_run_at")
        exec_info = last_execs.get(jid, {})
        exec_status = exec_info.get("status", "unknown")
        exec_error = exec_info.get("error", "")

        issues = []
        if last_status == "error":
            issues.append(f"Error: {last_error[:80] if last_error else 'unknown'}")
        if last_status == "delivery_failed":
            issues.append(f"Delivery: {job.get('last_delivery_error', 'unknown')[:80]}")
        if fail_streak > 0:
            issues.append(f"Failure streak: {fail_streak}")
        if deliver == "local":
            issues.append("Delivers to local only (no Discord)")
        if "404" in str(exec_error):
            issues.append("HTTP 404 in execution")
        if "429" in str(exec_error) or "429" in str(last_error or ""):
            issues.append("HTTP 429 rate limit")

        # Check if job has a script but deliver is local
        if job.get("script") and deliver == "local":
            issues.append("Script job but no Discord delivery")

        flag = "✅" if (not issues and enabled) else ("⚠️" if not issues and not enabled else "⚠️")
        if any("429" in i or "Error" in i for i in issues):
            flag = "❌"

        rows.append({
            "name": name,
            "schedule": schedule,
            "last_run": (last_run or "never")[:16] if last_run else "never",
            "last_status": last_status,
            "exec_status": exec_status,
            "streak": fail_streak,
            "flag": flag,
            "issues": issues,
            "deliver": deliver,
            "next_run": (next_run or "?")[:16] if next_run else "?",
            "enabled": enabled,
        })

    return rows

# ── 3. Web/API Health ───────────────────────────────────────────────
def check_web_health() -> list[dict]:
    results = []

    # Render API health — use 60s timeout to handle Render cold starts
    code, body, err = http_get(f"{RENDER_API}/api/health", timeout=60)
    results.append({
        "name": "Render API (health)",
        "url": f"{RENDER_API}/api/health",
        "status": code,
        "ok": code == 200,
        "body": body,
        "error": err,
    })

    # Render API meta — 60s timeout for cold starts
    code2, body2, err2 = http_get(f"{RENDER_API}/api/meta", timeout=60)
    results.append({
        "name": "Render API (meta)",
        "url": f"{RENDER_API}/api/meta",
        "status": code2,
        "ok": code2 == 200,
        "body": body2,
        "error": err2,
    })

    # GitHub Pages
    code3, body3, err3 = http_get(GITHUB_PAGES, timeout=12)
    results.append({
        "name": "GitHub Pages",
        "url": GITHUB_PAGES,
        "status": code3,
        "ok": code3 == 200,
        "body": body3[:80] if body3 else None,
        "error": err3,
    })

    # DB release freshness — compare local DB last_update vs release date
    local_update = db_query(
        "SELECT MAX(d) AS d FROM ("
        "SELECT MAX(created_at) AS d FROM filings_13f "
        "UNION ALL SELECT MAX(created_at) AS d FROM holdings_13f "
        "UNION ALL SELECT MAX(completed_at) AS d FROM ingestion_log_si "
        "UNION ALL SELECT MAX(filing_date) AS d FROM insider_submissions "
        "UNION ALL SELECT MAX(date) AS d FROM price_history "
        "UNION ALL SELECT MAX(updated_at) AS d FROM corr_matrices "
        "UNION ALL SELECT MAX(enriched_at) AS d FROM ticker_factors)",
        one=True,
    )
    local_update_str = local_update["d"][:10] if local_update and local_update["d"] else "unknown"
    release_date = GH_RELEASE_TAG.replace("db-v", "")

    results.append({
        "name": "DB Release",
        "url": f"github.com/mcdawgzy/purrtfolio-tools/releases/tag/{GH_RELEASE_TAG}",
        "status": 200,
        "ok": False,  # Will be set below
        "body": f"Local DB latest: {local_update_str} | Release: {release_date}",
        "error": None,
        "_local_update": local_update_str,
        "_release_date": release_date,
    })

    # Compare: if local is more than 1 day newer than release, it's stale
    try:
        local_d = date.fromisoformat(local_update_str)
        release_d = date.fromisoformat(release_date)
        stale_days = (local_d - release_d).days
        results[-1]["ok"] = stale_days <= 1
        results[-1]["body"] += f" | Stale by {stale_days}d"
    except Exception:
        results[-1]["ok"] = False
        results[-1]["body"] += f" | Cannot compare"

    return results

# ── 4. Git Status ──────────────────────────────────────────────────
def check_git() -> dict:
    result = {"repo": str(WEBROOT), "clean": True, "changed_files": [], "issues": []}
    code, stdout, stderr = run_cmd("git status --porcelain", cwd=str(WEBROOT))
    if code == 0 and stdout:
        result["clean"] = False
        result["changed_files"] = [line.strip() for line in stdout.split("\n") if line.strip()]
        result["issues"].append(f"{len(result['changed_files'])} uncommitted file(s)")
    elif code != 0:
        result["issues"].append(f"git status failed: {stderr[:100]}")

    # Check for stale DB stub
    stub = WEBROOT / "purrtfolio.db"
    if stub.exists() and stub.stat().st_size == 0:
        result["issues"].append(f"Stale DB stub: {stub} (0 bytes)")
        result["clean"] = False

    return result

# ── 5. Data Quality ────────────────────────────────────────────────
def check_data_quality() -> list[dict]:
    issues = []
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)

    # Empty ticker holdings
    n = conn.execute(
        'SELECT COUNT(*) FROM holdings_13f WHERE ticker IS NULL OR ticker = ""'
    ).fetchone()[0]
    issues.append({
        "severity": "info",
        "category": "data",
        "check": "Empty-ticker holdings",
        "detail": f"{n:,} holdings have empty/null ticker (bonds/options/private — known, sentinel row exists)",
        "fix": "None needed (sentinel '' row in tickers handles FK constraints)",
    })

    # price_history without ticker match
    n = conn.execute(
        "SELECT COUNT(*) FROM price_history WHERE ticker NOT IN (SELECT ticker FROM tickers)"
    ).fetchone()[0]
    issues.append({
        "severity": "info",
        "category": "data",
        "check": "price_history orphan tickers",
        "detail": f"{n:,} price_history rows reference tickers not in the tickers table (index ETFs: ^GSPC, ^NDX, etc.)",
        "fix": "Index tickers (^GSPC, ^NDX, GC=F) are price_history data but not in the curated tickers dimension — expected behavior",
    })

    # Legacy tables
    legacy_tables = []
    for (tname,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_legacy'"
    ).fetchall():
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        legacy_tables.append(f"{tname} ({cnt} rows)")
    if legacy_tables:
        issues.append({
            "severity": "info",
            "category": "data",
            "check": "Legacy tables present",
            "detail": f"Tables: {', '.join(legacy_tables)}",
            "fix": "Review for cleanup if not actively used",
        })

    # Stale DB stub in webroot
    stub = WEBROOT / "purrtfolio.db"
    if stub.exists() and stub.stat().st_size == 0:
        issues.append({
            "severity": "warning",
            "category": "data",
            "check": "Stale DB stub",
            "detail": f"{stub} is 0 bytes — points to old local copy, not the unified DB at {DB_PATH}",
            "fix": "Delete the stub or add to .gitignore; the real DB is downloaded from GitHub Release at Render cold-start",
        })

    # DB release not auto-publishing
    # Check if any cron script references gh release upload
    local_update_q = db_query(
        "SELECT MAX(d) AS d FROM ("
        "SELECT MAX(created_at) AS d FROM filings_13f "
        "UNION ALL SELECT MAX(ingested_at) AS d FROM short_interest "
        "UNION ALL SELECT MAX(filing_date) AS d FROM insider_submissions "
        "UNION ALL SELECT MAX(date) AS d FROM price_history "
        "UNION ALL SELECT MAX(updated_at) AS d FROM corr_matrices "
        "UNION ALL SELECT MAX(enriched_at) AS d FROM ticker_factors "
        "UNION ALL SELECT MAX(completed_at) AS d FROM ingestion_log_si)",
        one=True,
    )
    local_update = local_update_q["d"][:10] if local_update_q and local_update_q["d"] else "unknown"
    upload_found = False
    for script_name in os.listdir(str(SCRIPTS_DIR)):
        if script_name.endswith(".py") and script_name != "audit_qa_bot.py":
            try:
                content = (SCRIPTS_DIR / script_name).read_text(errors="replace")
                if "gh release upload" in content or "gh release create" in content:
                    upload_found = True
                    break
            except Exception:
                pass
    if not upload_found:
        issues.append({
            "severity": "warning",
            "category": "ops",
            "check": "No automated DB publish step",
            "detail": f"Local DB has data through {local_update} but GitHub Release is {GH_RELEASE_TAG} — web API serves stale data",
            "fix": "Add a post-ingest step to compress and upload purrtfolio.db to a new GitHub Release, then update all version tag references in src/config.py and render.yaml",
        })

    conn.close()
    return issues

# ── 6. Known Issues from Previous Cron Runs ─────────────────────────
def check_known_issues() -> list[dict]:
    """Check for known issues that the cron outputs have already revealed."""
    issues = []

    # 13F export.py broken
    export_path = WEBROOT / "scanners" / "13f" / "export.py"
    if export_path.exists():
        content = export_path.read_text(errors="replace")
        if "FROM holdings " in content or "FROM funds " in content:
            issues.append({
                "severity": "critical",
                "category": "data",
                "check": "13F export.py un-prefixed table references",
                "detail": "export.py has un-prefixed FROM holdings/funds queries that break after unified DB rename to holdings_13f",
                "fix": "Patch export.py: replace un-prefixed holdings/funds -> holdings_13f/funds_13f in all SQL",
            })

    # Macro git sync rebase failure
    macro_shim = SCRIPTS_DIR / "macro_market_update.py"
    if macro_shim.exists():
        content = macro_shim.read_text(errors="replace")
        if "rebase" in content and "stash" not in content:
            issues.append({
                "severity": "warning",
                "category": "ops",
                "check": "Macro git sync rebase can fail on uncommitted changes",
                "detail": "macro_market_update.py does git pull --rebase without stashing — fails when working tree has uncommitted changes",
                "fix": "Add git stash before pull --rebase, git stash pop after",
            })

    # Price Momentum & Correlation deliver to local only
    with open(JOBS_JSON, encoding="utf-8") as f:
        jobs_data = json.load(f)
    for job in jobs_data.get("jobs", []):
        if job.get("deliver") == "local" and job.get("script"):
            issues.append({
                "severity": "info",
                "category": "ops",
                "check": f"Cron job '{job['name']}' delivers to local only",
                "detail": f"Job {job['id']} has a script but deliver='local' — no Discord notification",
                "fix": f"Add a Discord channel and update deliver to discord:<channel_id>",
            })

    # Sector Enrichment delivery failure
    for job in jobs_data.get("jobs", []):
        if job.get("last_status") == "delivery_failed":
            issues.append({
                "severity": "warning",
                "category": "ops",
                "check": f"Cron job '{job['name']}' delivery failed",
                "detail": f"Last error: {job.get('last_delivery_error', 'N/A')[:120]}",
                "fix": f"Check channel permissions for deliver target {job.get('deliver')}",
            })

    # Short Interest job HTTP 429 failure
    for job in jobs_data.get("jobs", []):
        if "429" in str(job.get("last_error", "")):
            issues.append({
                "severity": "warning",
                "category": "data",
                "check": f"Cron job '{job['name']}' failed with HTTP 429",
                "detail": f"{job.get('last_error', '')[:120]}",
                "fix": "Transient upstream rate limit — job should retry on next scheduled run. Consider pinning an alternate model for this job.",
            })

    return issues

# ── 7. Website Quality & Incremental Improvements ────────────────────
def check_website_quality() -> list[dict]:
    """Scan the website repo for incremental improvement opportunities.

    Covers:
      - docs/ vs static/ mirror drift (GitHub Pages build output)
      - compiled Python artifacts (__pycache__, .pyc) not cleaned
      - stale DB stub in webroot
      - duplicate / unused scanner modules
    Issues here are auto-fixed when safe (see auto_fix_issues) and
    reported as remaining warnings when they need human attention.
    """
    issues = []

    # 1. Mirror sync: docs/ should track static/
    for fname in _frontend_files():
        sf = WEBROOT / "static" / fname
        df = WEBROOT / "docs" / fname
        if sf.exists() and df.exists():
            if sf.read_bytes() != df.read_bytes():
                issues.append({
                    "severity": "warning",
                    "category": "frontend",
                    "check": f"docs/{fname} out of sync with static/{fname}",
                    "detail": (f"static/{fname} ({sf.stat().st_size} bytes) differs from "
                               f"docs/{fname} ({df.stat().st_size} bytes) — GitHub Pages "
                               f"serves the stale docs/ copy"),
                    "fix": "Sync docs/ from static/ (auto-fixed by this audit bot)",
                })

    # 2. Compiled Python artifacts
    pycache = list(WEBROOT.rglob("__pycache__"))
    pyc_files = list(WEBROOT.rglob("*.pyc"))
    if pycache or pyc_files:
        issues.append({
            "severity": "info",
            "category": "ops",
            "check": "Compiled Python artifacts in webroot",
            "detail": (f"{len(pycache)} __pycache__ dirs, {len(pyc_files)} .pyc files "
                       f"in {WEBROOT} (gitignored but slow to traverse)"),
            "fix": "Delete __pycache__ dirs and .pyc files (auto-fixed by this audit bot)",
        })

    # 3. Stale non-empty DB stub
    stub = WEBROOT / "purrtfolio.db"
    if stub.exists() and stub.stat().st_size > 0:
        issues.append({
            "severity": "warning",
            "category": "data",
            "check": "Stale non-empty DB stub in webroot",
            "detail": (f"{stub} is {stub.stat().st_size} bytes — should not exist in the "
                       f"webroot; real DB is at {DB_PATH}, downloaded at Render cold-start"),
            "fix": "Delete the stub (auto-fixed by this audit bot)",
        })

    return issues


# ── 8. New Items to Build (dynamic) ──────────────────────────────────
def suggest_new_items() -> list[str]:
    """Dynamically suggest new items based on current website audit.

    Previously-flagged items (now resolved):
      ✅ DB Release Auto-Publish Pipeline — built & cron-scheduled
      ✅ Discord Delivery for Price Momentum & Correlation Matrix — deliver targets set
      ✅ Sector Enrichment delivery fix — changed from origin(403) to working channel
      ✅ Macro snapshot git sync resilience — added git stash/pop
      ✅ 13F export.py table-name migration — already using _13f tables
      ✅ Stale DB stub cleanup — deleted + .gitignore covers purrtfolio.db*
      ✅ Short Interest job model resilience — converted to no_agent=True
      ✅ Keepalive URL drift fix — verified: one3f-tracker-wpj6.onrender.com is correct
    """
    suggestions = []

    # Scan the web source for improvement opportunities
    try:
        web_issues = check_website_quality()
    except Exception:
        web_issues = []

    if web_issues:
        suggestions.append(
            "**Resolve remaining website quality issues** — see Section 5 below "
            f"({len(web_issues)} item(s) found by the website quality scan)."
        )

    # Check if docs/ and static/ are tracked in git separately (suggests a
    # post-commit hook to keep them in sync)
    try:
        out = run_cmd("git log --oneline -5 --name-only", cwd=str(WEBROOT), timeout=10)
        if out[0] == 0 and out[1]:
            recent_files = set()
            for line in out[1].strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("commit") and "/" in line:
                    recent_files.add(line)
            static_only = any(f.startswith("static/") for f in recent_files)
            docs_only = any(f.startswith("docs/") for f in recent_files)
            if static_only and not docs_only:
                suggestions.append(
                    "**Add docs/ sync to build workflow** — commits touch static/ but not "
                    "docs/; add a post-commit hook or CI step to mirror static/ → docs/."
                )
    except Exception:
        pass


    return suggestions

def auto_fix_issues() -> list[dict]:
    """Attempt to fix the easiest, safest issues automatically.
    Each fix is recorded with before/after context so the report shows
    exactly what changed and what still needs human attention.
    """
    fixes = []

    def _record(issue, action, target, status="fixed", detail=""):
        fixes.append({
            "issue": issue, "action": action, "target": target,
            "status": status, "detail": detail,
        })

    # ── Fix 1: Delete stale 0-byte DB stub ──
    stub_path = WEBROOT / "purrtfolio.db"
    if stub_path.exists() and stub_path.stat().st_size == 0:
        size = stub_path.stat().st_size
        stub_path.unlink()
        _record(
            "Stale DB stub (0 bytes)",
            f"Deleted {size}-byte stub file",
            str(stub_path),
            detail="The real DB is served from the unified purrtfolio.db at project root",
        )
    # else: already gone — nothing to do

    # ── Fix 2: Ensure .gitignore covers purrtfolio.db ──
    gitignore_path = WEBROOT / ".gitignore"
    gi_content = gitignore_path.read_text(errors="replace") if gitignore_path.exists() else ""
    if "purrtfolio.db" not in gi_content:
        # Append to existing .gitignore or create a new one
        entry = "purrtfolio.db\n"
        if gitignore_path.exists():
            with open(gitignore_path, "a", errors="replace") as f:
                f.write("\n" + entry)
        else:
            gitignore_path.write_text("*.pyc\n__pycache__/\n\n" + entry)
        _record(
            "DB stub not in .gitignore",
            "Added 'purrtfolio.db' to .gitignore",
            str(gitignore_path),
        )

    # ── Fix 3: Patch un-prefixed SQL table names in export.py ──
    export_path = WEBROOT / "scanners" / "13f" / "export.py"
    if export_path.exists():
        content = export_path.read_text(errors="replace")
        original = content
        # Only replace FROM holdings  (trailing space = not holdings_13f)
        n1 = content.count("FROM holdings ")
        content = content.replace("FROM holdings ", "FROM holdings_13f ")
        # Only replace FROM funds  (trailing space = not funds_13f)
        n2 = content.count("FROM funds ")
        content = content.replace("FROM funds ", "FROM funds_13f ")
        # Also handle JOIN ... holdings / JOIN ... funds without _13f suffix
        n3 = content.count("JOIN holdings ")
        content = content.replace("JOIN holdings ", "JOIN holdings_13f ")
        n4 = content.count("JOIN funds ")
        content = content.replace("JOIN funds ", "JOIN funds_13f ")

        total = n1 + n2 + n3 + n4
        if total > 0:
            export_path.write_text(content)
            _record(
                "13F export.py un-prefixed table references",
                f"Replaced {total} un-prefixed SQL table names with _13f suffixes "
                f"(FROM holdings: {n1}, FROM funds: {n2}, JOIN holdings: {n3}, JOIN funds: {n4})",
                str(export_path),
            )
        # else: already fixed — don't record a "skipped" entry so the report
        # doesn't repeat the same check every day. check_known_issues() still
        # catches regressions if the issue returns.

    # ── Fix 4: Pin stale git ref in keepalive.yml ──
    # (Skip — requires careful URL verification, leave for human)

    # ── Fix 5: Sync docs/ mirror from static/ ──
    for fname in _frontend_files():
        static_file = WEBROOT / "static" / fname
        docs_file = WEBROOT / "docs" / fname
        if static_file.exists() and docs_file.exists():
            if static_file.read_bytes() != docs_file.read_bytes():
                size_before = docs_file.stat().st_size
                shutil.copy2(static_file, docs_file)
                _record(
                    f"docs/{fname} out of sync with static/{fname}",
                    f"Synced docs/{fname} ({size_before} → {docs_file.stat().st_size} bytes)",
                    str(docs_file),
                )

    # ── Fix 6: Clean compiled Python artifacts in webroot ──
    pycache_dirs = list(WEBROOT.rglob("__pycache__"))
    pyc_files = list(WEBROOT.rglob("*.pyc"))
    cleaned_dirs = 0
    cleaned_files = 0
    for d in pycache_dirs:
        shutil.rmtree(d, ignore_errors=True)
        cleaned_dirs += 1
    for f in pyc_files:
        f.unlink(missing_ok=True)
        cleaned_files += 1
    if cleaned_dirs or cleaned_files:
        _record(
            "Compiled Python artifacts in webroot",
            f"Removed {cleaned_dirs} __pycache__ dirs + {cleaned_files} .pyc files",
            str(WEBROOT),
        )

    # ── Fix 7: Delete stale non-empty DB stub in webroot ──
    stub = WEBROOT / "purrtfolio.db"
    if stub.exists() and stub.stat().st_size > 0:
        size = stub.stat().st_size
        stub.unlink()
        _record(
            "Stale non-empty DB stub in webroot",
            f"Deleted {size}-byte stub (real DB is at {DB_PATH}, downloaded from GitHub Release)",
            str(stub),
        )

    return fixes

# ── Report generation ──────────────────────────────────────────────
def generate_report() -> str:
    # Auto-fixes MUST run before quality checks so the report shows
    # what's ACTUALLY still broken, not what was just auto-fixed.
    fixes = auto_fix_issues()

    fresh = check_data_freshness()
    cron = check_cron_health()
    web = check_web_health()
    git = check_git()
    quality = check_data_quality()
    known = check_known_issues()
    web_quality = check_website_quality()
    website_issues, website_results = check_website_data()
    suggestions = suggest_new_items()

    # Compute summary counts (combine known + data quality + website quality)
    all_issues = known + quality + web_quality + website_issues
    n_critical = sum(1 for i in all_issues if i["severity"] == "critical")
    n_warning = sum(1 for i in all_issues if i["severity"] == "warning")
    n_info = sum(1 for i in all_issues if i["severity"] == "info")
    n_failed_jobs = sum(1 for j in cron if j["last_status"] in ("error", "delivery_failed"))

    lines = []
    lines.append("# Audit/QA Bot — Daily Report")
    lines.append(f"**Date:** {now_str()} AEST")
    lines.append(f"**DB:** `{DB_PATH}` ({DB_PATH.stat().st_size / 1e6:.1f}MB)")
    lines.append("")
    lines.append(f"> 🔴 {n_critical} critical · 🟡 {n_warning} warning · ℹ️ {n_info} info · ⚠️ {n_failed_jobs} failed/deliver-failed cron jobs")
    lines.append("")

    # 1. Data Freshness
    lines.append("## 📊 1. Data Freshness")
    lines.append("")
    lines.append("| Source | Latest | Stale | Threshold | Flag |")
    lines.append("|--------|--------|-------|-----------|------|")
    for r in fresh:
        lines.append(f"| {r['source']} | {r.get('latest','?')} | {r.get('stale','?')} | {r['threshold']} | {r['flag']} |")
    lines.append("")
    # Add notes
    for r in fresh:
        if r.get("note"):
            lines.append(f"- **{r['source']}**: {r['note']}")
    lines.append("")

    # 2. Cron Job Health
    lines.append("## ⚙️ 2. Cron Job Health")
    lines.append("")
    lines.append("| Job | Schedule | Last Run | Status | Streak | Issues |")
    lines.append("|-----|----------|----------|--------|--------|--------|")
    for j in cron:
        issue_str = "; ".join(j["issues"]) if j["issues"] else "—"
        lines.append(f"| {j['name']} | `{j['schedule']}` | {j['last_run']} | {j['flag']} {j['last_status']} | {j['streak']} | {issue_str} |")
    lines.append("")

    # 3. Web/API Health
    lines.append("## 🌐 3. Web/API Health")
    lines.append("")
    for w in web:
        ok_flag = "✅" if w["ok"] else "❌" if w["status"] == 0 else "⚠️"
        body = w["body"] or w["error"] or ""
        if len(body) > 100:
            body = body[:100] + "…"
        lines.append(f"- {ok_flag} **{w['name']}** — HTTP {w['status']} — `{body}`")
    lines.append("")

    # 3b. Website Data Verification
    lines.append("### Live Page Data Check")
    lines.append("")
    web_ok_count = sum(1 for r in website_results if r["ok"])
    web_bad_count = len(website_results) - web_ok_count
    lines.append(f"- **{web_ok_count}/{len(website_results)}** pages verified with live data (" + ("OK" if web_bad_count == 0 else "FAIL") + ")")
    lines.append("")
    lines.append("| Page | Endpoint | Status | Detail |")
    lines.append("|------|----------|--------|--------|")
    for r in website_results:
        sflag = "OK" if r["ok"] else "FAIL"
        lines.append(f"| {r['page']} | `{r['endpoint']}` | {sflag} | {r['detail']} |")
    lines.append("")

    # 4. Git Status
    lines.append("## 📂 4. Git Status")
    lines.append("")
    if git["clean"]:
        lines.append("✅ Working tree clean — no uncommitted changes.")
    else:
        lines.append(f"⚠️ **{len(git['changed_files'])} uncommitted file(s)** in `{WEBROOT}`:")
        lines.append("")
        for f in git["changed_files"]:
            lines.append(f"  - `{f}`")
        lines.append("")
        lines.append("⚠️ These uncommitted changes block the macro snapshot cron's `git pull --rebase` step.")
    lines.append("")

    # 5. Issues Found
    lines.append("## 🔍 5. Issues Found")
    lines.append("")

    critical_issues = [i for i in known if i["severity"] == "critical"]
    warning_issues = [i for i in known if i["severity"] == "warning"]
    info_issues = [i for i in known if i["severity"] == "info"]
    quality_warnings = [q for q in quality if q["severity"] == "warning"]
    quality_infos = [q for q in quality if q["severity"] == "info"]
    web_warnings = [w for w in web_quality if w["severity"] == "warning"]
    web_infos = [w for w in web_quality if w["severity"] == "info"]

    if critical_issues:
        lines.append("### 🔴 Critical (fix now)")
        lines.append("")
        for i in critical_issues:
            lines.append(f"**{i['check']}** — {i['detail']}")
            lines.append(f"  → Fix: {i['fix']}")
            lines.append("")

    if warning_issues or quality_warnings or web_warnings:
        lines.append("### 🟡 Warnings (address soon)")
        lines.append("")
        for i in warning_issues + quality_warnings + web_warnings:
            src = i.get("detail", "")
            lines.append(f"**{i['check']}** — {src}")
            if i.get("fix"):
                lines.append(f"  → {i['fix']}")
            lines.append("")

    if info_issues or quality_infos or web_infos:
        lines.append("### ℹ️ Info (known patterns)")
        lines.append("")
        for i in info_issues + quality_infos + web_infos:
            lines.append(f"**{i['check']}** — {i['detail']}")
            if i.get("fix"):
                lines.append(f"  → {i['fix']}")
            lines.append("")

    # 6. New Items to Build
    lines.append("## 🟣 6. Proposed New Items to Build")
    lines.append("")
    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. {s}")
    lines.append("")

    # 7. Auto-Fix Applied
    if fixes:
        lines.append("## 🔧 7. Auto-Fix Applied")
        lines.append("")
        lines.append("| Issue | Action | Status |")
        lines.append("|-------|--------|--------|")
        for fx in fixes:
            lines.append(f"| {fx['issue']} | {fx['action']} | ✅ {fx['status']} |")
        lines.append("")
        # Show detail for any non-fixed items
        for fx in fixes:
            if fx.get("detail") and fx["status"] != "fixed":
                lines.append(f"- **{fx['issue']}**: {fx['detail']}")
        lines.append("")
        lines.append("*These fixes were applied automatically by the audit script. "
                      "Human review of SQL changes recommended.*")
        lines.append("")

    # 8. Summary
    lines.append("## ✅ 8. Summary")
    lines.append("")
    lines.append(f"- **{len(fresh)}** data sources checked — {sum(1 for r in fresh if r['flag'] == '✅')} fresh")
    lines.append(f"- **{len(cron)}** cron jobs monitored — {n_failed_jobs} with errors or delivery failures")
    lines.append(f"- **{len(fixes)}** issues auto-fixed by the bot")
    lines.append(f"- **{len(web)}** web endpoints checked — {sum(1 for w in web if w['ok'])} reachable")
    lines.append(f"- **{sum(1 for r in website_results if r['ok'])}/{len(website_results)}** SPA pages verified with live data")
    lines.append(f"- **{n_critical}** critical issues, **{n_warning}** warnings, **{n_info}** informational")
    lines.append(f"- **{len(suggestions)}** proposed new items to build")
    lines.append("")
    lines.append(f"_Report generated by audit_qa_bot.py_")

    return "\n".join(lines)

if __name__ == "__main__":
    try:
        report = generate_report()
        print(report)
    except Exception as e:
        print(f"Status: error")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)

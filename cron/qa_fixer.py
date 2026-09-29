#!/usr/bin/env python3
"""QA Fixer — turns the daily Audit/QA report into a fix PR.

Runs as a no_agent Hermes job after the Audit/QA Bot. It reads today's report,
takes the critical and warning issues, and asks Claude Code (`claude -p`) to fix
the ones that a code or content change in this repo can fix. The script, not the
agent, enforces the guardrails:

  - works in its own clone (QA_FIXER_WORKDIR, default ~/qa-fixer-work), never in
    the checkout Hermes runs from
  - skips issues already covered by an open `qa-fix` PR
  - rejects changes to protected paths, oversized diffs, and failing checks
  - opens at most one PR per run and never merges

Stdout is the Discord message; empty stdout = nothing to say (silent).

    python cron/qa_fixer.py                 # normal run
    python cron/qa_fixer.py --dry-run       # fix + check, but no push/PR/state
    python cron/qa_fixer.py --report X.md   # use a specific report file
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / "AppData" / "Local" / "hermes"))
JOBS_JSON = HERMES_HOME / "cron" / "jobs.json"
OUTPUT_DIR = HERMES_HOME / "cron" / "output"
STATE_FILE = HERMES_HOME / "cron" / "qa_fixer_state.json"
WORK = Path(os.environ.get("QA_FIXER_WORKDIR", Path.home() / "qa-fixer-work"))

LABEL = "qa-fix"
CLAUDE_TIMEOUT = 30 * 60
REALERT_DAYS = 7            # repeat a "needs you" item at most weekly
MAX_FILES, MAX_LINES = 15, 400
PROTECTED = (".github/", "docs/", "render.yaml", "src/config.py", "cron/qa_fixer.py")
PROTECTED_SUFFIXES = (".db", ".env", ".pem", ".key")

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "fixed": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "summary": {"type": "string"}},
            "required": ["id", "summary"]}},
        "needs_human": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["id", "reason"]}},
        "pr_title": {"type": "string"},
        "pr_summary": {"type": "string"},
    },
    "required": ["fixed", "needs_human", "pr_title", "pr_summary"],
}

PROMPT = """You are fixing issues found by the daily Audit/QA report for this repo
(the Purrtfolio website: static/ frontend, src/ API, scanners/, cron/ jobs, research/).
Read CLAUDE.md or README.md and cron/README.md first if they exist.

Issues (id, severity, check, detail, suggested fix):
{issues}

Rules:
- Fix only issues that a code or content change in THIS repo can fix. Stale data,
  upstream outages or rate limits, Render/Hermes/GitHub settings, and anything
  needing a secret or a judgement call go in needs_human with a one-line reason.
- Keep changes minimal and focused on the issues. No refactors, no new dependencies.
- Never touch .github/, docs/ (CI builds it), render.yaml, src/config.py,
  cron/qa_fixer.py, *.db files or secrets.
- Do not commit, push, or run any git command that changes state; the caller does that.
- After changing code, run: python -m pytest tests research/catalogue -q
  and make sure it passes. If you cannot make it pass, revert your change to that
  file and move the issue to needs_human.
- Every issue id must appear in exactly one of fixed or needs_human.
- pr_title: short, imperative. pr_summary: markdown bullets of what changed and why.
"""


# ── helpers ─────────────────────────────────────────────────────────
def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600, check: bool = True,
        env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env, input=stdin)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {(proc.stderr or proc.stdout).strip()[-400:]}")
    return proc


def fingerprint(check: str) -> str:
    return hashlib.sha1(check.strip().lower().encode("utf-8")).hexdigest()[:10]


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ── 1. Today's report ──────────────────────────────────────────────
def latest_report() -> Path | None:
    """Today's Audit/QA Bot output, or None if it hasn't run today."""
    try:
        jobs = json.loads(JOBS_JSON.read_text(encoding="utf-8")).get("jobs", [])
    except (OSError, ValueError):
        return None
    job = next((j for j in jobs if j.get("script") == "audit_qa_bot.py"), None)
    if not job:
        return None
    reports = sorted((OUTPUT_DIR / job["id"]).glob("*.md"))
    if not reports or not reports[-1].name.startswith(date.today().isoformat()):
        return None
    return reports[-1]


def parse_issues(report: str) -> list[dict]:
    """Critical and warning items from the report's 'Issues Found' section."""
    issues, severity, in_section = [], None, False
    for line in report.splitlines():
        if line.startswith("## "):
            in_section = "Issues Found" in line
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            severity = "critical" if "Critical" in line else "warning" if "Warning" in line else None
            continue
        m = re.match(r"\*\*(.+?)\*\* — ?(.*)", line)
        if severity and m:
            issues.append({"id": fingerprint(m.group(1)), "severity": severity,
                           "check": m.group(1), "detail": m.group(2).strip(), "fix": ""})
        elif severity and issues and line.strip().startswith("→"):
            issues[-1]["fix"] = line.strip().lstrip("→").strip().removeprefix("Fix:").strip()
    return issues


def open_pr_fingerprints() -> set[str]:
    proc = run(["gh", "pr", "list", "--label", LABEL, "--state", "open", "--json", "body"], cwd=REPO)
    fps = set()
    for pr in json.loads(proc.stdout or "[]"):
        m = re.search(r"<!-- qa-fix-ids: ([\w,]+) -->", pr.get("body") or "")
        if m:
            fps.update(m.group(1).split(","))
    return fps


# ── 2. Work copy ───────────────────────────────────────────────────
def prepare_workcopy(branch: str) -> None:
    if not (WORK / ".git").exists():
        url = run(["git", "remote", "get-url", "origin"], cwd=REPO).stdout.strip()
        run(["git", "clone", "-q", url, str(WORK)], timeout=600)
    run(["git", "fetch", "-q", "origin"], cwd=WORK)
    run(["git", "checkout", "-q", "-B", branch, "origin/master"], cwd=WORK)
    run(["git", "reset", "-q", "--hard", "origin/master"], cwd=WORK)
    run(["git", "clean", "-q", "-fdx"], cwd=WORK)


def tool_env() -> dict:
    """PATH with this interpreter first, so `python` in the agent's shell is the
    Hermes venv (which has the test and scanner dependencies). API key variables
    are dropped so `claude` always runs on the logged-in claude.ai subscription."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    return env


# ── 3. Claude Code ─────────────────────────────────────────────────
def claude_exe() -> str:
    """The claude binary. On Windows npm installs a claude.cmd wrapper, and
    cmd.exe truncates arguments at newlines, so use the native exe it wraps."""
    found = shutil.which("claude")
    if not found:
        raise RuntimeError("claude CLI not found on PATH")
    if found.lower().endswith(".cmd"):
        native = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if native.exists():
            return str(native)
    return found


def ask_claude(issues: list[dict]) -> dict:
    claude = claude_exe()
    listing = "\n".join(
        f"- id={i['id']} [{i['severity']}] {i['check']} — {i['detail']}" + (f" (suggested: {i['fix']})" if i["fix"] else "")
        for i in issues)
    proc = run([
        claude, "-p", PROMPT.format(issues=listing),
        "--output-format", "json",
        "--json-schema", json.dumps(RESULT_SCHEMA),
        "--no-session-persistence",
        "--allowedTools", "Read", "Edit", "Write", "Glob", "Grep",
        "Bash(python -m pytest:*)", "Bash(git status:*)", "Bash(git diff:*)",
        "Bash(node --check:*)", "Bash(node --input-type=module --check:*)",
        "--disallowedTools", "WebFetch", "WebSearch",
        "Bash(git commit:*)", "Bash(git push:*)", "Bash(git reset:*)", "Bash(git checkout:*)",
    ], cwd=WORK, timeout=CLAUDE_TIMEOUT, env=tool_env(), stdin="")
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError(f"claude output is not JSON: {(proc.stdout or proc.stderr).strip()[:300]!r}")
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError(f"claude returned no result: {str(out.get('result'))[:300]}")
    return out["structured_output"]


# ── 4. Verify the change ───────────────────────────────────────────
def changed_files() -> list[str]:
    run(["git", "add", "-A"], cwd=WORK)
    return [f for f in run(["git", "diff", "--cached", "--name-only"], cwd=WORK).stdout.splitlines() if f]


def verify(files: list[str]) -> str | None:
    """None if the staged change is acceptable, else the reason it isn't."""
    bad = [f for f in files if f.startswith(PROTECTED) or f in PROTECTED or f.endswith(PROTECTED_SUFFIXES)]
    if bad:
        return f"touched protected paths: {', '.join(bad)}"
    numstat = run(["git", "diff", "--cached", "--numstat"], cwd=WORK).stdout.splitlines()
    lines = sum(int(a) + int(d) for a, d, _ in (l.split("\t", 2) for l in numstat) if a.isdigit() and d.isdigit())
    if len(files) > MAX_FILES or lines > MAX_LINES:
        return f"change too large ({len(files)} files, {lines} lines; limit {MAX_FILES}/{MAX_LINES})"

    env = tool_env()
    py = [f for f in files if f.endswith(".py") and (WORK / f).exists()]
    if py and run([sys.executable, "-m", "py_compile", *py], cwd=WORK, check=False, env=env).returncode:
        return "Python files don't compile"
    node = shutil.which("node")
    for f in files:
        if node and f.startswith("static/js/") and f.endswith(".js") and (WORK / f).exists():
            src = (WORK / f).read_text(encoding="utf-8")
            if run([node, "--input-type=module", "--check"], cwd=WORK, check=False, stdin=src).returncode:
                return f"JS syntax error in {f}"
    tests = run([sys.executable, "-m", "pytest", "tests", "research/catalogue", "-q", "-p", "no:cacheprovider"],
                cwd=WORK, check=False, timeout=900, env=env)
    if tests.returncode:
        return "tests fail: " + (tests.stdout.strip().splitlines() or ["?"])[-1]
    return None


# ── 5. Open the PR ─────────────────────────────────────────────────
def open_pr(branch: str, result: dict, ids: list[str]) -> str:
    msg = (f"{result['pr_title']}\n\nAutomated fix for issues in the {date.today()} QA report.\n\n"
           "Co-Authored-By: Claude <noreply@anthropic.com>\n")
    run(["git", "commit", "-q", "-F", "-"], cwd=WORK, stdin=msg)
    run(["git", "push", "-q", "-f", "origin", branch], cwd=WORK, timeout=300)
    run(["gh", "label", "create", LABEL, "--color", "C5DEF5",
         "--description", "Automated fix from the QA fixer"], cwd=WORK, check=False)
    body = (
        f"Automated fix for issues in the {date.today()} Audit/QA report "
        "(`cron/qa_fixer.py`, written by Claude Code, checked by the script: "
        "protected paths, diff size, compile/syntax, full test suite).\n\n"
        f"{result['pr_summary']}\n\n"
        "**Review before merging; this PR is never merged automatically.**\n\n"
        f"<!-- qa-fix-ids: {','.join(ids)} -->\n\n"
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    )
    proc = run(["gh", "pr", "create", "--base", "master", "--head", branch, "--label", LABEL,
                "--title", result["pr_title"], "--body-file", "-"], cwd=WORK, stdin=body)
    return proc.stdout.strip().splitlines()[-1]


# ── main ───────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fix and check, but don't push, open a PR or save state")
    ap.add_argument("--report", type=Path, help="report file to use instead of today's")
    args = ap.parse_args()

    report = args.report or latest_report()
    if not report:
        return 0  # QA bot hasn't run today; its own failure alerts cover that
    issues = parse_issues(report.read_text(encoding="utf-8"))
    covered = open_pr_fingerprints()
    todo = [i for i in issues if i["id"] not in covered]
    if not todo:
        return 0

    branch = f"qa-fix/{date.today().isoformat()}"
    prepare_workcopy(branch)
    result = ask_claude(todo)

    by_id = {i["id"]: i for i in todo}
    lines, fixed_ids = [], [f["id"] for f in result["fixed"] if f["id"] in by_id]
    if fixed_ids:
        files = changed_files()
        problem = verify(files) if files else "Claude reported fixes but changed no files"
        if problem:
            lines.append(f"**QA fixer:** attempted fix rejected — {problem}. No PR opened.")
            result["needs_human"] += [{"id": i, "reason": "automatic fix rejected"} for i in fixed_ids]
            fixed_ids = []
        elif args.dry_run:
            lines.append(f"**QA fixer (dry run):** fix passed all checks ({len(files)} files) — not pushed.")
        else:
            url = open_pr(branch, result, fixed_ids)
            lines.append(f"**QA fixer:** opened {url}")
        for f in result["fixed"]:
            if f["id"] in fixed_ids:
                lines.append(f"- fixed: {by_id[f['id']]['check']} — {f['summary']}")

    state = load_state()
    cutoff = (date.today() - timedelta(days=REALERT_DAYS)).isoformat()
    needs = [n for n in result["needs_human"] if n["id"] in by_id and state.get(n["id"], "") < cutoff]
    if needs:
        lines.append("**Needs you:**")
        for n in needs:
            lines.append(f"- {by_id[n['id']]['check']} — {n['reason']}")
            state[n["id"]] = date.today().isoformat()
    if not args.dry_run:
        save_state(state)

    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # surfaced to Hermes as a failed run
        print(f"Status: error — QA fixer: {e}")
        sys.exit(1)

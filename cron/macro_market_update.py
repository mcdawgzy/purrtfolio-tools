#!/usr/bin/env python3
# Cron launcher for the macro market update.
# Replaces macro_market_update.sh which failed with:
#   WSL ERROR: execvpe(/bin/bash) failed: No such file or directory
# (bash not on PATH in cron subprocess environment on Windows).
import os, sys, subprocess
from pathlib import Path

# Repo-relative paths: this file lives in <repo>/cron/ and is run by a Hermes shim.
REPO = Path(__file__).resolve().parents[1]

WORKDIR = str(REPO / "snapshots" / "macro")
SCRIPT_NAME = "main.py"
SCRIPT = os.path.join(WORKDIR, SCRIPT_NAME)

# Hermes runs cron scripts with its own venv interpreter; reuse it
PYTHON = sys.executable

if __name__ == "__main__":
    extra = sys.argv[1:]
    cmd = [PYTHON, SCRIPT, "--post-discord", *extra]
    result = subprocess.run(cmd, cwd=WORKDIR, env={**os.environ})
    if result.returncode == 0:
        # Sync updated snapshot assets to git so GitHub Pages picks them up.
        # The build-pages.yml workflow also pushes to master (docs/ sync), so
        # we must rebase onto origin/master before pushing to avoid divergence.
        _GIT = "git"
        _WEBROOT = str(REPO)
        try:
            # Stash uncommitted changes before pulling so --rebase doesn't fail.
            # The macro pipeline only owns static/snapshots/ and docs/snapshots/,
            # so we pop after the pull to restore any other working-tree changes.
            stash = subprocess.run(
                [_GIT, "-C", _WEBROOT, "stash", "push", "-u",
                 "-m", "temp: macro snapshot sync"],
                check=False, capture_output=True,
            )
            if stash.returncode != 0:
                print(f"[git sync] stash skipped/failed, continuing without stash: {stash.stderr.decode()[:200]}")

            # Pull latest to avoid "rejected (fetch first)" on next push
            pull = subprocess.run(
                [_GIT, "-C", _WEBROOT, "pull", "--rebase", "origin", "master"],
                check=False, capture_output=True,
            )
            if pull.returncode != 0:
                print(f"[git sync] rebase skipped/failed, continuing: {pull.stderr.decode()[:200]}")

            # Restore stashed changes
            if stash.returncode == 0:
                pop = subprocess.run(
                    [_GIT, "-C", _WEBROOT, "stash", "pop"],
                    check=False, capture_output=True,
                )
                if pop.returncode != 0:
                    print(f"[git sync] ⚠️ stash pop conflict — manual recovery needed: {pop.stderr.decode()[:200]}")

            subprocess.run([_GIT, "-C", _WEBROOT, "add", "static/snapshots/", "docs/snapshots/"], check=False)
            commit = subprocess.run(
                [_GIT, "-C", _WEBROOT, "commit", "-m", "chore: update market snapshot",
                 "-o", "static/snapshots/", "docs/snapshots/"],
                check=False, capture_output=True,
            )
            if commit.returncode == 0:
                push = subprocess.run(
                    [_GIT, "-C", _WEBROOT, "push", "origin", "master"],
                    check=False, capture_output=True,
                )
                if push.returncode == 0:
                    print("[git sync] ✅ snapshots pushed to GitHub")
                else:
                    print(f"[git sync] ❌ push failed: {push.stderr.decode().strip()[:300]}")
            else:
                print(f"[git sync] nothing to commit or commit failed: {commit.stderr.decode().strip()[:200]}")
        except Exception as e:
            print(f"[git sync] skipped: {e}")
    sys.exit(result.returncode)

#!/usr/bin/env python3
"""Point Hermes cron jobs at the runners in this repo's cron/ folder.

Each Hermes job runs a script by name from ~/AppData/Local/hermes/scripts/.
This replaces those scripts with tiny shims that execute the file of the same
name in <repo>/cron/, so job logic is versioned with the code it drives and
future repo changes need no Hermes edits.

    python cron/install_hermes_shims.py            # dry run: show what would change
    python cron/install_hermes_shims.py --apply    # back up originals, write shims
    python cron/install_hermes_shims.py --restore  # put the backed-up originals back

Run it from the checkout Hermes uses (C:\\Users\\cho_i\\13f-scanner-web).
Originals are saved to <hermes>/scripts/_pre_repo_backup/ before being replaced.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CRON_DIR = REPO / "cron"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / "AppData" / "Local" / "hermes"))
SCRIPTS_DIR = HERMES_HOME / "scripts"
BACKUP_DIR = SCRIPTS_DIR / "_pre_repo_backup"
HERMES_PYTHON = HERMES_HOME / "hermes-agent" / "venv" / "Scripts" / "python.exe"

# Hermes job script name -> runner in cron/ (same name unless listed here).
# The 13F job's script is a .sh (Hermes can't change a job's script via CLI),
# so that shim is a bash one-liner that runs the Python runner.
ALIASES = {"quarterly_pipeline.sh": "quarterly_13f_pipeline.py"}

MARKER = "Managed by cron/install_hermes_shims.py"

PY_SHIM = '''# Hermes shim: runs {target}
# {marker} (originals in _pre_repo_backup/).
import os
import runpy
import sys

# UTF-8 output regardless of how Hermes was launched (reports use emoji)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TARGET = r"{target}"
sys.argv[0] = TARGET
runpy.run_path(TARGET, run_name="__main__")
'''

SH_SHIM = '''#!/bin/bash
# Hermes shim: runs {target}. {marker} (originals in _pre_repo_backup/).
exec "{python}" "{target}" "$@"
'''


def planned() -> dict[str, Path]:
    """Hermes script name -> repo runner, for runners that exist."""
    plan = {p.name: p for p in sorted(CRON_DIR.glob("*.py"))
            if not p.name.startswith("_") and p.name != Path(__file__).name}
    for alias, target in ALIASES.items():
        plan[alias] = CRON_DIR / target
    return plan


def shim_text(name: str, target: Path) -> str:
    if name.endswith(".sh"):
        py = HERMES_PYTHON if HERMES_PYTHON.exists() else Path(sys.executable)
        return SH_SHIM.format(target=target.as_posix(), python=py.as_posix(), marker=MARKER)
    return PY_SHIM.format(target=target, marker=MARKER)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write the shims")
    g.add_argument("--restore", action="store_true", help="restore backed-up originals")
    args = ap.parse_args()

    if not SCRIPTS_DIR.is_dir():
        print(f"Hermes scripts dir not found: {SCRIPTS_DIR} (set HERMES_HOME)")
        return 2

    if args.restore:
        if not BACKUP_DIR.is_dir():
            print("Nothing to restore.")
            return 0
        for b in sorted(BACKUP_DIR.iterdir()):
            shutil.copy2(b, SCRIPTS_DIR / b.name)
            print(f"restored {b.name}")
        return 0

    changes = 0
    for name, target in planned().items():
        dest = SCRIPTS_DIR / name
        if not target.exists():
            print(f"skip   {name}: runner missing ({target})")
            continue
        new = shim_text(name, target)
        current = dest.read_text(encoding="utf-8", errors="replace") if dest.exists() else None
        if current == new:
            print(f"ok     {name}")
            continue
        state = "new" if current is None else ("update" if MARKER in current else "replace")
        print(f"{state:<6} {name} -> {target.relative_to(REPO)}")
        changes += 1
        if args.apply:
            if current is not None and MARKER not in current:
                BACKUP_DIR.mkdir(exist_ok=True)
                shutil.copy2(dest, BACKUP_DIR / name)
            dest.write_text(new, encoding="utf-8", newline="\n")

    if not args.apply:
        print(f"\n{changes} change(s). Dry run only; re-run with --apply to write them.")
    else:
        print(f"\n{changes} shim(s) written. Originals backed up to {BACKUP_DIR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""DB path rules that production depends on (no network, no real DB)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STARTUP_CHECK = """
import os
from pathlib import Path
from src.scanner_data import ensure_momentum_db, pm_db
main = Path(os.environ["PURRTFOLIO_DB"])
assert Path(pm_db.DB_PATH).resolve() == main.resolve(), pm_db.DB_PATH
ensure_momentum_db(at_startup=True)
assert not main.exists(), "startup wrote a file at the main DB path"
print("ok")
"""


def test_startup_never_writes_slim_db_over_main_db(tmp_path):
    """Without MOMENTUM_DB (as on Render), momentum data lives in the main DB.
    Startup must not download the slim extract to that path: the API would
    then treat a momentum-only file as the full DB (every other route 500s)."""
    env = {k: v for k, v in os.environ.items() if k not in ("MOMENTUM_DB", "DB_AUTO_REFRESH")}
    env["PURRTFOLIO_DB"] = str(tmp_path / "purrtfolio.db")
    r = subprocess.run([sys.executable, "-c", STARTUP_CHECK], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]

"""Export the with/against/random-direction equity curves for the ORB study page.

Re-runs trading_hub's scripts/eda_reddit_orb_null.py loop (OR1 leg, identical 3:1
bracket and costs; only the direction rule changes) and keeps each trade's date.
Needs the trading_hub checkout beside this repo (or TRADING_HUB_ROOT) and its ticks.

    py -3.14 research/studies/one-minute-orb/export_direction_curves.py research/studies/one-minute-orb/data/direction_curves.json
    cp research/studies/one-minute-orb/data/direction_curves.json static/research/one-minute-orb/direction.json
"""
import json, os, sys
from pathlib import Path
import numpy as np
HUB = Path(os.environ.get("TRADING_HUB_ROOT", Path(__file__).resolve().parents[4] / "trading_hub"))
sys.path.insert(0, str(HUB)); sys.path.insert(0, str(HUB / "scripts"))
from eda_reddit_orb_null import day_setup, _simulate_bracket, load_day, REPO, TICK_SIZE

files = sorted((REPO / "data" / "ticks" / "US500").glob("*.parquet"))
slip = TICK_SIZE["US500"]
days = []
for f in files:
    df = load_day(f)
    if df is None: continue
    s = day_setup(df)
    if s is None: continue
    days.append((str(df["et"].iloc[0].date()), s))
print("days with a break:", len(days), file=sys.stderr)

def run(mode, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for date, (bid, ask, mid, hi, lo, brk, side, i_931, i_end) in days:
        if mode == "TRUE": d, i = side, brk
        elif mode == "FADE": d, i = ("short" if side == "long" else "long"), brk
        else: d, i = ("long" if rng.random() < 0.5 else "short"), brk
        dist = hi - lo
        if dist <= 0: continue
        entry_px = (ask[i] + slip) if d == "long" else (bid[i] - slip)
        stop_level = (entry_px - dist) if d == "long" else (entry_px + dist)
        res = _simulate_bracket(i, d, stop_level, bid, ask, mid, slip, 3.0)
        if res is None: continue
        _, entry, exit_fill, outcome, risk = res
        pnl = (exit_fill - entry) if d == "long" else (entry - exit_fill)
        out.append((date, pnl / risk))
    return out

tr, fd = run("TRUE"), run("FADE")
assert [d for d, _ in tr] == [d for d, _ in fd]
rt, rf = np.array([r for _, r in tr]), np.array([r for _, r in fd])
diff = rt - rf
print(f"TRUE n={len(rt)} mean={rt.mean():+.4f}  FADE mean={rf.mean():+.4f}  "
      f"paired t={diff.mean()/(diff.std(ddof=1)/np.sqrt(len(diff))):+.2f}", file=sys.stderr)
DRAWS = 200
rand = []
for k in range(DRAWS):
    r = run("RANDDIR", seed=1000 + k)
    assert [d for d, _ in r] == [d for d, _ in tr]
    rand.append(np.cumsum([x for _, x in r]))
rand = np.array(rand)
print(f"RANDDIR mean over {DRAWS} draws={rand[:, -1].mean()/len(rt):+.4f}  "
      f"first20 mean={rand[:20, -1].mean()/len(rt):+.4f}", file=sys.stderr)
r1 = lambda a: [round(float(v), 2) for v in a]
json.dump({
    "source": "trading_hub scripts/eda_reddit_orb_null.py logic, US500 ticks, OR1 leg, 3:1, net of costs",
    "dates": [d for d, _ in tr],
    "with": r1(np.cumsum(rt)), "against": r1(np.cumsum(rf)),
    "random_median": r1(np.median(rand, 0)),
    "random_p5": r1(np.percentile(rand, 5, 0)), "random_p95": r1(np.percentile(rand, 95, 0)),
    "random_draws": DRAWS,
}, open(sys.argv[1], "w"), separators=(",", ":"))

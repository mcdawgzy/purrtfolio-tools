"""Render the 1200x1500 X poster for the one-minute ORB study from its real equity curve.

Run from anywhere: py -3.14 research/studies/one-minute-orb/make_poster.py
Needs Edge or Chrome (set BROWSER_EXE to override).
"""
import datetime as dt
import json
import os
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCR = Path(tempfile.mkdtemp(prefix="purrtfolio-poster-"))  # throwaway HTML for the renderer
OUT = HERE / "assets" / "0-poster.png"
EDGE = os.environ.get("BROWSER_EXE") or next(
    (p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe") if Path(p).exists()),
    "msedge")

# [date, cumulative R] per trade, exported from trading_hub's
# scripts/eda_reddit_orb_1m2m.py --json (544 trades, US500 ticks, 2024-05 -> 2026-05).
pts = json.loads((HERE / "data" / "equity_curve.json").read_text())
dates = [dt.date.fromisoformat(d) for d, _ in pts]
d0, d1 = dates[0], dates[-1]
n = len(pts)
CLAIM_R = 4 * 0.35 - 1  # expectancy per trade at a 35% win rate, fixed 3:1

# chart geometry
W, H = 1040, 560
L, R, T, B = 78, 200, 24, 46
YMIN, YMAX = -50, 230
def x(d):
    return L + (d - d0).days / (d1 - d0).days * (W - L - R)
def y(v):
    return T + (1 - (v - YMIN) / (YMAX - YMIN)) * (H - T - B)

actual = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, (_, v) in zip(dates, pts))
claim = " ".join(f"{x(d):.1f},{y((i + 1) * CLAIM_R):.1f}" for i, d in enumerate(dates))
claim_end = n * CLAIM_R
act_end = pts[-1][1]
area = f"{x(d0):.1f},{y(0):.1f} " + claim + f" {x(d1):.1f},{y(0):.1f}"

grid = []
for v in (0, 50, 100, 150, 200):
    grid.append(f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#1b2430" stroke-width="{2 if v == 0 else 1}"/>')
    grid.append(f'<text x="{L-14}" y="{y(v)+7:.1f}" text-anchor="end" class="ax">{"+" if v > 0 else ""}{v}R</text>')
for lab, d in [("MAY 2024", dt.date(2024, 5, 20)), ("NOV 2024", dt.date(2024, 11, 1)), ("MAY 2025", dt.date(2025, 5, 1)),
               ("NOV 2025", dt.date(2025, 11, 1)), ("MAY 2026", dt.date(2026, 5, 21))]:
    anchor = "start" if d == d0 else ("end" if d == d1 else "middle")
    grid.append(f'<text x="{x(d):.1f}" y="{H-12}" text-anchor="{anchor}" class="ax">{lab}</text>')

svg = f"""<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">
<defs>
  <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#3fd0c9" stop-opacity=".22"/><stop offset="1" stop-color="#3fd0c9" stop-opacity="0"/>
  </linearGradient>
  <filter id="glow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
{''.join(grid)}
<polygon points="{area}" fill="url(#fill)"/>
<polyline points="{claim}" fill="none" stroke="#3fd0c9" stroke-width="3" stroke-dasharray="10 8"/>
<circle cx="{x(d1):.1f}" cy="{y(claim_end):.1f}" r="7" fill="#3fd0c9"/>
<text x="{x(d1)+16:.1f}" y="{y(claim_end)-4:.1f}" class="lab" fill="#3fd0c9">+{claim_end:.0f}R</text>
<text x="{x(d1)+16:.1f}" y="{y(claim_end)+22:.1f}" class="sm" fill="#7fe3dd">IF IT WON 35%</text>
<polyline points="{actual}" fill="none" stroke="#ff6b5e" stroke-width="4" stroke-linejoin="round" filter="url(#glow)"/>
<circle cx="{x(d1):.1f}" cy="{y(act_end):.1f}" r="9" fill="#ff6b5e" stroke="#07090d" stroke-width="3"/>
<text x="{x(d1)+16:.1f}" y="{y(act_end)-4:.1f}" class="lab" fill="#ff6b5e">+{act_end:.1f}R</text>
<text x="{x(d1)+16:.1f}" y="{y(act_end)+22:.1f}" class="sm" fill="#ff9b92">WHAT IT MADE</text>
</svg>"""

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
*{{box-sizing:border-box}} html,body{{margin:0}}
body{{width:1200px;height:1500px;overflow:hidden;color:#e9eef2;font-family:'IBM Plex Sans',sans-serif;
  background:radial-gradient(900px 700px at 85% 45%, rgba(63,208,201,.13), transparent 70%),
             radial-gradient(700px 500px at 0% 100%, rgba(40,90,160,.18), transparent 70%), #07090d;}}
.pad{{padding:78px 80px 0}}
.eyebrow{{font:600 25px 'IBM Plex Mono',monospace;letter-spacing:.2em;color:#3fd0c9}}
.title{{font:400 150px/.92 'Anton',sans-serif;letter-spacing:.005em;margin:18px 0 0;text-transform:uppercase}}
.title span{{color:#3fd0c9}}
.sub{{font:600 25px 'IBM Plex Mono',monospace;letter-spacing:.14em;color:#8b97a3;margin-top:22px}}
.hero{{position:absolute;right:80px;top:250px;text-align:right}}
.hero .k{{font:600 21px 'IBM Plex Mono',monospace;letter-spacing:.18em;color:#8b97a3}}
.hero .v{{font:400 132px/1 'Anton',sans-serif;color:#ff6b5e;text-shadow:0 0 28px rgba(255,107,94,.45);margin-top:10px}}
.hero .note{{font:500 21px 'IBM Plex Mono',monospace;color:#b7c1ca;margin-top:6px}}
.hero .note b{{color:#e9eef2;font-weight:600}}
.chart{{position:absolute;left:80px;top:560px}}
.ax{{font:500 19px 'IBM Plex Mono',monospace;fill:#6b7784}}
.lab{{font:400 38px 'Anton',sans-serif}}
.sm{{font:600 15px 'IBM Plex Mono',monospace;letter-spacing:.12em}}
.tiles{{position:absolute;left:80px;right:80px;top:1150px;display:grid;grid-template-columns:repeat(4,1fr);gap:18px}}
.tile{{background:#0d121a;border:1px solid #1d2733;border-radius:16px;padding:22px 22px 20px}}
.tile .v{{font:400 64px/1 'Anton',sans-serif}}
.tile .k{{font:600 16px 'IBM Plex Mono',monospace;letter-spacing:.14em;color:#8b97a3;margin-top:12px;line-height:1.35}}
.ask{{position:absolute;left:80px;right:80px;top:1330px;font:600 27px/1.3 'IBM Plex Sans',sans-serif;color:#e9eef2}}
.ask span{{color:#3fd0c9}}
.foot{{position:absolute;left:80px;right:80px;bottom:40px;font:500 16px/1.5 'IBM Plex Mono',monospace;color:#56616d}}
</style></head><body>
<div class="pad">
  <div class="eyebrow">S&amp;P 500 · OPENING-RANGE SCALP · TESTED</div>
  <div class="title">One-minute<br><span>ORB at 3:1</span></div>
  <div class="sub">REDDIT CLAIM vs TICK DATA</div>
</div>
<div class="hero">
  <div class="k">WIN RATE · 544 TRADES</div>
  <div class="v">26.1%</div>
  <div class="note">claimed <b>34–36%</b> · coin flip <b>25.0%</b></div>
</div>
<div class="chart">{svg}</div>
<div class="tiles">
  <div class="tile"><div class="v">544</div><div class="k">TRADES<br>OVER 2 YEARS</div></div>
  <div class="tile"><div class="v">+0.008R</div><div class="k">PER TRADE<br>AFTER COSTS</div></div>
  <div class="tile"><div class="v">15</div><div class="k">LOSSES<br>IN A ROW</div></div>
  <div class="tile"><div class="v" style="color:#ff6b5e">−32.7R</div><div class="k">WORST<br>DRAWDOWN</div></div>
</div>
<div class="ask">The break direction is real, but it's thinner than the spread. <span>What would you change to make it pay?</span></div>
<div class="foot">Backtest on S&amp;P 500 CFD tick data, May 2024 – May 2026 · real spreads · rules fixed before testing · R = amount risked per trade · @Purrtfolio</div>
</body></html>"""

src = SCR / "poster_s017.html"
src.write_text(html, encoding="utf-8")
subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1200,1500",
                "--virtual-time-budget=5000", f"--screenshot={OUT}", src.as_uri()], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(OUT, OUT.stat().st_size, round(claim_end, 1), act_end)

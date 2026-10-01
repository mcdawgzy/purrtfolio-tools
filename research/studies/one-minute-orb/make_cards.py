"""Render og.png (link preview) and the X thread images for the one-minute ORB study.

Run from anywhere: py -3.14 research/studies/one-minute-orb/make_cards.py
Needs Edge or Chrome (set BROWSER_EXE to override). The diagram is read from the
deployed page, so edit it there first.
"""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCR = Path(tempfile.mkdtemp(prefix="purrtfolio-cards-"))  # throwaway HTML for the renderer
OUT_SITE = REPO / "static" / "research" / "one-minute-orb"  # deployed: page + og.png
OUT_X = HERE / "assets"  # not deployed: images for the X thread
EDGE = os.environ.get("BROWSER_EXE") or next(
    (p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe") if Path(p).exists()),
    "msedge")

# The site's theme (static/styles.css) so the cards match the page they preview.
# Light theme values; the dark-mode set isn't used for images.
INK, MUTED, FAINT, RULE = "#222222", "#555555", "#6E6E6E", "#E8E8E8"
GROUND, SURFACE, SURFACE_2 = "#FFFFFF", "#FAFAFA", "#F2F2F2"
ACCENT, ACCENT_SOFT = "#B4561C", "rgba(200, 111, 46, 0.10)"
SERIES, CLAIM, NEUTRAL, WIN, LOSS = "#C86F2E", "#C1272D", MUTED, "#00875A", "#C1272D"
CLAIM_BG = "#F9E6E7"

SANS = "'Aptos', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
DISPLAY = "'Space Grotesk', " + SANS
MONO = "'Space Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
FONTS = ("<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700"
         "&family=Space+Mono:wght@400;700&display=swap'>")

measured = {1: 48.5, 2: 33.6, 3: 26.1, 5: 15.6}


def chart_svg(w=640, h=360):
    L, R, T, B = 60, 30, 20, 50
    def x(k):
        return L + (k - 1) / (5.5 - 1) * (w - L - R)
    def y(v):
        return T + (1 - v / 55) * (h - T - B)
    mono = f"font-family=\"{MONO}\""
    parts = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
    for v in (0, 10, 20, 30, 40, 50):
        parts.append(f'<line x1="{L}" x2="{w-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{RULE}"/>')
        parts.append(f'<text x="{L-10}" y="{y(v)+5:.1f}" text-anchor="end" fill="{FAINT}" font-size="15" {mono}>{v}%</text>')
    for k in (1, 2, 3, 4, 5):
        parts.append(f'<text x="{x(k):.1f}" y="{h-B+24}" text-anchor="middle" fill="{FAINT}" font-size="15" {mono}>{k}:1</text>')
    parts.append(f'<text x="{(L+w-R)/2:.0f}" y="{h-4}" text-anchor="middle" fill="{MUTED}" font-size="15">reward-to-risk</text>')
    parts.append(f'<rect x="{x(3)-18:.1f}" y="{y(36):.1f}" width="36" height="{y(34)-y(36):.1f}" fill="{CLAIM_BG}" stroke="{CLAIM}" stroke-width="2" rx="2"/>')
    parts.append(f'<text x="{x(3)+26:.1f}" y="{y(35)+6:.1f}" fill="{CLAIM}" font-size="18" font-weight="600">claimed 34–36%</text>')
    d = []
    k = 1.0
    while k <= 5.5001:
        d.append(f'{"M" if not d else "L"}{x(k):.1f} {y(100/(1+k)):.1f}')
        k += 0.05
    parts.append(f'<path d="{" ".join(d)}" fill="none" stroke="{NEUTRAL}" stroke-width="2.5" stroke-dasharray="7 6"/>')
    parts.append(f'<text x="{x(3.9):.1f}" y="{y(100/4.9)+30:.1f}" fill="{MUTED}" font-size="17">coin flip</text>')
    for k, v in measured.items():
        parts.append(f'<circle cx="{x(k):.1f}" cy="{y(v):.1f}" r="8" fill="{SERIES}" stroke="{SURFACE}" stroke-width="2.5"/>')
    parts.append(f'<text x="{x(3)-16:.1f}" y="{y(26.1)+32:.1f}" text-anchor="end" fill="{INK}" font-size="18" font-weight="600">measured 26.1%</text>')
    parts.append("</svg>")
    return "".join(parts)


def mechanics_svg():
    page = (OUT_SITE / "index.html").read_text(encoding="utf-8")
    svg = re.search(r'(<svg viewBox="0 0 640 300" role="img".*?</svg>)', page, re.S).group(1)
    tokens = {"var(--brass-dim)": ACCENT_SOFT, "var(--brass)": ACCENT, "var(--text-dim)": MUTED,
              "var(--green)": WIN, "var(--red)": LOSS, "var(--text)": INK,
              "var(--line)": RULE, "var(--panel-2)": SURFACE_2, "var(--panel)": SURFACE,
              "var(--mono)": MONO.replace('"', "'")}
    for k, v in tokens.items():
        svg = svg.replace(k, v)
    return svg.replace('<svg viewBox="0 0 640 300"', '<svg viewBox="0 0 640 300" width="1040" height="487"')


def _half_year_ticks(dates):
    """(index, label) at the first trade of each Jan/Jul, skipping the partial first half."""
    out, last = [], ""
    for i, d in enumerate(dates):
        half = d[:4] + ("a" if d[5:7] < "07" else "b")
        if half != last:
            if last:
                out.append((i, ("Jan " if half.endswith("a") else "Jul ") + d[2:4]))
            last = half
    return out


def _lines_svg(w, h, dates, series, lo, hi, step, band=None, shade=None, L=70, R=90, T=20, B=44):
    """Running-total chart. series: [(values, colour, end label)]; band: (p5, p95);
    shade: (i_from, i_to, label) for the worst drawdown."""
    n = len(dates)
    def x(i):
        return L + i / (n - 1) * (w - L - R)
    def y(v):
        return T + (hi - v) / (hi - lo) * (h - T - B)
    mono = f"font-family=\"{MONO}\""
    p = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
    if shade:
        a, b, lab = shade
        p.append(f'<rect x="{x(a):.1f}" y="{T}" width="{x(b)-x(a):.1f}" height="{h-T-B}" fill="{CLAIM_BG}"/>')
        p.append(f'<text x="{(x(a)+x(b))/2:.1f}" y="{T+24}" text-anchor="middle" fill="{LOSS}" font-size="18" font-weight="600">{lab}</text>')
    v = lo
    while v <= hi:
        p.append(f'<line x1="{L}" x2="{w-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{"#D6D6D6" if v == 0 else RULE}"/>')
        lab = ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v)}R"
        p.append(f'<text x="{L-10}" y="{y(v)+5:.1f}" text-anchor="end" fill="{FAINT}" font-size="15" {mono}>{lab}</text>')
        v += step
    for i, lab in _half_year_ticks(dates):
        p.append(f'<text x="{x(i):.1f}" y="{h-B+26}" text-anchor="middle" fill="{FAINT}" font-size="15" {mono}>{lab}</text>')
    if band:
        lo_v, hi_v = band
        d = " ".join(f'{"M" if i == 0 else "L"}{x(i):.1f} {y(v):.1f}' for i, v in enumerate(hi_v))
        d += " " + " ".join(f"L{x(i):.1f} {y(v):.1f}" for i, v in reversed(list(enumerate(lo_v)))) + " Z"
        p.append(f'<path d="{d}" fill="rgba(85,85,85,0.16)"/>')
    ends = []
    for vals, col, lab in series:
        d = " ".join(f'{"M" if i == 0 else "L"}{x(i):.1f} {y(v):.1f}' for i, v in enumerate(vals))
        p.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.6" stroke-linejoin="round"/>')
        ends.append([y(vals[-1]), col, lab])
    ends.sort()
    for j in range(1, len(ends)):
        ends[j][0] = max(ends[j][0], ends[j - 1][0] + 22)
    for yy, col, lab in ends:
        p.append(f'<text x="{x(n-1)+10:.1f}" y="{yy+6:.1f}" fill="{col}" font-size="19" font-weight="700">{lab}</text>')
    p.append("</svg>")
    return "".join(p)


def _r(v):
    return ("+" if v >= 0 else "−") + f"{abs(v):.0f}R"


def direction_svg(w, h):
    D = json.loads((HERE / "data" / "direction_curves.json").read_text())
    series = [(D["random_median"], MUTED, "Random " + _r(D["random_median"][-1])),
              (D["against"], LOSS, "Against " + _r(D["against"][-1])),
              (D["with"], SERIES, "With " + _r(D["with"][-1]))]
    return _lines_svg(w, h, D["dates"], series, -200, 20, 40, band=(D["random_p5"], D["random_p95"]), R=150)


def equity_svg(w, h):
    pts = json.loads((HERE / "data" / "equity_curve.json").read_text())
    vals = [v for _, v in pts]
    peak, pi, dd, a, b = 0.0, 0, 0.0, 0, 0
    for i, v in enumerate(vals):
        if v > peak:
            peak, pi = v, i
        if v - peak < dd:
            dd, a, b = v - peak, pi, i
    return _lines_svg(w, h, [d for d, _ in pts], [(vals, SERIES, f"+{vals[-1]:.1f}R")], -30, 20, 10,
                      shade=(a, b, f"−{abs(dd):.1f}R from the peak"))


BASE_CSS = f"""
*{{box-sizing:border-box}} html,body{{margin:0}}
body{{width:{{W}}px;height:{{H}}px;background:{GROUND};color:{INK};font-family:{SANS};overflow:hidden;-webkit-font-smoothing:antialiased}}
.handle{{display:flex;align-items:center;gap:12px;font:700 18px {MONO};letter-spacing:.1em;text-transform:uppercase;color:{MUTED}}}
.handle::before{{content:'';width:12px;height:12px;background:{SERIES};flex:none}}
h1{{font:600 64px/1.02 {DISPLAY};letter-spacing:-.04em;margin:0}}
h2{{font:600 42px/1.08 {DISPLAY};letter-spacing:-.03em;margin:0}}
.sub{{font-size:24px;color:{MUTED};line-height:1.4}}
.tag{{display:inline-block;font:700 16px {MONO};letter-spacing:.12em;text-transform:uppercase;color:{LOSS};background:{CLAIM_BG};padding:9px 16px;border-radius:999px}}
"""


def page(w, h, body):
    css = BASE_CSS.replace("{W}", str(w)).replace("{H}", str(h))
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'>{FONTS}<style>{css}</style></head><body>{body}</body></html>"


cards = {
    OUT_SITE / "og.png": (1200, 630, f"""
<div style="display:grid;grid-template-columns:520px 1fr;height:100%;padding:48px 44px 40px 56px;gap:24px;align-items:center">
  <div style="display:grid;gap:22px">
    <div class="handle">@Purrtfolio · Research</div>
    <span class="tag" style="justify-self:start">Rejected</span>
    <h1>Claimed 34–36%.<br><span style="color:{LOSS}">Measured 26.1%.</span></h1>
    <div class="sub">The one-minute ORB scalp at 3:1 wins about what a coin flip does.</div>
  </div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:16px;padding:14px">{chart_svg(560, 360)}</div>
</div>"""),
    OUT_X / "1-how-it-works.png": (1200, 675, f"""
<div style="padding:40px 56px;display:grid;gap:18px">
  <div style="display:flex;justify-content:space-between;align-items:baseline"><h2>How the one-minute ORB scalp works</h2><div class="handle">@Purrtfolio</div></div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:16px;padding:12px 30px;justify-self:center">{mechanics_svg()}</div>
</div>"""),
    OUT_X / "2-coin-flip.png": (1200, 675, f"""
<div style="padding:40px 56px;display:grid;grid-template-columns:420px 1fr;gap:30px;align-items:center;height:100%">
  <div style="display:grid;gap:18px">
    <div class="handle">@Purrtfolio</div>
    <h2>Every measured win rate sits on the coin-flip curve</h2>
    <div class="sub">A 3:1 bracket on a random walk wins 1 / (1 + 3) = 25%. This setup won 26.1% across 544 trades on real tick data.</div>
  </div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:16px;padding:14px">{chart_svg(640, 420)}</div>
</div>"""),
    OUT_X / "3-lesson.png": (1200, 675, f"""
<div style="height:100%;padding:60px 70px;display:grid">
<div style="background:{INK};color:{GROUND};border-radius:24px;padding:0 64px;display:grid;align-content:center;gap:30px">
  <div class="handle" style="color:#B4B4B4">The lesson</div>
  <div style="font:600 54px/1.1 {DISPLAY};letter-spacing:-.03em;max-width:980px">Before you believe a win rate on a fixed R:R trade, compare it with <span style="white-space:nowrap">1 / (1 + R:R).</span></div>
  <div style="font-size:26px;color:#B4B4B4">26% at 3:1 is what randomness produces.</div>
  <div style="font:700 18px {MONO};letter-spacing:.1em;color:#E89877">@PURRTFOLIO</div>
</div>
</div>"""),
    OUT_X / "4-direction.png": (1200, 675, f"""
<div style="padding:36px 56px;display:grid;gap:16px">
  <div style="display:flex;justify-content:space-between;align-items:baseline"><h2>Same trades. Only the direction changes.</h2><div class="handle">@Purrtfolio</div></div>
  <div class="sub" style="font-size:21px">Running total after costs, 496 one-minute-range trades. Grey band: middle 90% of 200 random-direction runs.</div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:16px;padding:10px">{direction_svg(1060, 470)}</div>
</div>"""),
    OUT_X / "5-drawdown.png": (1200, 675, f"""
<div style="padding:36px 56px;display:grid;gap:16px">
  <div style="display:flex;justify-content:space-between;align-items:baseline"><h2>Two years for +4.3R, with a 32.7R hole</h2><div class="handle">@Purrtfolio</div></div>
  <div class="sub" style="font-size:21px">544 trades after costs. At 0.5% risk per trade that hole is a 16.4% drawdown. Most prop firms stop you at 10%.</div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:16px;padding:10px">{equity_svg(1060, 470)}</div>
</div>"""),
    OUT_X / "6-calculator.png": (1200, 675, f"""
<div style="padding:52px 64px;display:grid;gap:30px;height:100%;align-content:center">
  <div class="handle">@Purrtfolio</div>
  <h1 style="font-size:58px">Your win rate has to beat costs,<br>not just the coin flip.</h1>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:{RULE};border:1px solid {RULE};border-radius:16px;overflow:hidden">
    <div style="background:{SURFACE};padding:26px 28px;display:grid;gap:8px"><div style="font:600 52px/1 {DISPLAY}">25.0%</div><div class="sub" style="font-size:20px">coin flip at 3:1</div></div>
    <div style="background:{SURFACE};padding:26px 28px;display:grid;gap:8px"><div style="font:600 52px/1 {DISPLAY};color:{LOSS}">27.4%</div><div class="sub" style="font-size:20px">break-even after a 0.57-pt spread on a 6-pt stop</div></div>
    <div style="background:{SURFACE};padding:26px 28px;display:grid;gap:8px"><div style="font:600 52px/1 {DISPLAY}">280</div><div class="sub" style="font-size:20px">trades before a 35% win rate means anything</div></div>
  </div>
  <div class="sub">Check your own setup with the free calculator on the study page.</div>
</div>"""),
}

for out, (w, h, body) in cards.items():
    src = SCR / f"card_{out.stem}.html"
    src.write_text(page(w, h, body), encoding="utf-8")
    out.unlink(missing_ok=True)
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={w},{h}", "--virtual-time-budget=8000",
                    f"--screenshot={out}", src.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):  # headless Edge can return before the PNG is written
        if out.exists() and out.stat().st_size:
            break
        time.sleep(0.5)
    print(out, out.stat().st_size)

"""Render og.png (link preview) and the X thread images for the one-minute ORB study.

Run from anywhere: py -3.14 research/studies/one-minute-orb/make_cards.py
Needs Edge or Chrome (set BROWSER_EXE to override). The diagram is read from the
deployed page, so edit it there first.
"""
import os
import re
import subprocess
import tempfile
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

INK, MUTED, FAINT, RULE = "#16202b", "#5b6470", "#8a919a", "#d9dcd4"
GROUND, SURFACE, ACCENT, ACCENT_SOFT = "#f2f3ef", "#ffffff", "#0e6e74", "#dcecec"
SERIES, CLAIM, NEUTRAL, WIN, LOSS = "#008d9e", "#c23b3b", "#7a7f87", "#2f7d4a", "#b0413e"

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:'
         'opsz,wght@12..96,700;12..96,800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap">')

measured = {1: 48.5, 2: 33.6, 3: 26.1, 5: 15.6}


def chart_svg(w=640, h=360):
    L, R, T, B = 60, 30, 20, 50
    def x(k):
        return L + (k - 1) / (5.5 - 1) * (w - L - R)
    def y(v):
        return T + (1 - v / 55) * (h - T - B)
    mono = 'font-family="IBM Plex Mono, monospace"'
    parts = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
    for v in (0, 10, 20, 30, 40, 50):
        parts.append(f'<line x1="{L}" x2="{w-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{RULE}"/>')
        parts.append(f'<text x="{L-10}" y="{y(v)+5:.1f}" text-anchor="end" fill="{FAINT}" font-size="15" {mono}>{v}%</text>')
    for k in (1, 2, 3, 4, 5):
        parts.append(f'<text x="{x(k):.1f}" y="{h-B+24}" text-anchor="middle" fill="{FAINT}" font-size="15" {mono}>{k}:1</text>')
    parts.append(f'<text x="{(L+w-R)/2:.0f}" y="{h-4}" text-anchor="middle" fill="{MUTED}" font-size="15">reward-to-risk</text>')
    parts.append(f'<rect x="{x(3)-18:.1f}" y="{y(36):.1f}" width="36" height="{y(34)-y(36):.1f}" fill="{CLAIM}" fill-opacity=".25" stroke="{CLAIM}" stroke-width="2" rx="2"/>')
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
    tokens = {"var(--accent-soft)": ACCENT_SOFT, "var(--accent)": ACCENT, "var(--neutral)": NEUTRAL,
              "var(--muted)": MUTED, "var(--win)": WIN, "var(--loss)": LOSS, "var(--ink)": INK,
              "var(--rule)": RULE, "var(--surface)": SURFACE}
    for k, v in tokens.items():
        svg = svg.replace(k, v)
    svg = svg.replace(f"color-mix(in srgb, {NEUTRAL} 22%, transparent)", "#e3e4e2")
    return svg.replace('<svg viewBox="0 0 640 300"', '<svg viewBox="0 0 640 300" width="1040" height="487"')


BASE_CSS = f"""
*{{box-sizing:border-box}} html,body{{margin:0}}
body{{width:{{W}}px;height:{{H}}px;background:{GROUND};color:{INK};font-family:'IBM Plex Sans',sans-serif;overflow:hidden}}
.handle{{font:500 22px 'IBM Plex Mono',monospace;color:{ACCENT}}}
h1{{font:800 64px/1.0 'Bricolage Grotesque',sans-serif;letter-spacing:-.03em;margin:0}}
h2{{font:700 40px/1.1 'Bricolage Grotesque',sans-serif;letter-spacing:-.02em;margin:0}}
.sub{{font-size:24px;color:{MUTED};line-height:1.35}}
.tag{{display:inline-block;font:700 16px 'IBM Plex Sans';letter-spacing:.06em;text-transform:uppercase;color:{LOSS};border:2px solid {LOSS};padding:6px 10px;border-radius:5px}}
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
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:14px;padding:14px">{chart_svg(560, 360)}</div>
</div>"""),
    OUT_X / "1-how-it-works.png": (1200, 675, f"""
<div style="padding:40px 56px;display:grid;gap:18px">
  <div style="display:flex;justify-content:space-between;align-items:baseline"><h2>How the one-minute ORB scalp works</h2><div class="handle">@Purrtfolio</div></div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:14px;padding:12px 30px;justify-self:center">{mechanics_svg()}</div>
</div>"""),
    OUT_X / "2-coin-flip.png": (1200, 675, f"""
<div style="padding:40px 56px;display:grid;grid-template-columns:420px 1fr;gap:30px;align-items:center;height:100%">
  <div style="display:grid;gap:18px">
    <div class="handle">@Purrtfolio</div>
    <h2>Every measured win rate sits on the coin-flip curve</h2>
    <div class="sub">A 3:1 bracket on a random walk wins 1 / (1 + 3) = 25%. This setup won 26.1% across 544 trades on real tick data.</div>
  </div>
  <div style="background:{SURFACE};border:1px solid {RULE};border-radius:14px;padding:14px">{chart_svg(640, 420)}</div>
</div>"""),
    OUT_X / "3-lesson.png": (1200, 675, f"""
<div style="height:100%;background:{INK};color:{GROUND};padding:70px 80px;display:grid;align-content:center;gap:30px">
  <div style="font:500 22px 'IBM Plex Mono',monospace;color:#9aa4ae;text-transform:uppercase;letter-spacing:.08em">The lesson</div>
  <div style="font:700 56px/1.12 'Bricolage Grotesque',sans-serif;letter-spacing:-.02em;max-width:980px">Before you believe a win rate on a fixed R:R trade, compare it with 1 / (1 + R:R).</div>
  <div style="font-size:26px;color:#c9d0d6">26% at 3:1 is what randomness produces.</div>
  <div style="font:500 22px 'IBM Plex Mono',monospace;color:#5bb9be">@Purrtfolio</div>
</div>"""),
}

for out, (w, h, body) in cards.items():
    src = SCR / f"card_{out.stem}.html"
    src.write_text(page(w, h, body), encoding="utf-8")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={w},{h}", "--virtual-time-budget=4000",
                    f"--screenshot={out}", src.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(out, out.stat().st_size)

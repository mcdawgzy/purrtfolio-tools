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
}

for out, (w, h, body) in cards.items():
    src = SCR / f"card_{out.stem}.html"
    src.write_text(page(w, h, body), encoding="utf-8")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={w},{h}", "--virtual-time-budget=8000",
                    f"--screenshot={out}", src.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(out, out.stat().st_size)

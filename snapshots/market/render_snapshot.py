#!/usr/bin/env python3
"""
Render market snapshot PNG from JSON report.

Output: output/market_snapshot_YYYYMMDD.png
"""

import json
import os
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def load_report(date_str: str = None, input_dir: str = "output") -> dict:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(input_dir, f"market_report_{date_str}.json")
    with open(path, "r") as f:
        return json.load(f)


def get_move_style(pct: float):
    """Return (text_color, bg_color, triangle_char) for pct."""
    if pct is None or abs(pct) < 0.05:
        return ("#88929E", "#1E2228", "▬")
    elif pct > 0:
        return ("#34D399", "#064E3B", "▲")
    else:
        return ("#F87171", "#7F1D1D", "▼")


def render_market_snapshot(report: dict, output_path: str = None,
                           output_dir: str = "output", date_str: str = None):
    """Render compact, readable market snapshot."""
    rows = report["rows"]

    if output_path is None:
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        output_path = os.path.join(output_dir, f"market_snapshot_{date_str}.png")

    os.makedirs(output_dir, exist_ok=True)

    # ─── Color Palette ─────────────────────────────────────────────────────
    BG          = "#0A0E14"
    PANEL       = "#11151A"
    CARD        = "#151A20"
    CARD_ALT    = "#13181E"
    LINE        = "#1F2630"
    LINE_ACCENT = "#D4A84E"

    TEXT        = "#E8EBEF"
    TEXT_DIM    = "#9BA4B0"
    TEXT_MUTED  = "#6B7580"

    BRASS       = "#D4A84E"
    BRASS_BG    = "#3D341A"

    # ─── Prepare data ──────────────────────────────────────────────────────
    data_rows = [r for r in rows if r["type"] == "row"]
    top5 = sorted(data_rows, key=lambda x: abs(x.get("pct_change", 0)), reverse=True)[:5]
    top5_names = set(r["name"] for r in top5)

    sections = {}
    section_order = []
    current_section = None
    for row in rows:
        if row["type"] == "section":
            current_section = row["name"]
            sections[current_section] = []
            section_order.append(current_section)
        elif current_section:
            sections[current_section].append(row)

    # ─── Figure setup ──────────────────────────────────────────────────────
    # Count wrapped lines to size figure properly
    import textwrap
    total_wrapped_lines = 0
    for sec in section_order:
        for row in sections[sec]:
            drv = row.get("driver", "")
            # Driver col is ~0.42 wide; at fontsize 8.5, ~1 char ≈ 0.0035 of axes
            wrap_width = max(35, int(0.42 / 0.0042))
            wrapped = textwrap.wrap(drv, width=wrap_width)
            total_wrapped_lines += max(1, len(wrapped))

    total_data_rows = sum(len(v) for v in sections.values())
    n_sections = len(sections)
    # Base height + per-row + per-wrapped-line + section gaps
    fig_height = 5.0 + total_data_rows * 0.22 + total_wrapped_lines * 0.11 + n_sections * 0.28

    # 16:9 aspect ratio at 13 wide → 7.3125 tall
    fig, ax = plt.subplots(figsize=(13, max(7.3, fig_height)))
    ax.axis('off')
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # ─── Layout ────────────────────────────────────────────────────────────
    LEFT   = 0.035
    RIGHT  = 0.965
    TOP    = 0.985
    CONTENT_W = RIGHT - LEFT

    COL_NAME   = LEFT + 0.005
    COL_LEVEL  = LEFT + 0.21
    COL_MOVE   = LEFT + 0.35
    COL_DRIVER = LEFT + 0.46

    current_y = TOP

    # ─── Helpers ───────────────────────────────────────────────────────────
    def add_rect(x, y, w, h, facecolor, edgecolor=None, lw=0, radius=0.004):
        patch = mpatches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            transform=ax.transAxes,
            facecolor=facecolor,
            edgecolor=edgecolor or "none",
            linewidth=lw,
            mutation_scale=1000,
        )
        ax.add_patch(patch)
        return patch

    def t(x, y, s, **kw):
        defaults = dict(transform=ax.transAxes, va='center', ha='left', family='sans-serif')
        defaults.update(kw)
        ax.text(x, y, s, **defaults)

    def divider(y, x1=LEFT+0.02, x2=RIGHT-0.02):
        ax.plot([x1, x2], [y, y], transform=ax.transAxes, color=LINE, lw=0.5, clip_on=False)

    # ════════════════════════════════════════════════════════════════════════
    # MASTHEAD
    # ════════════════════════════════════════════════════════════════════════
    mh_h = 0.045
    mh_y = current_y - mh_h
    add_rect(LEFT, mh_y, CONTENT_W, mh_h, PANEL, edgecolor=LINE_ACCENT, lw=0.8)

    t(LEFT + 0.015, mh_y + mh_h * 0.55, "Market Snapshot",
      fontsize=17, fontweight='bold', color=TEXT)

    date_s = datetime.now().strftime("%a, %b %d")
    t(RIGHT - 0.015, mh_y + mh_h * 0.55, date_s,
      fontsize=10, color=TEXT_DIM, ha='right')

    current_y = mh_y - 0.008

    # ════════════════════════════════════════════════════════════════════════
    # TOP 5 MOVERS BAND
    # ════════════════════════════════════════════════════════════════════════
    mv_h = 0.05
    mv_y = current_y - mv_h
    add_rect(LEFT, mv_y, CONTENT_W, mv_h, CARD, edgecolor=LINE, lw=0.5)

    t(LEFT + 0.012, mv_y + mv_h * 0.78, "BIGGEST MOVERS",
      fontsize=7.5, fontweight='bold', color=TEXT_MUTED)

    card_w = (CONTENT_W - 0.025) / 5
    gap = 0.003
    start_x = LEFT + 0.012
    card_y = mv_y + mv_h * 0.42

    for i, m in enumerate(top5):
        cx = start_x + i * (card_w + gap)
        pct = m.get("pct_change", 0)
        mc, mbg, tri = get_move_style(pct)
        level = m["level_move"].split("(")[0].strip()

        add_rect(cx, card_y - 0.018, card_w, 0.036, CARD_ALT, radius=0.003)

        t(cx + 0.006, card_y + 0.007, m["name"],
          fontsize=8, fontweight='bold', color=TEXT_DIM)
        t(cx + 0.006, card_y - 0.002, level,
          fontsize=7, color=TEXT_MUTED, family='monospace')
        t(cx + card_w/2, card_y - 0.013, f"{tri}{abs(pct):.1f}%",
          fontsize=11, fontweight='bold', color=mc, ha='center')

    current_y = mv_y - 0.012

    # ════════════════════════════════════════════════════════════════════════
    # SECTIONS
    # ════════════════════════════════════════════════════════════════════════
    row_h_single = 0.020
    sec_h = 0.020
    line_spacing = 0.012
    wrap_width = max(35, int(0.42 / 0.0042))

    for sec_name in section_order:
        sec_rows = sections[sec_name]
        if not sec_rows:
            continue

        # Section header
        sec_y = current_y - sec_h
        dx = LEFT + 0.008
        dy = sec_y + sec_h * 0.5
        diamond = mpatches.Rectangle((dx-0.0025, dy-0.0025), 0.005, 0.005,
                                     transform=ax.transAxes, facecolor=BRASS,
                                     edgecolor='none', angle=45)
        ax.add_patch(diamond)
        t(dx + 0.008, dy, sec_name.upper(),
          fontsize=9, fontweight='bold', color="#B8BEC8")

        current_y = sec_y - 0.003

        for ri, row in enumerate(sec_rows):
            is_top = row["name"] in top5_names
            pct = row.get("pct_change", 0)
            mc, mbg, tri = get_move_style(pct)

            # Wrap driver
            drv = row["driver"]
            wrapped = textwrap.wrap(drv, width=wrap_width)
            if not wrapped:
                wrapped = [drv]
            n_lines = len(wrapped)
            row_block_h = max(row_h_single, n_lines * line_spacing + 0.006)

            ry = current_y - row_block_h * 0.5

            # Row background for top movers
            if is_top:
                add_rect(LEFT + 0.008, ry - row_block_h/2,
                         CONTENT_W - 0.016, row_block_h * 0.92,
                         (212/255, 168/255, 78/255, 0.035), radius=0.003)

            if ri > 0:
                divider(ry + row_block_h/2 - 0.002)

            # Name (vertically centered on first line)
            nx = COL_NAME
            if is_top:
                circle = mpatches.Circle((nx - 0.006, ry + (n_lines-1)*line_spacing/2),
                                         0.0018, transform=ax.transAxes,
                                         facecolor=BRASS, edgecolor='none', zorder=10)
                ax.add_patch(circle)
                t(nx, ry + (n_lines-1)*line_spacing/2, row["name"],
                  fontsize=9.5, fontweight='bold', color=TEXT)
            else:
                t(nx, ry + (n_lines-1)*line_spacing/2, row["name"],
                  fontsize=9.5, color=TEXT)

            # Level
            level = row["level_move"].split("(")[0].strip()
            t(COL_LEVEL, ry + (n_lines-1)*line_spacing/2, level,
              fontsize=9.5, fontweight='bold', color=TEXT, family='monospace')

            # Move badge
            pct_str = ""
            if "(" in row["level_move"]:
                pct_str = row["level_move"].split("(")[1].replace(")", "").strip()

            if pct_str:
                badge_text = f"{tri}{pct_str}"
                bx = COL_MOVE
                by = ry + (n_lines-1)*line_spacing/2
                bw = 0.07
                bh = 0.013
                add_rect(bx, by - bh/2, bw, bh, mbg, radius=0.002)
                t(bx + bw/2, by, badge_text,
                  fontsize=7.5, fontweight='bold', color=mc, ha='center')

            # Driver (wrapped)
            for li, line in enumerate(wrapped):
                line_y = ry + (n_lines - 1 - li) * line_spacing - line_spacing/2
                t(COL_DRIVER, line_y, line,
                  fontsize=8.5,
                  fontweight='normal',
                  color=TEXT_DIM if not is_top else TEXT)

            current_y = ry - row_block_h/2 - 0.001

        current_y -= 0.006

    # ════════════════════════════════════════════════════════════════════════
    # COLOPHON
    # ════════════════════════════════════════════════════════════════════════
    col_y = current_y - 0.012
    divider(col_y + 0.012)

    t(LEFT + 0.015, col_y, "Source: Yahoo Finance  •  Auto-generated  •  Not financial advice",
      fontsize=7, color=TEXT_MUTED)
    t(RIGHT - 0.015, col_y, "@Purrtfolio",
      fontsize=9, fontweight='bold', color=BRASS, ha='right')

    # Save
    plt.savefig(output_path, dpi=200, facecolor=BG, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)
    print(f"Rendered: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    report = load_report(date_str)
    render_market_snapshot(report, date_str=date_str)

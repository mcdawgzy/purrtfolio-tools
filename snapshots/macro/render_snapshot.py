#!/usr/bin/env python3
"""
Market Snapshot Renderer - Professional 16:9 Tear Sheet
Fixed: explicit y-tracking with text heights, no overlap.
"""

import json
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def load_report(date_str=None, input_dir="output"):
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = f"{input_dir}/market_report_{date_str}.json"
    with open(path, "r") as f:
        return json.load(f)


def get_move_color(pct):
    if pct is None or abs(pct) < 0.05:
        return "#94A3B8"
    elif pct > 0:
        return "#22C55E"
    return "#EF4444"


def get_move_arrow(pct):
    if pct is None or abs(pct) < 0.05:
        return " "
    elif pct > 0:
        return "\u25B2"
    return "\u25BC"


def fmt_level(lm):
    return lm.split("(")[0].strip()


def fmt_pct(lm):
    if "(" in lm:
        return lm.split("(")[1].replace(")", "").strip()
    return ""


def truncate_driver(drv, max_chars=42):
    """Hard-trim driver to max_chars. No period-cutting — drivers are already short."""
    if len(drv) <= max_chars:
        return drv
    return drv[:max_chars - 3] + "..."


def render_market_snapshot(report, output_path=None, output_dir="output", date_str=None):
    rows = report["rows"]
    if output_path is None:
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        output_path = f"{output_dir}/market_snapshot_{date_str}.png"
    os.makedirs(output_dir, exist_ok=True)

    BG = "#0A0E14"; PANEL = "#11161D"; TEXT = "#E8EBEF"
    TEXT_DIM = "#7E8A9A"; TEXT_MUT = "#5C6B7A"; LINE = "#1E2A38"; ACCENT = "#C9A24E"

    data_rows = [r for r in rows if r["type"] == "row"]
    top5 = sorted(data_rows, key=lambda x: abs(x.get("pct_change", 0)), reverse=True)[:5]
    top5_names = {r["name"] for r in top5}

    sections = {}; sec_name = None; sec_order = []
    for row in rows:
        if row["type"] == "section":
            sec_name = row["name"]; sections[sec_name] = []; sec_order.append(sec_name)
        elif sec_name:
            sections[sec_name].append(row)

    total_rows = sum(len(v) for v in sections.values())
    n_sec = len(sec_order)

    # ─── Layout constants (all explicit, no guessing) ──────────────────
    # Font sizes
    ASSET_FS = 9.5
    DRV_FS = 8
    SEC_FS = 7.5

    # Text heights (approx: font_size * 0.006)
    H_TITLE    = 0.022   # masthead title fs=13
    H_DATE     = 0.016   # date fs=8.5
    H_LABEL    = 0.013   # "BIGGEST MOVERS" fs=7
    H_COLHDR   = 0.013   # column headers fs=6.5
    H_SECTHDR  = 0.017   # section header fs=7.5
    H_DATAROW  = 0.019   # data row (max of asset/level/pct/driver)
    H_FOOTER   = 0.011   # footer fs=6-8

    # Gaps
    GAP_TOP         = 0.003   # padding top of figure
    GAP_SUBTITLE    = 0.006   # subtitle below masthead line
    GAP_BIGGERSUB   = 0.006   # label below biggest movers line
    GAP_BIGGERSUB2  = 0.004   # gap between label and cards
    GAP_MV2COL      = 0.008   # gap between movers panel and column headers
    GAP_COL2SEC     = 0.006   # gap between column header line and section header
    GAP_SECT2ROW    = 0.012   # gap between section header and first row
    GAP_ROW2ROW     = 0.002   # gap between data rows
    GAP_SEC2SEC     = 0.008   # gap between sections
    GAP_FOOT        = 0.010   # footer above bottom edge

    # Heights
    MAST_H       = H_TITLE + 0.004 + H_DATE + 0.004  # title + subtitle + date + padding
    BIGGER_H     = 0.050   # fixed panel height for movers
    CARD_TOP_PAD = 0.012   # padding below "BIGGEST MOVERS" label before cards
    CARD_H       = BIGGER_H - CARD_TOP_PAD - 0.006  # remaining height for cards
    COLHDR_H     = H_COLHDR + 0.006  # column header + line
    # Row height: asset/level/% baseline + gap + dynamic driver height
    DRV_LINE_H   = DRV_FS * 0.006  # ~0.048
    MAX_DRV_LINES = 3  # max lines per driver
    DRV_BLOCK_H  = DRV_LINE_H * MAX_DRV_LINES  # max driver height
    ROW_H        = H_DATAROW + 0.004 + DRV_BLOCK_H  # asset row + gap + max driver block

    # Total height estimate
    est_h = GAP_TOP + MAST_H + BIGGER_H + GAP_MV2COL + COLHDR_H
    est_h += n_sec * (H_SECTHDR + GAP_SECT2ROW + H_DATAROW * 3 + GAP_SEC2SEC)  # rough: 3 rows per sec
    est_h += H_FOOTER + GAP_FOOT

    if est_h > 0.96:
        s = 0.96 / est_h
        CARD_H *= s; BIGGER_H *= s
        H_DATAROW *= s; ROW_H *= s
        ASSET_FS = max(8, int(ASSET_FS * s))
        DRV_FS = max(6.5, int(DRV_FS * s))

    fig = plt.figure(figsize=(12.8, 7.2))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(BG)

    LEFT = 0.04; RIGHT = 0.96; CONTENT_W = RIGHT - LEFT
    COL_NAME    = LEFT + 0.005
    COL_LEVEL   = LEFT + 0.18
    COL_MOVE    = LEFT + 0.28
    COL_DRIVER  = LEFT + 0.38

    # ─── Drawing helpers ─────────────────────────────────────────────
    def dtxt(x, y, txt, fs=9, wt='normal', clr=TEXT, h='left', v='bottom'):
        t = ax.text(x, y, txt, fontsize=fs, fontweight=wt, color=clr,
                    ha=h, va=v, family='sans-serif', transform=ax.transAxes, clip_on=True)
        return t

    def dline(y, x1=LEFT, x2=RIGHT, clr=LINE, lw=0.5):
        ax.plot([x1, x2], [y, y], transform=ax.transAxes, color=clr, lw=lw, clip_on=False)

    def drect(x, y, w, h, fc=PANEL, ec=None, lw=0, a=1.0):
        ax.add_patch(mpatches.Rectangle((x, y), w, h,
            transform=ax.transAxes, facecolor=fc, edgecolor=ec, lw=lw, alpha=a, zorder=0))

    def dcircle(x, y, r=0.002, c=ACCENT):
        ax.add_patch(mpatches.Circle((x, y), r, transform=ax.transAxes, facecolor=c, edgecolor='none', zorder=10))

    # ─── Y tracking ──────────────────────────────────────────────────
    y = 1.0 - GAP_TOP

    # ─── 1. MASTHEAD ─────────────────────────────────────────────────
    mh_top = y
    dtxt(LEFT, y, "MARKET SNAPSHOT", fs=13, wt='bold', clr=TEXT)
    y -= H_TITLE + 0.004
    date_s = datetime.now().strftime("%A, %B %d, %Y")
    dtxt(RIGHT, y, date_s, fs=8.5, wt='normal', clr=TEXT_DIM, h='right')
    y -= H_DATE + 0.004
    mh_bottom = y - 0.003
    panel_h = mh_top - mh_bottom

    drect(LEFT, mh_bottom, CONTENT_W, panel_h, PANEL)
    dline(mh_bottom)
    y = mh_bottom - 0.003

    # ─── 2. BIGGEST MOVERS ───────────────────────────────────────────
    mv_top = y
    drect(LEFT, mv_top - BIGGER_H, CONTENT_W, BIGGER_H, PANEL)
    dline(mv_top)

    # Label at top of panel
    label_y = mv_top - CARD_TOP_PAD
    dtxt(LEFT, label_y, "BIGGEST MOVERS", fs=7, wt='bold', clr=TEXT_MUT)
    label_bottom = label_y - H_LABEL

    # Cards BELOW the label
    card_top = label_bottom + GAP_BIGGERSUB2
    card_bottom = mv_top - BIGGER_H + 0.004
    card_h = card_bottom - card_top

    card_w = (CONTENT_W - 0.04) / 5
    card_gap = 0.004
    cx_start = LEFT + 0.02

    for i, m in enumerate(top5):
        cx = cx_start + i * (card_w + card_gap) + card_w / 2
        pct = m.get("pct_change", 0)
        mc = get_move_color(pct); tri = get_move_arrow(pct)
        level = fmt_level(m["level_move"])

        # Highlight card for #1 mover
        if i == 0:
            drect(cx - card_w*0.45, card_bottom, card_w*0.9, card_h, PANEL, ec=mc, lw=0.8)

        # Asset name at top of card
        dtxt(cx, card_top, m["name"], fs=7, wt='bold', clr=TEXT_DIM, h='center')
        # Level below name
        dtxt(cx, card_top + card_h * 0.30, level, fs=6.5, wt='normal', clr=TEXT_MUT, h='center')
        # Big % at bottom of card
        dtxt(cx, card_bottom, f"{tri} {abs(pct):.2f}%", fs=11, wt='bold', clr=mc, h='center')

    y = mv_top - BIGGER_H - 0.003

    # ─── 3. COLUMN HEADERS ───────────────────────────────────────────
    col_top = y
    dtxt(COL_NAME, col_top, "ASSET", fs=6.5, wt='bold', clr=TEXT_MUT)
    dtxt(COL_LEVEL + 0.06, col_top, "LEVEL", fs=6.5, wt='bold', clr=TEXT_MUT, h='right')
    dtxt(COL_MOVE + 0.04, col_top, "24H", fs=6.5, wt='bold', clr=TEXT_MUT, h='right')
    dtxt(COL_DRIVER, col_top, "DRIVER", fs=6.5, wt='bold', clr=TEXT_MUT)

    col_bottom = col_top - H_COLHDR
    y = col_bottom
    dline(y)
    y -= GAP_COL2SEC

    # ─── 4. DATA SECTIONS ────────────────────────────────────────────
    for si, sec_name in enumerate(sec_order):
        sec_rows = sections[sec_name]
        if not sec_rows:
            continue

        if si > 0:
            dline(y, clr=LINE, lw=0.3)
            y -= GAP_SEC2SEC

        # Section header at y (baseline), text extends DOWNWARD
        dcircle(LEFT + 0.003, y, 0.0025, "#9AA4B0")
        dtxt(LEFT + 0.01, y, sec_name.upper(), fs=SEC_FS, wt='bold', clr="#9AA4B0")
        y -= H_SECTHDR + GAP_SECT2ROW

        # Data rows
        for ri, row in enumerate(sec_rows):
            is_top = row["name"] in top5_names
            pct = row.get("pct_change", 0)
            mc = get_move_color(pct); tri = get_move_arrow(pct)

            # Highlight top mover row
            if is_top:
                drect(LEFT, y - ROW_H, CONTENT_W, ROW_H, ACCENT, a=0.03)

            # Divider line between rows
            if ri > 0:
                dline(y - ROW_H + GAP_ROW2ROW/2, clr=LINE, lw=0.2)

            # Draw row at y (baseline), text extends DOWNWARD
            if is_top:
                dcircle(COL_NAME + 0.004, y, 0.0018)
                dtxt(COL_NAME + 0.01, y, row["name"], fs=ASSET_FS, wt='bold', clr=TEXT)
            else:
                dtxt(COL_NAME, y, row["name"], fs=ASSET_FS, wt='normal', clr=TEXT)

            # Level column
            level = fmt_level(row["level_move"])
            dtxt(COL_LEVEL + 0.12, y, level, fs=9, wt='normal', clr=TEXT, h='right')

            # % column
            pct_str = fmt_pct(row["level_move"])
            if pct_str:
                dtxt(COL_MOVE + 0.07, y, f"{tri} {pct_str}", fs=8, wt='bold', clr=mc, h='right')

            # Driver column — auto-wrap to 2-3 lines
            drv = row["driver"]
            col_w = RIGHT - COL_DRIVER
            max_chars = max(1, int(col_w * 55))  # ~35 chars per line at fs=8
            drv_lines = []; words = drv.split()
            line = ""
            for w in words:
                test = f"{line} {w}".strip()
                if len(test) > max_chars:
                    drv_lines.append(line)
                    line = w
                else:
                    line = test
            if line:
                drv_lines.append(line)
            # Draw wrapped lines (max 3)
            drv_line_h = DRV_LINE_H
            for li, dl in enumerate(drv_lines[:MAX_DRV_LINES]):
                dtxt(COL_DRIVER, y - DRV_LINE_H - li * drv_line_h, dl, fs=DRV_FS, wt='normal', clr=TEXT_DIM)

            # Advance y past this row
            y -= ROW_H

        y -= GAP_SEC2SEC * 0.5

    # ─── 5. FOOTER ───────────────────────────────────────────────────
    footer_y = max(0.05, y - GAP_FOOT)
    dline(footer_y)
    dtxt(LEFT, footer_y - H_FOOTER, "Source: Yahoo Finance", fs=6, wt='normal', clr=TEXT_MUT)
    dtxt(RIGHT, footer_y - H_FOOTER, "@Purrtfolio", fs=8, wt='bold', clr=ACCENT, h='right')

    plt.savefig(output_path, dpi=200, facecolor=BG)
    plt.close(fig)
    print(f"Rendered: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    ds = sys.argv[1] if len(sys.argv) > 1 else None
    render_market_snapshot(load_report(ds))
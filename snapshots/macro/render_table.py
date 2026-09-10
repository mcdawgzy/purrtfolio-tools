#!/usr/bin/env python3
"""
Macro Market Update Renderer - Clean Rebuild
Fixed row height, proper scaling, all rows visible.
"""

import json
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import textwrap


def load_report(date_str: str = None, input_dir: str = "output") -> dict:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = f"{input_dir}/market_report_{date_str}.json"
    with open(path, "r") as f:
        return json.load(f)


def get_pct_color(pct: float) -> str:
    if pct is None:
        return "#888888"
    elif pct > 0.1:
        return "#00b85c"
    elif pct < -0.1:
        return "#e03e3e"
    else:
        return "#faad14"


def wrap_text(text: str, max_width: int) -> str:
    if not text:
        return ""
    return textwrap.fill(text, width=max_width)


def render_market_update(report: dict, output_path: str = None, output_dir: str = "output", date_str: str = None):
    rows = report["rows"]
    timestamp = report["timestamp"]

    if output_path is None:
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        output_path = f"{output_dir}/market_snapshot_{date_str}.png"

    os.makedirs(output_dir, exist_ok=True)

    # Count rows
    data_rows = [r for r in rows if r["type"] == "row"]
    section_rows = [r for r in rows if r["type"] == "section"]
    n_data = len(data_rows)
    n_sections = len(section_rows)
    n_total = n_data + n_sections

    # ─── Fixed layout constants ─────────────────────────────────────────────
    ROW_HEIGHT_IN = 0.38      # inches per row
    SECTION_HEIGHT_IN = 0.30  # inches per section header
    HEADER_HEIGHT_IN = 0.50   # inches for column headers
    TITLE_HEIGHT_IN = 0.70    # inches for title block
    FOOTER_HEIGHT_IN = 0.45   # inches for footer
    MARGIN_TOP_IN = 0.20
    MARGIN_BOTTOM_IN = 0.20
    BLANK_ROW_IN = ROW_HEIGHT_IN * 1.5  # spacer before footer

    fig_height = (TITLE_HEIGHT_IN + HEADER_HEIGHT_IN + 
                  n_sections * SECTION_HEIGHT_IN + 
                  n_data * ROW_HEIGHT_IN + 
                  BLANK_ROW_IN +
                  FOOTER_HEIGHT_IN + MARGIN_TOP_IN + MARGIN_BOTTOM_IN)

    # Calculate actual content width and use a tighter figure
    LEFT_MARGIN = 0.35
    RIGHT_MARGIN = 0.35
    usable_width = 17 - LEFT_MARGIN - RIGHT_MARGIN
    # Figure width = content width + margins
    fig_width = usable_width + LEFT_MARGIN + RIGHT_MARGIN

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')

    # Colors
    BG = "#0d1117"
    ROW_EVEN = "#161b22"
    ROW_ODD = "#0d1117"
    SECTION_BG = "#111827"
    HEADER_BG = "#1f2937"
    TEXT = "#e6edf3"
    TEXT_DIM = "#8b949e"
    TEXT_MUTED = "#6e7681"
    BLUE = "#58a6ff"
    GREEN = "#00b85c"
    RED = "#e03e3e"
    AMBER = "#faad14"
    BORDER = "#30363d"
    GRID = "#21262d"

    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # ─── Y coordinate system (inches from bottom) ───────────────────────────
    y_bottom = 0
    y_top = fig_height

    # Footer position
    footer_y = FOOTER_HEIGHT_IN

    # Data area starts above footer
    data_top = fig_height - MARGIN_TOP_IN - TITLE_HEIGHT_IN - HEADER_HEIGHT_IN

    # Column x positions (inches from left)
    # LEFT_MARGIN and RIGHT_MARGIN already defined above with usable_width
    col_name_w = usable_width * 0.20
    col_level_w = usable_width * 0.18
    col_driver_w = usable_width * 0.62

    # Center-justify: position columns in the middle of their allocated widths
    col_name_x = LEFT_MARGIN + col_name_w / 2
    col_level_x = LEFT_MARGIN + col_name_w + col_level_w / 2
    col_driver_x = LEFT_MARGIN + col_name_w + col_level_w + col_driver_w / 2

    # ─── Draw title block ───────────────────────────────────────────────────
    dt = datetime.now()
    date_fmt = dt.strftime("%B %d %Y")
    title_y = fig_height - MARGIN_TOP_IN - TITLE_HEIGHT_IN / 2

    # Title - centered
    title_center_x = LEFT_MARGIN + usable_width / 2
    ax.text(title_center_x, title_y + 0.15, "MARKET SNAPSHOT",
            fontsize=22, fontweight='bold', color=TEXT, va='center', ha='center')
    ax.text(title_center_x, title_y - 0.15, "24-Hour Change  •  Key Levels & Drivers",
            fontsize=11, color=TEXT_DIM, va='center', ha='center')

    # Date on right side
    ax.text(LEFT_MARGIN + usable_width, title_y + 0.15, date_fmt,
            fontsize=15, fontweight='medium', color=BLUE, va='center', ha='right')

    # Rule under title
    rule_y = fig_height - MARGIN_TOP_IN - TITLE_HEIGHT_IN
    ax.hlines(rule_y, LEFT_MARGIN, LEFT_MARGIN + usable_width, colors=BORDER, linewidth=1)

    # ─── Column headers ─────────────────────────────────────────────────────
    header_y = rule_y - HEADER_HEIGHT_IN / 2
    ax.add_patch(mpatches.Rectangle(
        (LEFT_MARGIN, header_y - HEADER_HEIGHT_IN/2),
        usable_width, HEADER_HEIGHT_IN,
        facecolor=HEADER_BG, edgecolor=BORDER, linewidth=0.8
    ))

    for i, (hdr, x) in enumerate(zip(["Indicator", "Level / Move", "Driver"],
                                       [col_name_x, col_level_x, col_driver_x])):
        ax.text(x, header_y, hdr, fontsize=11, fontweight='bold' if i < 2 else 'normal',
                color=TEXT, va='center', ha='center')

    # Column separators
    for x in [LEFT_MARGIN + col_name_w, LEFT_MARGIN + col_name_w + col_level_w]:
        ax.vlines(x, footer_y + FOOTER_HEIGHT_IN, rule_y, colors=GRID, linewidth=0.5)

    # ─── Draw rows bottom-up ────────────────────────────────────────────────
    current_y = data_top

    # We need to process rows in order, but draw from top down
    # Build a flat list of (is_section, name, level_move, driver, pct)
    draw_rows = []
    for r in rows:
        if r["type"] == "section":
            draw_rows.append(("section", r["name"], "", "", None))
        else:
            draw_rows.append(("data", r["name"], r["level_move"], r["driver"], r.get("pct_change")))

    for idx, (rtype, name, level_move, driver, pct) in enumerate(draw_rows):
        if rtype == "section":
            h = SECTION_HEIGHT_IN
            y_center = current_y - h / 2
            # Section background
            ax.add_patch(mpatches.Rectangle(
                (LEFT_MARGIN, current_y - h), usable_width, h,
                facecolor=SECTION_BG, edgecolor=BORDER, linewidth=0.5
            ))
            # Section label - LEFT justified
            ax.text(LEFT_MARGIN, y_center, f"▸  {name}",
                    fontsize=11, fontweight='bold', color=BLUE, va='center', ha='left')
            current_y -= h
        else:
            h = ROW_HEIGHT_IN
            y_center = current_y - h / 2

            # Row background (alternating)
            bg = ROW_EVEN if idx % 2 == 0 else ROW_ODD
            if pct is not None:
                if pct > 0.1:
                    bg = (0, 184/255, 92/255, 0.06)
                elif pct < -0.1:
                    bg = (224/255, 62/255, 62/255, 0.06)
                else:
                    bg = (250/255, 173/255, 20/255, 0.06)

            ax.add_patch(mpatches.Rectangle(
                (LEFT_MARGIN, current_y - h), usable_width, h,
                facecolor=bg, edgecolor=GRID, linewidth=0.3
            ))

            # Name - centered in column
            ax.text(col_name_x, y_center, name,
                    fontsize=10, color=TEXT, va='center', ha='center')

            # Level/Move - centered in column
            pct_color = get_pct_color(pct)
            ax.text(col_level_x, y_center, level_move,
                    fontsize=10, fontweight='medium', color=pct_color, va='center', ha='center')

            # Driver - centered in column
            wrapped = wrap_text(driver, 110)
            ax.text(col_driver_x, y_center, wrapped,
                    fontsize=9.5, color=TEXT_DIM, va='center', ha='center', wrap=True)

            current_y -= h

    # ─── Footer ─────────────────────────────────────────────────────────────
    footer_center = footer_y + FOOTER_HEIGHT_IN / 2
    # Top rule
    ax.hlines(footer_y + FOOTER_HEIGHT_IN, LEFT_MARGIN, LEFT_MARGIN + usable_width, colors=BORDER, linewidth=0.8)
    # Footer text - left and right aligned
    ax.text(LEFT_MARGIN, footer_center, "Data: Yahoo Finance, CME, ICE  |  Not investment advice",
            fontsize=9, color=TEXT_MUTED, va='center', ha='left')
    ax.text(LEFT_MARGIN + usable_width, footer_center, "@Purrtfolio",
            fontsize=9, fontweight='medium', color=BLUE, va='center', ha='right')

    # Save
    plt.savefig(output_path, dpi=220, facecolor=BG, bbox_inches=None, pad_inches=0)
    plt.close(fig)
    print(f"Rendered: {output_path} ({fig_height:.1f}in tall, {n_data} data rows, {n_sections} sections)")
    return output_path


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    report = load_report(date_str)
    render_market_update(report)
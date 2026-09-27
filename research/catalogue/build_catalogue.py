"""Render the strategy catalogue from research/catalogue/studies/*.yaml.

Writes, next to this file:
  STRATEGY_CATALOGUE.md  every study, sources named (internal view; do not publish)
  public/studies.json    public studies, anonymised (the website / X feed)
  backtest-log.html      the filterable Backtest Log page, built from the feed

test_catalogue.py fails if any of them is stale, so run this after editing a study.

Usage (from the repo root):
    py -3.14 research/catalogue/build_catalogue.py
    py -3.14 research/catalogue/build_catalogue.py --check   # exit 1 if stale
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalogue import HERE, load_studies, render_markdown, render_public_json  # noqa: E402

MARKDOWN_PATH = HERE / "STRATEGY_CATALOGUE.md"
PUBLIC_JSON_PATH = HERE / "public" / "studies.json"
LOG_PAGE_PATH = HERE / "backtest-log.html"
LOG_TEMPLATE_PATH = HERE / "backtest_log_template.html"


def render_log_page(public_json: str) -> str:
    """Embed the public feed in the Backtest Log template (</ escaped for <script>)."""
    template = LOG_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__DATA__", public_json.replace("</", "<\\/"))


def outputs() -> dict[Path, str]:
    studies = load_studies()
    public = render_public_json(studies)
    return {
        MARKDOWN_PATH: render_markdown(studies),
        PUBLIC_JSON_PATH: public,
        LOG_PAGE_PATH: render_log_page(public),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if outputs are stale")
    args = parser.parse_args()

    stale = []
    for path, text in outputs().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    for path in stale:
        print(f"{'stale' if args.check else 'wrote'}: {path.relative_to(HERE)}")
    if not stale:
        print("catalogue outputs up to date")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())

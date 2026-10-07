# Research content

> **Retired 2026-10-08** with the rest of the site. The strategy catalogue that
> lived in `research/catalogue/` was deleted; see git history before that date.

Everything used to publish strategy research on the website and X. The backtests
themselves live in the separate `trading_hub` repo; nothing here runs a backtest.
Only `static/` is deployed, so files in `research/` are never public on their own.

```
research/
└── studies/<slug>/                # one folder per published study
    ├── data/                      # numbers exported from trading_hub
    ├── assets/                    # X images (poster, diagram, chart, lesson)
    ├── make_poster.py             # 1200x1500 poster
    ├── make_cards.py              # og.png for the page + thread/follow-up images
    ├── x-thread.md                # the thread text
    └── x-followups.md             # poll + single posts after the thread
```

The published page for a study lives in `static/research/<slug>/` (with its `og.png`).
When you publish one, add its card to `static/research/index.html` (the
Research page linked from the site's main nav), newest first.

Research pages use the site's own theme so they read as part of the app: link
`static/styles.css` (tokens, masthead, nav, tables) and `static/research/research.css`
(article layout), and put `<nav class="nav" data-site-nav data-root="../../">` first in
`.app` (above the masthead) with `js/site-nav.js` to render the app's nav. Colour with the site tokens
(`--brass`, `--red`, `--green`, `--text-dim`, `--panel`…); copy the one-minute ORB page
as the template. `make_cards.py` uses the same palette for `og.png`.

The site has no signup or request form: X is where readers follow and reply.
The whole publishing pipeline is in `BUSINESS_PLAN.md`.

## Commands (from the repo root)

```bash
pip install -r research/requirements.txt
py -3.14 research/studies/one-minute-orb/make_poster.py
py -3.14 research/studies/one-minute-orb/make_cards.py
py -3.14 research/studies/one-minute-orb/export_direction_curves.py research/studies/one-minute-orb/data/direction_curves.json  # needs trading_hub ticks
```

The image scripts need Edge or Chrome (set `BROWSER_EXE` to use another).

## Rules for public content

- Social-media posters and vendors are anonymised with enough context to recognise
  the setup ("a prominent Reddit poster"). Published papers keep their citations.

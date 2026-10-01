# Research content

Everything used to publish strategy research on the website and X. The backtests
themselves live in the separate `trading_hub` repo; nothing here runs a backtest.
Only `static/` is deployed, so files in `research/` are never public on their own.

```
research/
├── catalogue/                     # every tested study, one record each
│   ├── studies/*.yaml             # the source (edit these)
│   ├── catalogue.py               # schema + renderers
│   ├── build_catalogue.py         # -> STRATEGY_CATALOGUE.md, public/studies.json, backtest-log.html
│   ├── backtest_log_template.html # the filterable Backtest Log page
│   └── test_catalogue.py
└── studies/<slug>/                # one folder per published study
    ├── data/                      # numbers exported from trading_hub
    ├── assets/                    # X images (poster, diagram, chart, lesson)
    ├── make_poster.py             # 1200x1500 poster
    ├── make_cards.py              # og.png for the page + thread images
    └── x-thread.md                # the thread text
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

Every study page ends with `<div class="cta" data-research-cta hidden></div>` and loads
`static/research/research-cta.js`, which renders the email signup and "Request a test"
block. Set `BUTTONDOWN_USER` and `REQUEST_FORM_URL` there once; each half stays hidden
while its setting is empty. The whole publishing pipeline is in `BUSINESS_PLAN.md`.

## Commands (from the repo root)

```bash
pip install -r research/requirements.txt
py -3.14 research/catalogue/build_catalogue.py      # rebuild after editing a study
py -3.14 -m pytest research/catalogue -q            # checks + anonymisation guard
py -3.14 research/studies/one-minute-orb/make_poster.py
py -3.14 research/studies/one-minute-orb/make_cards.py
py -3.14 research/studies/one-minute-orb/export_direction_curves.py research/studies/one-minute-orb/data/direction_curves.json  # needs trading_hub ticks
```

The image scripts need Edge or Chrome (set `BROWSER_EXE` to use another).

## Rules for public content

- `STRATEGY_CATALOGUE.md` names every source. It is internal; publish the page or
  `public/studies.json` instead.
- Social-media posters and vendors are anonymised with enough context to recognise
  the setup ("a prominent Reddit poster"). Published papers keep their citations.
  `test_catalogue.py` fails if a name, handle or account detail reaches the public feed.
- Coverage: with a `trading_hub` checkout beside this repo (or `TRADING_HUB_ROOT` set),
  the tests also fail if any strategy, mechanism, paper or pre-registration tested
  there has no record here. Without it, those checks are skipped.

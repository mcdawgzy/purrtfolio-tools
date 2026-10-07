# Research business plan

> **Retired 2026-10-08** with the rest of the site. The strategy catalogue that
> lived in `research/catalogue/` was deleted; see git history before that date.

Internal note (not deployed; only `static/` is public). Decided 2026-09-29; simplified
2026-10-07 to an X-first model.

## Positioning

We don't sell strategies, signals or bots. We test the strategies other people are
selling, honestly, and post the results. The one-minute ORB study (rejected:
+0.008R/trade after costs, t = 0.10) is the template and proof of method: real tick
data, pre-registered decision rule, real spreads, opposite-direction and
random-direction controls. "Rejected" results are content, not failures.

## Model (2026-10-07)

- **Revenue: our posts on X.** X is the main income stream, so every study is
  packaged for X first: thread, poster, single follow-up posts, replies.
- **Website: free and open.** Every study is published in full on the Research page,
  next to the free tools (e.g. the cost/breakeven calculator on the ORB page). The
  site is where X posts link for the full breakdown; it asks for nothing.
- **Strategy ideas** come from our own strategies and from replies on X. There is no
  request form; good ideas from replies go into triage.

Dropped on 2026-10-07: the email list (Buttondown), the "Request a test" form (Tally),
the members subscription, and paid public/private testing.

## Process flow

```text
Sources: own strategies | ideas from X replies
   │
   ▼
1 Triage      weekly: pick the next study; reject untestable rules
2 Pre-register rules + decision rule written down
3 Test        in trading_hub: tick data, real costs, opposite/random-direction controls
4 Verdict     Pass / Rejected / Inconclusive by the pre-registered rule
5 Record      catalogue YAML here (research/catalogue/studies/) → build_catalogue.py;
              test_catalogue.py fails if trading_hub has a study with no record
6 Package     study page + og/cards + X thread + follow-up posts
   │
   ▼
Distribution: X thread → study page → replies on X → back to 1
```

**Fortnightly rhythm** (one public study every two weeks):

| Day | Week A | Week B |
|---|---|---|
| Mon | Triage, write the pre-registration | Package: page, cards, thread |
| Tue–Wed | Run the test | Publish: page; thread near the US open |
| Thu–Fri | Reuse the last study as 1–2 single X posts | Reply to comments; note ideas worth testing |

**Tools:** site = GitHub Pages; study record = the catalogue; visits = GoatCounter
(purrtfolio.goatcounter.com; tag links shared on X with `?ref=x`).

**Weekly numbers:** X impressions, followers, engagement on threads, X payouts, page
visits from X.

## Rules

- Never promise returns or present a strategy as profitable to trade; we report
  test results on the rules as given, not advice.
- Keep the existing anonymisation rules for sources (see `README.md`).
- Check data-provider licences before publishing any raw tick data or per-trade CSVs.

## Open items

- Close or archive the Buttondown account and the Tally form (no longer linked from
  the site).
- Licence check before offering per-trade CSV downloads on study pages.
- ~~Build the first free tool~~ (cost/breakeven calculator on the ORB page).

# Research business plan

Internal note (not deployed; only `static/` is public). Decided 2026-09-29.

## Positioning

We don't sell strategies, signals or bots. We sell honest tests of the strategies
other people are selling. The one-minute ORB study (rejected: +0.008R/trade after
costs, t = 0.10) is the template and proof of method: real tick data, pre-registered
decision rule, real spreads, opposite-direction and random-direction controls.
"Rejected" results are content, not failures.

## Model

1. **Free tier (top of funnel)**
   - A few free tools on the site, e.g. a cost/breakeven calculator (stop size,
     spread, R:R → required win rate, whether an edge survives costs) and a
     prop-firm challenge simulator.
   - Public posts: each study's verdict, poster and X thread, plus the Research page.
2. **Monthly subscription (members)**
   - Members submit strategies to test and vote on submissions (crowdsourced queue).
   - We test the most popular ones each cycle.
   - Full studies and results go to members first: per-trade data, every variant,
     code/notebook. Public gets the verdict summary (possibly after a delay).

## Income without a subscription (decided 2026-10-01)

The subscription above is optional. These come first:

- **Paid testing.** Public test (lower price, published with the source anonymised)
  or private test (full price, report to the client only). The client approves the
  pre-registration spec before the run: they pay for the test, not the result.
- **Our own strategies.** They go through the same pipeline. Rejected ones are free
  studies; passed ones are published in full, with the code + full report sold as a
  one-off download.
- **Email list** (free) is the asset everything else depends on.

## Process flow

Every study, whatever its source, runs through one pipeline:

```text
Sources: own strategies | free public requests (reader votes) | paid requests (public/private)
   │
   ▼
1 Intake      one "Request a test" form → one queue
2 Triage      weekly: paid first, then own strategies + top-voted requests; reject untestable rules
3 Pre-register rules + decision rule written down; paid clients sign off the spec
4 Test        in trading_hub: tick data, real costs, opposite/random-direction controls
5 Verdict     Pass / Rejected / Inconclusive by the pre-registered rule
6 Record      catalogue YAML here (research/catalogue/studies/) → build_catalogue.py;
              test_catalogue.py fails if trading_hub has a study with no record
7 Package     public: study page + og/cards + X thread + email (+ paid download if own & passed)
              private: report to the client only
   │
   ▼
Distribution: X thread → study page → email signup / "Request a test" → back to 1
```

**Fortnightly rhythm** (one public study every two weeks):

| Day | Week A | Week B |
|---|---|---|
| Mon | Triage, write the pre-registration | Package: page, cards, thread, email |
| Tue–Wed | Run the test | Publish: page + email; thread near the US open |
| Thu–Fri | Reuse the last study as 1–2 single X posts | Replies → steer good ideas to the request form |

Paid private tests take the Tue–Wed test slots.

**Tools, one of each:** site = GitHub Pages; email = Buttondown; request form = Tally
(feeds the queue); payments = Stripe Payment Links or Lemon Squeezy; study record =
the catalogue; visits = GoatCounter (purrtfolio.goatcounter.com; tag shared links
`?ref=x` / `?ref=email`; signup and request clicks are counted as events).

**Weekly numbers:** X impressions, page visits, email subscribers, test requests,
paid tests.

### Rollout

- **Phase 0 (before the ORB thread):** ORB page gets the cost/breakeven calculator,
  equity curve, "what we'd test next" and the signup + request block (done on
  `feat/research-growth`; the block stays hidden until `BUTTONDOWN_USER` and
  `REQUEST_FORM_URL` are set in `static/research/research-cta.js`; both set 2026-10-02).
- **Phase 1 (weeks 1–4):** post the ORB thread (page link + signup in the first
  reply, not in the posts), reuse it as 3 single posts, publish study #2 from our
  own strategies, ideally one that passed.
- **Phase 2 (first unprompted requests):** add prices to the form, take the first
  paid tests.

## Rules

- Never promise returns or present a strategy as profitable to trade; we report
  test results on the rules as given, not advice. Say so in the terms.
- Keep the existing anonymisation rules for sources (see `README.md`).
- Check data-provider licences before sharing any raw tick data with members.

## Open items

- ~~Create the Buttondown account and Tally request form~~ (done 2026-10-02).
- Prices for public and private tests; payments platform.
- Licence check before offering per-trade CSV downloads on study pages.
- Members area / subscription: only if paid testing and the list show demand.
- ~~Build the first free tool~~ (cost/breakeven calculator on the ORB page).

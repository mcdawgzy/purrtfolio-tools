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

## Rules

- Never promise returns or present a strategy as profitable to trade; we report
  test results on the rules as given, not advice. Say so in the terms.
- Keep the existing anonymisation rules for sources (see `README.md`).
- Check data-provider licences before sharing any raw tick data with members.

## Open items

- Pick the platform for payments and the members area (Substack / Beehiiv / Ghost,
  or gated pages on the site).
- Pricing and the number of strategies tested per month.
- Submission + voting mechanism.
- Build the first free tool.

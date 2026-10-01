# Email — the one-minute ORB scalp at 3:1

Not deployed: research/ is outside static/. Paste the body into a new Buttondown email
(it takes Markdown). Send it once the first subscribers are in, or keep it as the template.

**Subject:** The 1-minute ORB scalp: claimed 34–36%, measured 26.1%

**Preview text:** What a coin flip wins at 3:1, and why that matters for every fixed R:R setup.

---

A Reddit scalping post says you can trade the first 1-minute range at the open, fixed 3:1, and win 34–36% of the time. At 3:1 that would be a great edge: +0.36R to +0.44R per trade.

I tested it on real S&P 500 tick data. 544 trades, every one paying the real spread.

**It won 26.1%.**

That number matters because of a simple fact: if price moves at random, a 3:1 bracket hits its target 1 / (1 + 3) = 25% of the time. So 26.1% is what a coin flip gives you. The same held at every R:R I tried, from 1:1 to 5:1.

**The part that's real.** Trading with the break did beat trading against it, by 0.31R per trade. Opening momentum exists. But the gross edge is about 0.12R and the spread costs about 0.09R, so after costs it made +0.008R per trade. Basically zero.

**On a prop account it's worse.** The worst run was 15 losses in a row and a 32.7R drawdown. At 0.5% risk per trade, that's a 16.4% drawdown, well past the usual 10% limit.

**The lesson:** before you believe any win rate on a fixed R:R trade, compare it with 1 / (1 + R:R).

The full study has the equity curves, every variant I tested, and a calculator to check your own setup's win rate against costs:

**[Read the full study →](https://purrtfolio.onrender.com/research/one-minute-orb/)**

**Got a strategy you want tested?** Send me the rules. A public test gets published with the source anonymised; a private one goes to you alone. Same method either way.

[Request a test →](https://tally.so/r/q40zxY)

Next up: whether a filter can make the break pay. Reply and tell me which one you'd test: gap size, range size against ATR, or the VIX.

— Purrtfolio

*Research, not financial advice. Backtests describe the past.*

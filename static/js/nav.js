// Top navigation (Research link + grouped dropdowns) and per-page descriptions.

import { el } from './core/dom.js';
import { state } from './core/state.js';
import { setHash } from './router.js';
import { NAV_CTA, NAV_GROUPS, NAV_ROUTES, closeNavDropdowns } from './nav-shared.js';

// ---------------- Page descriptions ----------------
// Context paragraphs shown at the top of each view explaining what the
// data shows, where it comes from, and known limitations / issues.
const PAGE_DESCRIPTIONS = {
  snapshot: {
    intro: 'Daily macro market snapshot covering 31 tickers across 7 sections — US Equities, Global Equities, US Rates, FX, Commodities, Market Internals, and Crypto. The PNG captures price levels, 24-hour changes, and a driver narrative for each ticker; the top-3 mover narratives are shown in the card below. Generated each morning at 7 AM UTC+10 via a macro pipeline that fetches free-tier data from yfinance (equities, FX, commodities, crypto, bond proxies) and CBOE for VIX.',
    issues: 'yfinance free-tier data can lag by up to 15 minutes and may carry gaps in off-hours crypto/FX sessions. The snapshot is a static PNG rendered at generation time — it does not auto-refresh. Reload after the daily pipeline runs to see the latest data. Overnight gaps (e.g. holidays) show stepped changes the next day.',
  },
  funds: {
    intro: 'Directory of ~27 curated institutional investment funds whose SEC Form 13F filings are tracked in this dashboard. Each row shows the fund name, strategy classification, CIK, latest-reported AUM, and total holdings count. Click any fund to drill into its position list or quarter-over-quarter changes. Filings are ingested via the edgartools library and stored in the unified purrtfolio.db SQLite database.',
    issues: '13F data is quarterly with a 35–45 day SEC filing lag — the most recent quarter shown may be 6+ weeks stale. AUM reflects only the fund\'s reported U.S. equity holdings (not global AUM). Some funds file amendments (13F-ORF or 13F/A) that may not yet be reflected here. Cash, options, and non-U.S. positions are excluded by the SEC filing structure itself.',
  },
  fund: {
    intro: 'Quarterly 13F holdings for a single institution. The Holdings tab shows every position as of the report period — ticker, shares, CUSIP, and market value — sorted by value by default. The Changes tab shows quarter-over-quarter activity classified as New, Increased, Decreased, Closed, or Unchanged, with the dollar change per position. Data comes from SEC EDGAR Form 13F filings; the holding_changes_13f table pre-computes deltas between consecutive quarters.',
    issues: 'Holdings are point-in-time as of the quarter-end filing date — they do not reflect intra-quarter trading. Position values are the fund\'s reported market value, not current market prices. Amendment filings (13F-ORF, 13F/A) may introduce corrections that haven\'t propagated to this view yet. Funds with no infotable (e.g. certain broad index funds) are excluded from holdings counts.',
  },
  ticker: {
    intro: 'Cross-fund view of who currently holds a specific ticker. The table lists every tracked fund holding the ticker — its position value, share count, and quarter-over-quarter status. Below the holders table, a quarterly history shows total value across all funds per report period. If the ticker is in the short-interest watchlist, a short-interest summary appears above the holders. Position data comes from SEC EDGAR Form 13F holdings; short interest (when shown) comes from FINRA bi-weekly data.',
    issues: '13F data is quarterly and subject to a 35–45 day filing lag. Short interest is aggregate per ticker — not per-fund — settled twice monthly and lagging the current date by approximately two weeks. Free-float and percentage-of-free-float figures are estimates based on reported share counts and may not account for restricted shares or dual-class structures. Ticker lookups are case-insensitive but must match exactly (e.g. BRK.B vs BRK.A).',
  },
  consensus: {
    intro: 'Cross-fund momentum: tickers where multiple funds (>1) are net buying or net selling in the same quarter. Buys are sorted by total dollar increase; sells by total dollar decrease. The min-funds filter controls the inclusion threshold (default: 2 funds). Data comes from the holding_changes_13f table, which pre-computes per-fund position deltas from consecutive SEC EDGAR 13F filings.',
    issues: 'Only captures changes between consecutive reported quarters — a fund that held a position constant while others moved will not appear. NEW positions (from $0) and CLOSED positions (to $0) are excluded from the net change to prevent false signals, so net change reflects only incremental moves on continuing positions. Relies on both the prior and current quarter filings being present; tickers missing from either quarter are omitted.',
  },
  sectors: {
    intro: 'Sector-level rotation between the two most recent 13F reporting periods. Each row is a GICS sector with its previous and current aggregate portfolio value, the dollar and percentage change, the change in holder count, and the change in position count (number of funds holding the sector). Data comes from SEC EDGAR Form 13F holdings joined to the tickers.sector column for GICS classification.',
    issues: 'Sector classifications are incomplete — only about 6% of tracked AUM currently has sector data populated (primarily tickers enriched by the short-interest scanner). A weekly sector-enrichment cron job populates tickers.sector for new tickers, so coverage will improve over time. The view uses a FULL OUTER JOIN between two periods, so sectors appearing in only one quarter show as new or closed. ETFs-as-securities ("ETFs & Funds") are excluded from the aggregation.',
  },
  shortinterest: {
    intro: 'FINRA short interest data for ~50 large-cap tickers across three tabs: the Latest Snapshot (all tickers sorted by short-dollar size), Signals (spikes ≥50% change, high DTC ≥10 days, covering ≤-30%, new shorts ≥5x), and Watchlist (same table sorted by current short value). Drill into any ticker for its full bi-weekly history with split and revision flags. Data comes from FINRA bi-weekly short interest reports, stored in the short_interest and ticker_short_meta tables.',
    issues: 'Data is aggregate per ticker — not per-fund — so it shows total short interest across all reporting entities. Settled twice monthly with a ~2-week lag (FINRA settlement date, not trade date). Coverage is limited to NASDAQ and NYSE listed securities — OTC/pink sheets are excluded. Percentage of free float is estimated from reported share counts and may miss restricted shares. "New shorts ≥5x" compares to the previous settlement, which can be noisy on low-base numbers.',
  },
  economic: {
    intro: 'Upcoming high-impact economic calendar events: FOMC meetings, US economic releases (CPI, PPI, NFP, GDP, jobs), and major central bank decisions (ECB, BOE, BOJ). The table shows event date, time, category, impact level, and forecast vs prior values. FOMC dates come from the Federal Reserve website; US releases from the Finnhub free API; ECB/BOE/BOJ are a curated schedule. Data is stored in the economic_events table and refreshed daily by the economic-calendar scanner cron.',
    issues: 'Non-FOMC events use a curated fallback list — ad-hoc announcements or last-minute schedule changes may not be captured until the next daily ingestion. Finnhub free API has limited historical and forecast coverage; when a forecast or prior value is unavailable it shows "—". Event times use local market time zones (ET for US events) and DST transitions can shift displayed times by an hour around boundary dates.',
  },
  insider: {
    intro: 'Recent SEC Form 4 insider trading activity for the curated watchlist. The Latest Trades tab shows the most recent transactions (buy/sale, quantity, price, value, ownership type). The Signal tab aggregates top buys by value, top sells, officer/CFO/CEO trades, and most-active tickers. Drill into any ticker for its full transaction history. Data comes from SEC EDGAR Form 4 filings (sec-edgar-feeder), stored in the insider_submissions, insider_owners, and insider_transactions tables.',
    issues: 'Form 4 is filed by the insider within 2 business days of the trade date, so there is an inherent 2–3 day lag. Transaction values are calculated as shares × reported price per share and may be incomplete or inaccurate for complex derivative transactions (e.g. option exercises with embedded pricing). Only covers U.S.-listed issuers; foreign private issuers filing Form 6-K or ADR programs are excluded. Signal sets filter to Direct ownership to avoid double-counting through trusts or family members.',
  },
  momentum: {
    intro: 'Price momentum scans across a curated watchlist of ~54 tickers. The Top Movers tab ranks by 20-day rate of change. Volume Spikes shows tickers trading above 2× their 10-day volume EMA. Consolidation highlights tickers in tight ranges (ATR < 3% of price). Earnings Gaps flags overnight gaps >1%. Drill into any ticker for its daily price history. Data comes from daily OHLCV from yfinance (cron-populated price_history table, with an on-demand yfinance fallback when the DB is empty).',
    issues: 'On-demand mode (when the DB hasn\'t been populated by cron) uses yfinance free tier, which can lag by up to 15 minutes and may fail on some tickers. The 20-day rate of change uses price return, not total return — dividends are not factored in. Micro-cap tickers with a 20-day SMA below $5 are filtered to reduce noise. Volume spike ratios are sensitive to low-base effects during holidays or IPO quiet periods.',
  },
  correlation: {
    intro: 'Rolling-window correlation between tracked tickers and market pivot assets (S&P 500, Nasdaq, Russell 2000, 2Y/5Y/10Y/30Y treasuries, VIX, USD, etc.). The Matrix tab shows all tickers × all pivots as a heatmap. The Pivot tab ranks tickers by their correlation to a single pivot asset. Windows: 1, 3, 6, or 12 months. Data comes from daily close prices from yfinance (cron-populated corr_matrices table, with on-demand computation when the DB is empty).',
    issues: 'Correlations are computed from raw price returns, not total returns (dividends ignored). The 1-month window has limited statistical significance (≈21 trading days). On-demand computation triggers a yfinance download that can take several seconds on a cold start. Pivot tickers and the ticker set must both have price history for every day in the window; missing days reduce the sample.',
  },
  factors: {
    intro: 'Portfolio-value-weighted factor exposure for the latest 13F quarter across three style dimensions: Size (market cap: Large/Mid/Small), Value/Growth (P/B: Value/Blend/Growth), and Momentum (20-day ROC: Momentum/Neutral/Contrarian). Each dimension shows the overall allocation as a bar chart, a per-bucket table, and a per-strategy tilt. The Crowded Trades tab lists the most-held positions by fund count and value. Data comes from SEC EDGAR 13F holdings joined to the ticker_factors enrichment table.',
    issues: 'Coverage is honest — only tickers with factor classifications contribute to the exposure buckets; the remainder of AUM is reported as Unclassified. Market cap and P/B figures are enriched externally and may use a different update cadence than the 13F filing date. The 20-day momentum signal is price-return-based and excludes dividends. Per-strategy breakout requires at least one fund holding the ticker in that strategy.',
  },
  putcallratio: {
    intro: 'Daily put/call ratios from the Chicago Board Options Exchange (CBOE) across multiple series — Total Market, Index, Equity, ETP, VIX, SPX+SPXW, OEX, and MRUT. The Latest tab shows all series with their 5-day, 20-day, 50-day moving averages, z-scores, and current signal classification. The Signals tab highlights extreme readings. The History tab charts a single series over time. Data comes from CBOE daily data stored in the put_call_ratio and put_call_latest tables, refreshed daily by cron.',
    issues: 'Data is only available on trading days (no weekend or holiday bars). Signal classifications (Sell-Side/Buy-Side/Neutral) are based on z-scores relative to a 20-day moving average, which can whipsaw during volatile regimes. The ratio reflects all put and call volume including market-maker activity, index inclusion effects, and opening transactions — it is a sentiment indicator, not a direct price-direction prediction. VIX options have a different volatility regime than equity options, so cross-series comparison should be cautious.',
  },
  ivrank: {
    intro: 'Daily ATM implied volatility for ~30 large-cap tickers with liquid options. IV Rank shows where current IV sits within its 52-week range (0 = lowest, 100 = highest). IV Percentile is the percentage of the past 252 trading days with IV below today — above 70% means options are historically expensive (sell premium); below 30% means cheap (buy premium). Data is fetched via yfinance options chains (nearest-expiry ATM call/put IV averaged), processed in Python via cron, and stored in the unified purrtfolio.db. The history chart for each ticker plots daily IV alongside IV Rank with 5-day and 20-day moving averages.',
    issues: 'yfinance options chains sometimes return NaN for implied volatility — these are filtered out. The first ~10 days after a fresh ticker is added will show insufficient data for IV Rank until a lookback builds up. IV values are ATM-only (nearest expiry), not 30-day rolling IV — they can jump around more than a standardised index like VIX. Data ingestion runs daily at 6 AM UTC+10; the current day may not appear until ~6:05 AM after the cron completes.',
  },
  news: {
    intro: 'Daily financial news sentiment for a curated watchlist of ~144 tickers. Headlines are fetched from 6 free RSS feeds (Yahoo Finance, Seeking Alpha, Benzinga, MarketWatch, Reddit r/investing), matched to tickers by symbol format ($TICKER, (TICKER)) and company name, then scored using VADER sentiment analysis enhanced with a financial lexicon (100+ domain-specific terms). The Headlines tab shows the latest stories with sentiment scores and matched tickers. The Signals tab highlights tickers with notable bullish or bearish sentiment (avg score ≥0.15 or ≤−0.15, min 2 headlines). Drill into any ticker for its daily sentiment history and associated headlines. Data is stored in the news_headlines and ticker_news_sentiment tables, refreshed daily by cron.',
    issues: 'Headline-to-ticker matching uses company name matching which can produce occasional false positives (e.g. a surname like "Wells" matching Wells Fargo). RSS feeds are general market news — not every headline will mention a tracked ticker, so some tickers may have no recent sentiment data. VADER + financial lexicon is a rule-based approximation, not a transformer model; scores reflect headline tone only and do not capture sarcasm, irony, or complex multi-clause reasoning. Reddit r/investing is community discussion, not professional news — sentiment there may differ from institutional tone.',
  },
  positioning: {
    intro: 'Interactive position sizing calculator using the Kelly Criterion. Enter your account size, win rate, and reward-to-risk ratio to compute the optimal fraction of capital to risk per trade — with Full, Half, and Quarter Kelly variants. Results update live as you type. This is a client-side tool: no inputs are sent to any server or stored. The Kelly Criterion (f* = p − (1−p)/b) determines the theoretically optimal bet size for maximising long-term geometric growth; Half and Quarter Kelly reduce volatility at the cost of slower growth.',
    issues: '',
  },
  drawdown: {
    intro: 'Monte Carlo drawdown simulator. Run hundreds of simulated trade sequences to see the distribution of outcomes — average and median final values, max drawdown, probability of large drawdowns, probability of ruin, and CAGR. The equity curve visualises multiple simulation paths plus the median trajectory. All computation is client-side; no data leaves your browser.',
    issues: 'Monte Carlo uses pseudorandom outcomes — results are statistical estimates, not guarantees. Real trading involves serial correlation, volatility clustering, and regime changes that a simple IID model cannot capture. Assumed 252 trading days per year for CAGR. Simulations assume fixed position size (constant percentage of current equity); they do not model slippage, commissions, or liquidity constraints.',
  },
  payoff: {
    intro: 'Interactive multi-leg options payoff calculator. Build custom option strategies by adding legs — each leg is a call or put that you bought or sold, with a strike price and premium paid or received. The payoff diagram shows the combined profit/loss curve at expiration across a range of underlying prices. Key outputs include max profit, max loss, breakeven points, and terminal P&L. All calculations are client-side; no data leaves your browser.',
    issues: '',
  },
  greeks: {
    intro: 'Interactive Black-Scholes Greeks calculator for a single European option. Enter spot price, strike, implied volatility, time to expiry, interest rate, and dividend yield to compute Delta, Gamma, Theta, and Vega in real time. The Delta-vs-Spot chart plots how Delta changes across underlying prices — the steepness of that curve at any point is Gamma, the rate of Delta change. This is a client-side tool: no inputs are sent to any server or stored.',
    issues: 'Uses the Black-Scholes-Merton model with continuous dividend yield. These are theoretical values — actual options may trade at different prices due to discrete dividends, American exercise features, stochastic volatility, and transaction costs. Theta is shown as daily decay (1/365 of annualized). Vega is shown per 1% change in implied volatility. For multi-leg strategies, use the Options Payoff Visualizer alongside this tool.',
  },
  optionsexplainer: {
    intro: 'Educational guide to options trading: what calls and puts are, how premium, strike, and expiration work, moneyness (ITM/ATM/OTM), the Greeks at a glance, time decay (theta), implied volatility (vega), and common option strategies (spreads, straddles, condors, covered calls, protective puts). This is a conceptual primer — use the Greeks Explainer and Options Payoff Visualizer for interactive calculations, and the IV Rank Tracker for live implied volatility data.',
    issues: 'This is a static educational reference, not trading advice. Options involve substantial risk, including the potential to lose significantly more than the initial investment for leveraged positions. Past performance of any strategy is not indicative of future results.',
  },
  unusualactivity: {
    intro: 'Daily unusual activity scan across ~24 large-cap tickers. Detects unusual options activity (high volume-to-open-interest ratios, large notional trades) and volume spikes (dark-pool / block-trade proxy — current volume vs 20-day average). Each flagged trade or spike is scored by severity (0-100) based on VOI ratio, notional dollar size, days-to-expiry proximity, and volume surge. Use the Latest tab to see flagged activity sorted by severity, or drill into any ticker for its history chart. Data is fetched from yfinance options chains and daily price/volume history, processed in Python via cron, and stored in the unified purrtfolio.db.',
    issues: 'Options volume data from yfinance free tier can lag by up to 24 hours. The volume-spike detector is a proxy for dark-pool activity, not a direct feed of executed block trades — a volume spike can also be caused by news events or algorithmic trading. VOI ratio (volume/open-interest) is most meaningful for options with established open interest; freshly listed strikes can show inflated ratios. Notional values use mid-price (bid+ask)/2, which may differ from execution prices on wide spreads. Data ingestion runs daily at 7 AM UTC+10; the current day may not appear until ~7:10 AM after the cron completes.',
  },
  screener: {
    intro: 'Customizable stock screener over the full tickers universe (~11,800 securities from SEC EDGAR 13F holdings). Filter by GICS sector, price range, daily volume, market cap, or ETF vs stock. Sort by market cap, price, volume, 5-day price change, or ticker. Market cap is computed as latest close × shares_outstanding (from price_history joined to tickers). Results update live as you adjust filters — no page reload needed. Data is read from the unified purrtfolio.db SQLite database, refreshed daily by cron.',
    issues: 'Market cap uses diluted shares_outstanding from 13F filings, not real-time float — it may not reflect post-IPO activity or recent buybacks. The 5-day price change compares today&rsquo;s close to the close 5 trading days ago; gaps from halted/suspended tickers can produce misleading returns. Index tickers (e.g. ^GSPC, ^NDX) are excluded since they lack fundamental data in the tickers dimension. ETF filtering relies on the is_etf flag from EDGAR classification, which may miss newer or non-US-listed ETFs.',
  },
  quotes: {
    intro: 'A curated collection of ~50 famous trader and investor quotes, organized by category (Investing, Trading, Risk Management, Psychology, Markets). New quotes can be added by extending the seed file and re-running the daily cron. Each quote is attributed to its author with source documentation. Use the category filter to browse by theme, or click "Random" for a daily dose of wisdom.',
    issues: 'Quotes are curated from public interviews, books, and annual reports. Some attributions are debated by scholars — treat as folklore rather than verified transcripts. Categories are assigned by keyword clustering, not by the speakers themselves. The collection is seeded once and grown manually; it is not scraped from social media in real-time.',
  },
  earningsrevisions: {
    intro: 'Tracks earnings revision momentum across the watchlist universe (~24 large-cap tickers). For each ticker, the scanner fetches yfinance\u2019s earnings_history (actual vs estimate for the last 4 reported quarters), computes a mean revision percentage, fraction of positive surprises, and a z-scored momentum rank. Ticklers are classified as improving / deteriorating / stable based on whether recent-quarter revisions are accelerating or decelerating. Data is fetched daily at 5:30 AM UTC+10 via cron and stored in the unified purrtfolio.db. The z-score compares each ticker\u2019s revision magnitude to the cross-sectional mean and standard deviation \u2014 higher scores indicate stronger positive earnings surprises relative to peers.',
    issues: 'yfinance earnings_history availability is inconsistent \u2014 ETFs (SPY, QQQ, IWM) and some foreign tickers return 404 and are silently skipped. The 4-quarter window means tickers with fewer reported quarters are excluded entirely, which can bias the universe toward larger, more consistent reporters. Revision pct uses (actual - estimate) / |estimate|, so small or negative estimates can produce extreme values; the z-score dampens this but outliers like BA can still dominate the ranking. The trend classification threshold (\u00b12% recent-vs-older delta) is a heuristic \u2014 a \\u201cstable\u201d reading may still reflect meaningful acceleration below the threshold. Data lags real-time by 1-2 days during earnings season.',
  },
  crowdedtrades: {
    intro: 'Multi-signal crowdedness scanner for a curated watchlist of ~157 tickers. Aggregates six independent signals into a 0\u2013100 score: (1) short interest (SIR + DTC + change), (2) options flow (call/put volume-to-open-interest), (3) IV rank (peer-relative IV percentile), (4) price momentum (20-day ROC rank), (5) put/call ratio extremes, and (6) cross-asset correlation to market pivots. Signals are classified as NEUTRAL, MEDIUM, or HIGH based on configurable thresholds. Updated daily after the 6:30 AM UTC+10 cron ingest. Data comes from FINRA short interest, CBOE put/call ratios, yfinance options chains, and price data \u2014 all stored in the unified purrtfolio.db.',
    issues: 'Short interest is aggregate per ticker (not per-fund) and settles twice monthly with a ~2-week lag. Options data from yfinance free tier can lag by up to 24 hours. The peer-relative IV percentile fallback computes rank within the same sector+asset-type group (min 5 peers); tickers with fewer peers fall back to universe-wide percentile. The put/call ratio signal classifies extreme readings as bullish-complacency (low PCR) or bearish-complacency (high PCR). Not all tickers will have all six signals populated on every scan \u2014 component scores default to 0 when upstream data is unavailable. Signals are point-in-time snapshots at daily close; intra-day moves are not reflected.',
  },
};

export function renderPageDescription(view) {
  const desc = PAGE_DESCRIPTIONS[view];
  if (!desc) return null;
  const wrap = el('div', { class: 'page-description' });
  wrap.appendChild(el('p', { class: 'page-description-para' }, desc.intro));
  wrap.appendChild(el('p', { class: 'page-description-para issues' }, desc.issues));
  return wrap;
}

function navHref(item) {
  return NAV_ROUTES[item.view] || '#/' + item.view;
}

export function renderNav() {
  const nav = el('nav', { class: 'nav', 'aria-label': 'Site' });

  // Brand / logo — the home page is the Research hub
  nav.appendChild(el('a', { class: 'nav-brand', href: './research/' }, 'Purrtfolio'));

  // Published research write-ups (static pages under ./research/, not SPA routes)
  nav.appendChild(el('a', { class: 'nav-dropdown-label nav-flat', href: './research/' }, 'Research'));

  // Dropdown groups
  for (const group of NAV_GROUPS) {
    const dropdown = el('div', { class: 'nav-dropdown' });

    // Trigger label
    const trigger = el('div', {
      class: 'nav-dropdown-label',
      tabindex: 0,
      onclick: (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('open');
      },
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          dropdown.classList.toggle('open');
        }
      },
    }, group.label);

    // Menu
    const menu = el('div', { class: 'nav-dropdown-menu' });
    for (const item of group.items) {
      const isActive = state.view === item.view;
      menu.appendChild(el('a', {
        class: 'nav-link' + (isActive ? ' active' : ''),
        href: navHref(item),
        onclick: (e) => {
          e.preventDefault();
          setHash(navHref(item));
          closeNavDropdowns();
        },
      }, item.label));
    }

    dropdown.appendChild(trigger);
    dropdown.appendChild(menu);
    nav.appendChild(dropdown);
  }

  nav.appendChild(el('div', { class: 'nav-spacer' }));
  nav.appendChild(el('a', { class: 'btn btn-primary nav-cta', href: NAV_CTA.href }, NAV_CTA.label));
  return nav;
}

/* Hash routing + top-level render dispatch.
   Routing via hash: #/  (market snapshot)
                    #/funds  (funds list)
                    #/fund/{cik}  (fund detail)
                    #/fund/{cik}?tab=changes  (changes subview)
                    #/ticker/{ticker}  (cross-fund view)
                    #/consensus  (cross-fund momentum)
                    #/short-interest  (short interest overview)
                    #/short-interest/signals  (SI signals)
                    #/short-interest/{ticker}  (SI ticker history)
                    ... see parseHash() for the full list.
   Views import render()/setHash() from here and this module imports the views;
   that cycle is safe because every cross-module use happens at call time, never
   during module evaluation. */

import { el } from './core/dom.js';
import { state } from './core/state.js';
import { renderPageDescription, renderNav } from './nav.js';
import { renderDrawdownSimulator } from './views/calculators/drawdown.js';
import { renderGreeksExplainer } from './views/calculators/greeks.js';
import { renderOptionsExplainer } from './views/calculators/optionsexplainer.js';
import { renderPayoffVisualizer } from './views/calculators/payoff.js';
import { renderPositionSizing } from './views/calculators/positionsizing.js';
import { loadConsensus, renderConsensusView } from './views/consensus.js';
import { loadCorrelation, renderCorrelation } from './views/correlation.js';
import { loadCrowdedTrades, renderCrowdedTradesPage } from './views/crowdedtrades.js';
import { loadEarningsRevisions, renderEarningsRevisions } from './views/earningsrevisions.js';
import { loadEconomicCalendar, renderEconomicCalendar } from './views/economic.js';
import { loadFactors, renderFactors } from './views/factors.js';
import { loadFund, renderFund } from './views/fund.js';
import { loadFunds, renderFunds } from './views/funds.js';
import { loadInsider, renderInsider } from './views/insider.js';
import { loadIVRank, renderIVRank } from './views/ivrank.js';
import { loadMomentum, renderMomentum } from './views/momentum.js';
import { loadNews, renderNews } from './views/news.js';
import { loadPutCallRatio, renderPutCallRatio } from './views/putcallratio.js';
import { loadQuotes, renderQuotes } from './views/quotes.js';
import { loadScreener, renderScreener } from './views/screener.js';
import { loadSectors, renderSectors } from './views/sectors.js';
import { loadShortInterest, renderShortInterest } from './views/shortinterest.js';
import { loadSnapshot, renderSnapshot } from './views/snapshot.js';
import { loadTicker, renderTicker } from './views/ticker.js';
import { loadUnusualActivity, renderUnusualActivity } from './views/unusualactivity.js';

// ---------------- routing ----------------
function parseHash() {
  const h = location.hash.replace(/^#\/?/, '') || '';
  if (!h) return { view: 'snapshot' };
  if (h === 'funds') return { view: 'funds' };
  if (h === 'snapshot') return { view: 'snapshot' };
  if (h === 'consensus') return { view: 'consensus' };
  if (h === 'sectors') return { view: 'sectors' };
  if (h === 'economic-calendar' || h === 'economic-calendar/') return { view: 'economic' };
  if (h.startsWith('insider')) {
    if (h === 'insider' || h === 'insider/') return { view: 'insider' };
    const rest = h.slice('insider/'.length);
    if (rest === 'signals') return { view: 'insider', insiderTab: 'signals' };
    return { view: 'insider', insiderTab: 'ticker', insiderTicker: rest.toUpperCase() };
  }
  if (h === 'short-interest' || h === 'short-interest/') return { view: 'shortinterest' };
  if (h.startsWith('short-interest/')) {
    const rest = h.slice('short-interest/'.length);
    if (rest === 'signals') return { view: 'shortinterest', siTab: 'signals' };
    return { view: 'shortinterest', siTab: 'ticker', siTicker: rest.toUpperCase() };
  }
  if (h === 'momentum' || h === 'momentum/') return { view: 'momentum' };
  if (h.startsWith('momentum/')) {
    const rest = h.slice('momentum/'.length);
    if (rest === 'volume-spikes') return { view: 'momentum', momTab: 'volume-spikes' };
    if (rest === 'consolidation') return { view: 'momentum', momTab: 'consolidation' };
    if (rest === 'gaps') return { view: 'momentum', momTab: 'gaps' };
    return { view: 'momentum', momTab: 'ticker', momTicker: rest.toUpperCase() };
  }
  if (h === 'correlation' || h === 'correlation/') return { view: 'correlation' };
  if (h.startsWith('correlation/')) {
    const rest = h.slice('correlation/'.length);
    return { view: 'correlation', corrPivot: rest.toUpperCase() };
  }
  if (h === 'factors' || h === 'factors/') return { view: 'factors', factorTab: 'drift' };
  if (h.startsWith('factors/')) {
    const rest = h.slice('factors/'.length);
    if (rest === 'crowded') return { view: 'factors', factorTab: 'crowded' };
    return { view: 'factors', factorTab: 'ticker', factorTicker: rest.toUpperCase() };
  }
  if (h === 'put-call-ratio' || h === 'put-call-ratio/') return { view: 'putcallratio' };
  if (h.startsWith('put-call-ratio/')) {
    const rest = h.slice('put-call-ratio/'.length);
    if (rest === 'history') return { view: 'putcallratio', pcrTab: 'history' };
    if (rest === 'signals') return { view: 'putcallratio', pcrTab: 'signals' };
    // PCR is per-series, not per-ticker; unknown sub-routes fall back to Latest.
    return { view: 'putcallratio', pcrTab: 'latest' };
  }
  if (h === 'iv-rank' || h === 'iv-rank/') return { view: 'ivrank' };
  if (h.startsWith('iv-rank/')) {
    const rest = h.slice('iv-rank/'.length);
    return { view: 'ivrank', ivTab: 'history', ivTicker: rest.toUpperCase() };
  }
  if (h === 'news' || h === 'news/') return { view: 'news', newsTab: 'headlines' };
  if (h.startsWith('news/')) {
    const rest = h.slice('news/'.length);
    if (rest === 'headlines') return { view: 'news', newsTab: 'headlines' };
    if (rest === 'signals') return { view: 'news', newsTab: 'signals' };
    if (rest === 'ticker') return { view: 'news', newsTab: 'ticker' };
    return { view: 'news', newsTab: 'ticker', newsTicker: rest.toUpperCase() };
  }
  if (h === 'drawdown-simulator' || h === 'drawdown-simulator/') return { view: 'drawdown' };
  if (h === 'position-sizing' || h === 'position-sizing/') return { view: 'positioning' };
  if (h === 'payoff-visualizer' || h === 'payoff-visualizer/') return { view: 'payoff' };
  if (h === 'greeks-explainer' || h === 'greeks-explainer/') return { view: 'greeks' };
  if (h === 'options-explainer' || h === 'options-explainer/') return { view: 'optionsexplainer' };
  if (h === 'unusual-activity' || h === 'unusual-activity/') return { view: 'unusualactivity' };
  if (h === 'screener' || h === 'screener/') return { view: 'screener' };
  if (h === 'quotes' || h === 'quotes/') return { view: 'quotes' };
  if (h === 'earnings-revisions' || h === 'earnings-revisions/') return { view: 'earningsrevisions' };
  if (h === 'crowded-trades' || h === 'crowded-trades/') return { view: 'crowdedtrades' };
  if (h.startsWith('unusual-activity/')) {
    const rest = h.slice('unusual-activity/'.length);
    return { view: 'unusualactivity', uaTab: 'history', uaTicker: rest.toUpperCase() };
  }
  if (h.startsWith('fund/')) {
    const rest = h.slice(5);
    const [cik, qs] = rest.split('?');
    const params = new URLSearchParams(qs || '');
    return { view: 'fund', cik, tab: params.get('tab') || 'holdings' };
  }
  if (h.startsWith('ticker/')) return { view: 'ticker', ticker: h.slice(7).toUpperCase() };
  return { view: 'funds' };
}

export function setHash(h) {
  if (location.hash === h) {
    // force re-render
    handleRoute();
  } else {
    location.hash = h;
  }
}

// Incremented on every navigation; a loader that finishes after a newer
// navigation started must not render over the newer view.
let _routeToken = 0;

export async function handleRoute() {
  const token = ++_routeToken;
  const r = parseHash();
  state.view = r.view;
  // Drop the momentum cache when leaving the view so re-entry refetches fresh
  // intraday data (tab switches within momentum stay cached — see loadMomentum).
  if (r.view !== 'momentum') {
    state.momRankings = null; state.momVolumeSpikes = null;
    state.momConsolidation = null; state.momGaps = null;
    state.momTickerHistory = null;
    state.momActiveTab = 'rankings';
  }
  if (r.view !== 'factors') {
    state.factorExposure = null;
    state.factorTicker = null;
    state.factorActiveTab = 'drift';
  }
  if (r.view !== 'ivrank') {
    state.ivMeta = null;
    state.ivLatest = { rows: [] };
    state.ivHistory = null;
    state.ivActiveTab = 'latest';
    state.ivSelectedTicker = null;
  }
  if (r.view !== 'unusualactivity') {
    state.uaMeta = null;
    state.uaLatest = { rows: [] };
    state.uaHistory = null;
    state.uaActiveTab = 'latest';
    state.uaSelectedTicker = null;
  }
  if (r.view !== 'crowdedtrades') {
    state.ctMeta = null;
    state.ctLatest = null;
  }
  const loaders = {
    funds:        () => loadFunds(),
    fund:         () => loadFund(r.cik, r.tab),
    ticker:       () => loadTicker(r.ticker),
    consensus:    () => loadConsensus(),
    sectors:      () => loadSectors(),
    shortinterest: () => loadShortInterest(r),
    economic:     () => loadEconomicCalendar(),
    snapshot:     () => loadSnapshot(),
    insider:      () => loadInsider(r),
    momentum:     () => loadMomentum(r),
    correlation:  () => loadCorrelation(r),
    factors:      () => loadFactors(r),
    putcallratio: () => loadPutCallRatio(r),
    ivrank:       () => loadIVRank(r),
    unusualactivity: () => loadUnusualActivity(r),
    screener:     () => loadScreener(r),
    news:         () => loadNews(r),
    quotes:       () => loadQuotes(r),
    earningsrevisions: () => loadEarningsRevisions(r),
    crowdedtrades: () => loadCrowdedTrades(r),
  };
  const loader = loaders[r.view];
  if (!loader) {
    // API-free page (calculators/explainers): render immediately.
    state.loading = false;
    state.routeLoading = false;
    state.error = null;
    render();
    return;
  }
  // Show LOADING… (without the new view's body, whose data isn't loaded yet).
  // Deferred briefly so fast/cached loads don't flash the indicator.
  state.loading = true;
  state.routeLoading = true;
  const showLoading = setTimeout(() => {
    if (token === _routeToken && state.routeLoading) render();
  }, 150);
  try {
    await loader();
  } catch (e) {
    state.error = 'Navigation error: ' + e.message;
  }
  clearTimeout(showLoading);
  if (token !== _routeToken) return;  // superseded by a newer navigation
  state.routeLoading = false;
  state.loading = false;
  render();
}

// ---------------- render ----------------
export function render() {
  const root = document.getElementById('app');
  
  root.innerHTML = '';
  root.appendChild(renderMasthead());
  root.appendChild(renderNav());
  if (state.bootError) {
    root.appendChild(el('div', { class: 'error' }, state.bootError));
  }
  if (state.error) {
    root.appendChild(el('div', { class: 'error' }, state.error));
  }
  if (state.loading || state.routeLoading) {
    root.appendChild(el('div', { class: 'loading' }, 'LOADING…'));
  }
  if (state.routeLoading) return;  // route data still loading; see handleRoute
  const _desc = renderPageDescription(state.view);
  if (_desc) root.appendChild(_desc);
  if (state.view === 'funds')        root.appendChild(renderFunds());
  else if (state.view === 'fund')     root.appendChild(renderFund());
  else if (state.view === 'ticker')   root.appendChild(renderTicker());
  else if (state.view === 'consensus') root.appendChild(renderConsensusView());
  else if (state.view === 'sectors')  root.appendChild(renderSectors());
  if (state.view === 'shortinterest') root.appendChild(renderShortInterest());
  else if (state.view === 'economic')   root.appendChild(renderEconomicCalendar());
  else if (state.view === 'snapshot')  root.appendChild(renderSnapshot());
  else if (state.view === 'insider')   root.appendChild(renderInsider());
  else if (state.view === 'momentum')   root.appendChild(renderMomentum());
  else if (state.view === 'correlation') root.appendChild(renderCorrelation());
  if (state.view === 'putcallratio') root.appendChild(renderPutCallRatio());
  else if (state.view === 'ivrank') root.appendChild(renderIVRank());
  if (state.view === 'factors')        root.appendChild(renderFactors());
  if (state.view === 'news')           root.appendChild(renderNews());
  if (state.view === 'positioning')  root.appendChild(renderPositionSizing());
  if (state.view === 'drawdown')     root.appendChild(renderDrawdownSimulator());
  if (state.view === 'payoff')       root.appendChild(renderPayoffVisualizer());
  if (state.view === 'greeks')       root.appendChild(renderGreeksExplainer());
  if (state.view === 'optionsexplainer') root.appendChild(renderOptionsExplainer());
  if (state.view === 'unusualactivity') root.appendChild(renderUnusualActivity());
  if (state.view === 'screener')        root.appendChild(renderScreener());
  if (state.view === 'quotes')          root.appendChild(renderQuotes());
  if (state.view === 'earningsrevisions') root.appendChild(renderEarningsRevisions());
  if (state.view === 'crowdedtrades') root.appendChild(renderCrowdedTradesPage());
}

function renderMasthead() {
  const q = state.meta?.quarters?.[0]?.report_period || '';
  const isDataPage = state.view === 'funds' || state.view === 'fund' || state.view === 'ticker' || state.view === 'consensus' || state.view === 'sectors';

  // View-specific titles
  let title;
  if (state.view === 'snapshot') {
    title = 'Market Snapshot';
  } else if (state.view === 'shortinterest') {
    title = 'Short Interest';
  } else if (state.view === 'insider') {
    title = 'Insider Trading';
  } else if (state.view === 'economic') {
    title = 'Economic Calendar';
  } else if (state.view === 'momentum') {
    title = 'Price Momentum';
  } else if (state.view === 'correlation') {
    title = 'Correlation Matrix';
  } else if (state.view === 'putcallratio') {
    title = 'Put/Call Ratio';
  } else if (state.view === 'ivrank') {
    title = 'IV Rank Tracker';
  } else if (state.view === 'factors') {
    title = 'Factor Exposure';
  } else if (state.view === 'positioning') {
    title = 'Position Sizing';
  } else if (state.view === 'drawdown') {
    title = 'Drawdown Simulator';
  } else if (state.view === 'payoff') {
    title = 'Options Payoff';
  } else if (state.view === 'greeks') {
    title = 'Greeks Explainer';
  } else if (state.view === 'optionsexplainer') {
    title = 'Options Explainer';
  } else if (state.view === 'unusualactivity') {
    title = 'Unusual Activity';
  } else if (state.view === 'screener') {
    title = 'Stock Screener';
  } else if (state.view === 'quotes') {
    title = 'Famous Trader Quotes';
  } else if (state.view === 'earningsrevisions') {
    title = 'Earnings Revision Momentum';
  } else if (state.view === 'crowdedtrades') {
    title = 'Crowded Trades';
  } else if (state.view === 'fund') {
    // Show fund name instead of generic title
    return el('div', { class: 'masthead' },
      el('h1', {}, state.fund?.name || 'Fund'),
      isDataPage ? el('div', { class: 'sub' },
        q ? `Latest quarter: ${q} · ` : '',
        `${state.meta?.counts.filings || 0} filings · `,
        `${state.meta?.counts.funds || 0} funds · `,
        `${state.meta?.counts.unique_tickers?.toLocaleString() || 0} tickers`) : null,
    );
  } else {
    title = state.view === 'funds' ? 'Funds' : 'Purrtfolio Tools';
  }

  return el('div', { class: 'masthead' },
    el('h1', {}, title),
    isDataPage && q ? el('div', { class: 'sub' },
      `Latest quarter: ${q} · `,
      `${state.meta?.counts.filings || 0} filings · `,
      `${state.meta?.counts.funds || 0} funds · `,
      `${state.meta?.counts.unique_tickers?.toLocaleString() || 0} tickers`) : null,
  );
}

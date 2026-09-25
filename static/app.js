/* Trading Tools by Purrtfolio — single-page drill-down
   No framework. State is in `state` object; view = render(state).
   Routing via hash: #/  (funds list)
                    #/fund/{cik}  (fund detail)
                    #/fund/{cik}?tab=changes  (changes subview)
                    #/ticker/{ticker}  (cross-fund view)
                    #/consensus  (cross-fund momentum)
                    #/short-interest  (short interest overview)
                    #/short-interest/signals  (SI signals)
                    #/short-interest/{ticker}  (SI ticker history)
|*/
'use strict';

// API base URL — uses local server in dev, production otherwise
const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? ''
  : 'https://one3f-tracker-wpj6.onrender.com';

const state = {
  view:   'funds',
  fund:   null,             // current fund detail (cik, name, ...)
  ticker: null,             // current ticker detail
  meta:   null,
  funds:  [],
  holdings: { rows: [], total: 0, quarter: null },
  changes:  { rows: [], total: 0, quarter: null },
  fundTab: 'holdings',      // 'holdings' | 'changes'
  holdingsSort: { col: 'value', dir: 'desc' },
  holdingsFilters: { min_value: '', ticker: '', limit: 100, offset: 0 },
  changesFilters:  { status: '', min_abs_value: '', limit: 100, offset: 0 },
  consensus: { buys: [], sells: [], quarter: null, min_funds: 2 },
  loading: false,
  error:  null,
  siMeta: null,
  siLatest: { rows: [], total: 0, limit: 100, min_short: 1_000_000 },
  siSignals: null,
  siTicker: null,
  siActiveTab: 'latest',   // 'latest' | 'signals' | 'history'
  snapshot: null,           // latest market snapshot metadata
  econMeta: null,           // economic calendar metadata
  econEvents: [],           // economic calendar events
  econDaysAhead: 30,        // lookahead window
  econImpact: '',           // '' | 'high' | 'medium' | 'low'
  econCategory: '',         // filter by category
  insiderMeta: null,        // insider trading metadata
  insiderLatest: { rows: [], total: 0, limit: 100, min_value: '' },
  insiderSignals: null,     // top buys / sells / officer trades
  insiderTicker: null,      // single ticker full history
  insiderActiveTab: 'latest',  // 'latest' | 'signals' | 'ticker'
  // Price Momentum
  momMeta: null,
  momRankings: { rows: [], total: 0 },
  momVolumeSpikes: { rows: [], total: 0 },
  momConsolidation: { rows: [], total: 0 },
  momGaps: { rows: [], total: 0 },
  momTickerHistory: null,
  momActiveTab: 'rankings',   // 'rankings' | 'volume-spikes' | 'consolidation' | 'gaps' | 'ticker'
  // Correlation Matrix
  corrMeta: null,
  corrMatrix: null,
  corrPivotView: null,        // correlation to a specific pivot ticker
  corrActiveTab: 'matrix',   // 'matrix' | 'pivot'
  // Factor Exposure / Style Drift
  factorMeta: null,
  factorExposure: null,      // {quarter, dimensions, coverage_pct, ...}
  crowdedTrades: null,       // {quarter, rows}
  factorActiveTab: 'drift',  // 'drift' | 'crowded' | 'ticker'
  factorTicker: null,
  // Put/Call Ratio
  pcrMeta: null,
  pcrLatest: null,        // { latest_date, rows: [...] }
  pcrSignals: null,
  pcrHistory: null,       // { series, rows: [...] }
  pcrActiveTab: 'latest',  // 'latest' | 'signals' | 'history'
  pcrHistorySeries: 'TOTAL',
  pcrHistoryDays: 60,
  // IV Rank & IV Percentile
  ivMeta: null,
  ivLatest: { rows: [] },
  ivHistory: null,
  ivActiveTab: 'latest',
  ivSelectedTicker: null,
  ivHistoryDays: 300,
  // Unusual Activity / Dark Pool
  uaMeta: null,
  uaLatest: { rows: [] },
  uaHistory: null,
  uaActiveTab: 'latest',   // 'latest' | 'history'
  uaSelectedTicker: null,
  // News Sentiment
  newsMeta: null,        // { latest_date, total_headlines, sources, ... }
  newsHeadlines: null,   // { latest_date, headlines: [...] }
  newsSignals: null,     // { latest_date, bullish: [...], bearish: [...] }
  newsTickerDetail: null,// { ticker, history: [...], headlines: [...] }
  newsActiveTab: 'headlines',  // 'headlines' | 'signals' | 'ticker'
  newsTicker: null,
  // Stock Screener
  screenerMeta: null,
  screenerResults: { rows: [], total: 0 },
  screenerFilters: {
    sector: '', min_price: '', max_price: '',
    min_volume: '', min_market_cap: '',
    etf_only: false, stocks_only: false,
  },
  screenerSort: { col: 'market_cap', dir: 'desc' },
  // Famous Trader Quotes
  quoteMeta: null,
  quoteList: [],
  quoteCategory: '',
  // Earnings Revision Momentum
  ermMeta: null,
  ermRows: [],
};

// ---------------- helpers ----------------
// Lazy-load Chart.js — only fetched when a chart view is first rendered,
// so non-chart pages don't pay the 205KB download cost.
let _chartJsPromise = null;
function ensureChartJS() {
  if (typeof Chart !== 'undefined') return Promise.resolve();
  if (_chartJsPromise) return _chartJsPromise;
  _chartJsPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = './chart.min.js';
    script.onload = () => { resolve(); };
    script.onerror = () => { reject(new Error('Failed to load chart.min.js')); };
    document.head.appendChild(script);
  });
  return _chartJsPromise;
}

// Retry transient failures (network errors from Render free-tier cold starts,
// and 5xx/429/408) with exponential backoff so a single spin-up hiccup doesn't
// surface as "Failed to fetch". 5 attempts with 2s base covers ~30s cold starts.
async function api(path, params = {}, _attempt = 1) {
  const url = new URL(API + path, location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
  });
  let r;
  try {
    r = await fetch(url);
  } catch (e) {
    // Network-level failure (instance asleep / DNS / connection reset).
    if (_attempt >= 5) throw e;
    await new Promise(res => setTimeout(res, 2000 * Math.pow(2, _attempt - 1)));
    return api(path, params, _attempt + 1);
  }
  if (!r.ok) {
    // Retry transient server-side errors; fail fast on real 4xx client errors.
    if (_attempt < 5 && (r.status >= 500 || r.status === 408 || r.status === 429)) {
      await new Promise(res => setTimeout(res, 2000 * Math.pow(2, _attempt - 1)));
      return api(path, params, _attempt + 1);
    }
    const body = await r.text();
    throw new Error(`HTTP ${r.status}: ${body.slice(0, 200)}`);
  }
  return r.json();
}

function formatStrategy(s) {
  if (!s) return '—';
  const map = {
    'activist': 'Activist',
    'index_passive': 'Index Passive',
    'macro_all_weather': 'Macro All-Weather',
    'quant_multi_strat': 'Quant Multi-Strat',
    'sovereign': 'Sovereign',
    'tech_growth': 'Tech Growth',
    'value_concentrated': 'Value Concentrated',
  };
  return map[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function fmtUSD(n, { compact = true, sign = false } = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  const s = sign && n > 0 ? '+' : (n < 0 ? '−' : '');
  if (compact) {
    if (abs >= 1e12) return `${s}$${(abs / 1e12).toFixed(2)}T`;
    if (abs >= 1e9)  return `${s}$${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6)  return `${s}$${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3)  return `${s}$${(abs / 1e3).toFixed(0)}K`;
  }
  return `${s}$${abs.toLocaleString()}`;
}

function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString();
}

function fmtPct(n) {
  if (n === null || n === undefined) return '—';
  const s = n > 0 ? '+' : '';
  return `${s}${n.toFixed(1)}%`;
}

// Compute % of free float: (short_interest_shares / free_float_shares * 100)
function computePctFreeFloat(r) {
  if (!r.free_float_shares || r.free_float_shares <= 0 || !r.current_short) return null;
  return (r.current_short * 100.0 / r.free_float_shares).toFixed(2);
}

function fmtFreeFloat(r) {
  if (r.pct_of_free_float !== null && r.pct_of_free_float !== undefined) {
    return r.pct_of_free_float.toFixed(2) + '%';
  }
  const pct = computePctFreeFloat(r);
  return pct !== null ? pct + '%' : '—';
}

function fmtDateISO(s) {
  if (!s) return '—';
  return `${String(s).slice(5, 7)}/${String(s).slice(8, 10)}/${String(s).slice(0, 4)}`;
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    if (c instanceof Node) {
      e.appendChild(c);
    } else {
      e.appendChild(document.createTextNode(String(c)));
    }
  }
  return e;
}

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
  if (h.startsWith('short-interest') || h === 'short-interest/') return { view: 'shortinterest' };
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
    return { view: 'putcallratio', pcrTab: 'ticker', pcrTicker: rest.toUpperCase() };
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

// Chart color palette - using actual hex values (CSS variables don't work in Chart.js)
const CHART_COLORS = {
  brass: '#C9A24E',
  green: '#2E9E6B',
  red: '#C7564A',
  blue: '#3B82F6',
  pink: '#EC4899',
  orange: '#F97316',
  teal: '#14B8A6',
  purple: '#A855F7',
  amber: '#EAB308',
  cyan: '#22D3EE',
  indigo: '#6366F1',
  emerald: '#10B981',
  rose: '#F43F5E',
};

const CHART_COLOR_ARRAY = [
  CHART_COLORS.brass,
  CHART_COLORS.green,
  CHART_COLORS.red,
  CHART_COLORS.blue,
  CHART_COLORS.pink,
  CHART_COLORS.orange,
  CHART_COLORS.teal,
  CHART_COLORS.purple,
  CHART_COLORS.amber,
  CHART_COLORS.cyan,
  CHART_COLORS.indigo,
  CHART_COLORS.emerald,
  CHART_COLORS.rose,
];

// Chart instances stored to allow destruction on re-render
const charts = {};

function destroyAllCharts() {
  Object.keys(charts).forEach(key => {
    if (charts[key]) {
      charts[key].destroy();
      delete charts[key];
    }
  });
}

function generateColorShades(baseColor, count) {
  // Use the base color directly with slight variations for better visibility
  // Chart.js works better with explicit color arrays
  return CHART_COLOR_ARRAY.slice(0, count);
}

async function createPieChart(canvasId, data, options = {}) {
  await ensureChartJS();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (charts[canvasId]) {
    charts[canvasId].destroy();
  }
  // Explicit colors for Chart.js (CSS variables don't work reliably in canvas)
  const TEXT_COLOR = '#E8EBEF';
  const TEXT_DIM = '#7E8A9A';
  const PANEL = '#11161D';
  const LINE = '#1E2A38';
  charts[canvasId] = new Chart(ctx, {
    type: 'pie',
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            font: { family: 'ui-monospace, SFMono-Regular, monospace', size: 10 },
            color: TEXT_COLOR,
            padding: 8,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: PANEL,
          titleColor: TEXT_COLOR,
          bodyColor: TEXT_DIM,
          borderColor: LINE,
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: (ctx) => {
              const label = ctx.label || '';
              const value = ctx.parsed;
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((value / total) * 100).toFixed(1);
              return `${label}: ${pct}% (${fmtUSD(value)})`;
            },
          },
        },
      },
      ...options,
    },
  });
  return charts[canvasId];
}

async function createBarChart(canvasId, data, options = {}) {
  await ensureChartJS();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (charts[canvasId]) {
    charts[canvasId].destroy();
  }
  const TEXT_COLOR = '#E8EBEF';
  const TEXT_DIM = '#7E8A9A';
  const LINE = '#1E2A38';
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#11161D',
          titleColor: TEXT_COLOR,
          bodyColor: TEXT_DIM,
          borderColor: LINE,
          borderWidth: 1,
          padding: 12,
        },
      },
      scales: {
        x: {
          ticks: { color: TEXT_COLOR, font: { size: 11 } },
          grid: { color: LINE },
        },
        y: {
          ticks: { color: TEXT_DIM, font: { size: 10 } },
          grid: { color: LINE },
        },
      },
      ...options,
    },
  });
  return charts[canvasId];
}

function createFundHoldingsChart(holdings) {
  const sorted = [...holdings].sort((a, b) => b.market_value_usd - a.market_value_usd);
  const top10 = sorted.slice(0, 10);
  const others = sorted.slice(10);
  const othersValue = others.reduce((sum, h) => sum + h.market_value_usd, 0);
  
  const labels = top10.map(h => h.ticker || h.cusip.slice(-6));
  if (othersValue > 0) labels.push('Others');
  
  const data = top10.map(h => h.market_value_usd);
  if (othersValue > 0) data.push(othersValue);
  
  createPieChart('fund-holdings-chart', {
    labels: labels,
    datasets: [{
      data: data,
      backgroundColor: CHART_COLOR_ARRAY.slice(0, labels.length),
      borderWidth: 1,
      borderColor: 'var(--bg)',
    }],
  });
}

function createTickerHoldersChart(holders) {
  const sorted = [...holders].sort((a, b) => b.market_value_usd - a.market_value_usd);
  const top10 = sorted.slice(0, 10);
  const others = sorted.slice(10);
  const othersValue = others.reduce((sum, h) => sum + h.market_value_usd, 0);
  
  const labels = top10.map(h => h.name.slice(0, 20));
  if (othersValue > 0) labels.push('Others');
  
  const data = top10.map(h => h.market_value_usd);
  if (othersValue > 0) data.push(othersValue);
  
  createPieChart('ticker-holders-chart', {
    labels: labels,
    datasets: [{
      data: data,
      backgroundColor: CHART_COLOR_ARRAY.slice(0, labels.length),
      borderWidth: 1,
      borderColor: 'var(--bg)',
    }],
  });
}

function createConsensusCharts(buys, sells) {
  const topBuys = buys.slice(0, 8);
  const buyLabels = topBuys.map(r => r.ticker);
  const buyData = topBuys.map(r => r.net_change_usd);
  
  createPieChart('consensus-buys-chart', {
    labels: buyLabels,
    datasets: [{
      data: buyData,
      backgroundColor: generateColorShades(CHART_COLORS.green, buyLabels.length),
      borderWidth: 1,
      borderColor: 'var(--bg)',
    }],
  });
  
  const topSells = sells.slice(0, 8);
  const sellLabels = topSells.map(r => r.ticker);
  const sellData = topSells.map(r => Math.abs(r.net_change_usd));
  
  createPieChart('consensus-sells-chart', {
    labels: sellLabels,
    datasets: [{
      data: sellData,
      backgroundColor: generateColorShades(CHART_COLORS.red, sellLabels.length),
      borderWidth: 1,
      borderColor: 'var(--bg)',
    }],
  });
}

function setHash(h) {
  if (location.hash === h) {
    // force re-render
    handleRoute();
  } else {
    location.hash = h;
  }
}

window.addEventListener('hashchange', handleRoute);
window.addEventListener('error', (e) => {
  console.error('Global error:', e.error);
});
window.addEventListener('unhandledrejection', (e) => {
  console.error('Unhandled promise rejection:', e.reason);
});

async function handleRoute() {
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
  try {
    if (r.view === 'funds')        await loadFunds();
    else if (r.view === 'fund')    await loadFund(r.cik, r.tab);
    else if (r.view === 'ticker')  await loadTicker(r.ticker);
    else if (r.view === 'consensus') await loadConsensus();
    else if (r.view === 'sectors') await loadSectors();
    else if (r.view === 'shortinterest') await loadShortInterest(r);
    else if (r.view === 'economic') await loadEconomicCalendar();
    else if (r.view === 'snapshot') await loadSnapshot();
    else if (r.view === 'insider') await loadInsider(r);
    else if (r.view === 'momentum') await loadMomentum(r);
    else if (r.view === 'correlation') await loadCorrelation(r);
    else if (r.view === 'factors')     await loadFactors(r);
    else if (r.view === 'putcallratio') await loadPutCallRatio(r);
    else if (r.view === 'ivrank')        await loadIVRank(r);
    else if (r.view === 'unusualactivity') await loadUnusualActivity(r);
    else if (r.view === 'screener')       await loadScreener(r);
    else if (r.view === 'news')        await loadNews(r);
    else if (r.view === 'quotes')      await loadQuotes(r);
    else if (r.view === 'earningsrevisions') await loadEarningsRevisions(r);
  } catch (e) {
    state.error = 'Navigation error: ' + e.message;
  }
  render();
}

// ---------------- data loaders ----------------
async function loadMeta() {
  if (state.meta) return state.meta;
  state.meta = await api('/api/meta');
  return state.meta;
}

async function loadFunds() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const d = await api('/api/funds');
    state.funds = d.funds;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadFund(cik, tab) {
  state.error = null;
  state.loading = true;
  state.fundTab = tab || 'holdings';
  try {
    await loadMeta();
    const [fund, h] = await Promise.all([
      api(`/api/funds/${cik}`),
      api(`/api/funds/${cik}/holdings`,
          { ...state.holdingsFilters,
            limit: state.holdingsFilters.limit,
            offset: state.holdingsFilters.offset,
            sort_by: state.holdingsSort.col,
            sort_dir: state.holdingsSort.dir }),
    ]);
    state.fund = fund;
    state.holdings = h;
    if (state.fundTab === 'changes') {
      const c = await api(`/api/funds/${cik}/changes`,
        { ...state.changesFilters,
          limit: state.changesFilters.limit,
          offset: state.changesFilters.offset });
      state.changes = c;
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadTicker(ticker) {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    state.ticker = await api(`/api/tickers/${ticker}`);
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadConsensus() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    state.consensus = await api('/api/consensus', { min_funds: state.consensus.min_funds });
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadSectors() {
  state.error = null;
  state.loading = true;
  try {
    const r = await api('/api/sectors');
    state.sectors = r.sectors || [];
    state.sectorPeriods = r.periods || { prev_q: null, curr_q: null };
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadSnapshot() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    state.snapshot = await api('/api/snapshot/latest');
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadEconomicCalendar() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, events] = await Promise.all([
      api('/api/econ/meta'),
      api('/api/econ/events', {
        days_ahead: state.econDaysAhead,
        impact: state.econImpact,
        category: state.econCategory,
      }),
    ]);
    state.econMeta = meta;
    state.econEvents = events.events || events;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadShortInterest(r) {
  state.error = null;
  state.loading = true;
  state.siActiveTab = r.siTab || (r.siTicker ? 'history' : 'latest');
  try {
    await loadMeta();
    // Batch all three calls in parallel instead of sequential
    const [meta, signals, latestResp, tickerResp] = await Promise.all([
      api('/api/si/meta'),
      api('/api/si/signals'),
      api('/api/si/latest', { min_short: state.siLatest.min_short, limit: state.siLatest.limit }),
      r.siTicker ? api('/api/si/tickers/' + r.siTicker) : Promise.resolve(null),
    ]);
    state.siMeta = meta;
    state.siSignals = signals;
    state.siLatest.rows = latestResp.rows || latestResp;
    state.siLatest.total = state.siLatest.rows.length;
    if (r.siTicker) {
      state.siActiveTab = 'history';
      state.siTicker = tickerResp;
    }
  } catch (e) {
      state.error = e.message;
    } finally {
      state.loading = false;
    }
  }

async function loadInsider(r) {
  state.error = null;
  state.loading = true;
  state.insiderActiveTab = r.insiderTab || 'latest';
  try {
    await loadMeta();
    // Batch meta + tab-specific data call in parallel
    const metaPromise = api('/api/insider/meta');
    let dataPromise = Promise.resolve(null);
    if (state.insiderActiveTab === 'latest') {
      dataPromise = api('/api/insider/latest', {
        min_value: state.insiderLatest.min_value || undefined,
        limit: state.insiderLatest.limit,
      });
    } else if (state.insiderActiveTab === 'signals') {
      dataPromise = api('/api/insider/signals', { limit: 100 });
    }
    const [meta, data] = await Promise.all([metaPromise, dataPromise]);
    state.insiderMeta = meta;
    if (state.insiderActiveTab === 'latest') {
      state.insiderLatest.rows = data.rows || data;
      state.insiderLatest.total = state.insiderLatest.rows.length;
    } else if (state.insiderActiveTab === 'signals') {
      state.insiderSignals = data;
    }
    if (r.insiderTicker) {
      state.insiderActiveTab = 'ticker';
      state.insiderTicker = await api('/api/insider/tickers/' + r.insiderTicker);
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadMomentum(r) {
  state.momActiveTab = r.momTicker ? 'ticker' : (r.momTab || 'rankings');
  // Tab switch within Price Momentum (no specific ticker): if all four
  // datasets are already cached, flip the tab view instantly without a server
  // round-trip — handleRoute() re-renders after we return.
  if (!r.momTicker && state.momRankings && state.momVolumeSpikes && state.momConsolidation && state.momGaps) {
    return;
  }
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, rankings, spikes, consolidation, gaps] = await Promise.all([
      api('/api/momentum/meta'),
      api('/api/momentum/rankings'),
      api('/api/momentum/volume-spikes'),
      api('/api/momentum/consolidation'),
      api('/api/momentum/earnings-gaps'),
    ]);
    state.momMeta = meta;
    state.momRankings = { rows: rankings, total: rankings.length };
    state.momVolumeSpikes = { rows: spikes, total: spikes.length };
    state.momConsolidation = { rows: consolidation, total: consolidation.length };
    state.momGaps = { rows: gaps, total: gaps.length };
    if (r.momTicker) {
      state.momTickerHistory = await api('/api/momentum/tickers/' + r.momTicker);
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadCorrelation(r) {
  state.error = null;
  state.loading = true;
  state.corrActiveTab = r.corrPivot ? 'pivot' : 'matrix';
  try {
    await loadMeta();
    // Batch meta + data call in parallel
    const [meta, data] = await Promise.all([
      api('/api/correlation/meta'),
      r.corrPivot
        ? api('/api/correlation/pivot/' + r.corrPivot)
        : api('/api/correlation/matrix'),
    ]);
    state.corrMeta = meta;
    if (r.corrPivot) {
      state.corrPivotView = data;
    } else {
      state.corrMatrix = data;
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadFactors(r) {
  state.error = null;
  state.loading = true;
  state.factorActiveTab = r.factorTab || 'drift';
  // 13F data is quarterly/static — cache drift + crowded on first load;
  // only (re)fetch the per-ticker detail when drilling into a ticker.
  const cached = state.factorExposure && state.crowdedTrades;
  if (!r.factorTicker && cached && state.factorActiveTab !== 'ticker') {
    state.loading = false;
    return;
  }
  try {
    await loadMeta();
    if (state.factorActiveTab === 'ticker') {
      // Batch meta + ticker detail in parallel (404 on ticker is not an error)
      const [meta, tickerData] = await Promise.all([
        api('/api/factors/meta'),
        api('/api/factors/tickers/' + r.factorTicker).catch(e => {
          if (e.message && e.message.includes('404')) return null;
          throw e;
        }),
      ]);
      state.factorMeta = meta;
      state.factorTicker = tickerData;
    } else {
      state.factorMeta = await api('/api/factors/meta');
    }
    if (state.factorActiveTab === 'drift' && !state.factorExposure) {
      state.factorExposure = await api('/api/factors/exposure');
    }
    if (state.factorActiveTab === 'crowded' && !state.crowdedTrades) {
      state.crowdedTrades = await api('/api/factors/crowded');
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function reloadFactorTab(tab) {
  state.factorActiveTab = tab;
  state.loading = true;
  try {
    if (tab === 'drift' && !state.factorExposure) {
      state.factorExposure = await api('/api/factors/exposure');
    }
    if (tab === 'crowded' && !state.crowdedTrades) {
      state.crowdedTrades = await api('/api/factors/crowded');
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function reloadFundTab(cik, tab) {
  state.fundTab = tab;
  state.error = null;
  state.loading = true;
  try {
    if (tab === 'changes') {
      state.changes = await api(`/api/funds/${cik}/changes`, state.changesFilters);
    } else {
      state.holdings = await api(`/api/funds/${cik}/holdings`, {
        ...state.holdingsFilters,
        sort_by: state.holdingsSort.col,
        sort_dir: state.holdingsSort.dir,
      });
    }
  } catch (e) { state.error = e.message; }
  finally { state.loading = false; }
  render();
}

// ---------------- Put/Call Ratio loader ----------------
async function loadPutCallRatio(r) {
  state.pcrActiveTab = r.pcrTab || 'latest';
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    // Batch all three calls in parallel
    const [meta, latest, signals] = await Promise.all([
      api('/api/pcr/meta'),
      api('/api/pcr/latest'),
      api('/api/pcr/signals'),
    ]);
    state.pcrMeta = meta;
    state.pcrLatest = latest;
    state.pcrSignals = signals;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}
// ---------------- IV Rank loader ----------------
async function loadIVRank(r) {
  state.ivActiveTab = r.ivTab || 'latest';
  state.ivSelectedTicker = r.ivTicker || null;
  state.ivHistoryDays = r.ivHistoryDays || 300;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, latest] = await Promise.all([
      api('/api/iv/meta'),
      api('/api/iv/latest'),
    ]);
    state.ivMeta = meta;
    state.ivLatest = latest;
    if (state.ivSelectedTicker) {
      state.ivHistory = await api(`/api/iv/history/${state.ivSelectedTicker}?days=${state.ivHistoryDays}`);
      state.ivActiveTab = 'history';
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- Unusual Activity loader ----------------
async function loadUnusualActivity(r) {
  state.uaActiveTab = r.uaTab || 'latest';
  state.uaSelectedTicker = r.uaTicker || null;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, latest] = await Promise.all([
      api('/api/ua/meta'),
      api('/api/ua/latest'),
    ]);
    state.uaMeta = meta;
    state.uaLatest = latest;
    if (state.uaSelectedTicker) {
      state.uaHistory = await api(`/api/ua/history/${state.uaSelectedTicker}`);
      state.uaActiveTab = 'history';
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadScreener(r) {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const f = state.screenerFilters;
    const [meta, results] = await Promise.all([
      api('/api/screener/meta'),
      api('/api/screener', {
        sector:     f.sector,
        min_price:  f.min_price,
        max_price:  f.max_price,
        min_volume: f.min_volume,
        min_market_cap: f.min_market_cap,
        etf_only:   f.etf_only,
        stocks_only: f.stocks_only,
        sort_col:   state.screenerSort.col,
        sort_dir:   state.screenerSort.dir,
        limit:      100,
      }),
    ]);
    state.screenerMeta = meta;
    state.screenerResults = { rows: results, total: results.length };
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function applyScreenerFilters() {
  const f = state.screenerFilters;
  try {
    state.loading = true;
    const results = await api('/api/screener', {
      sector:      f.sector,
      min_price:   f.min_price,
      max_price:   f.max_price,
      min_volume:  f.min_volume,
      min_market_cap: f.min_market_cap,
      etf_only:    f.etf_only,
      stocks_only: f.stocks_only,
      sort_col:    state.screenerSort.col,
      sort_dir:    state.screenerSort.dir,
      limit:       100,
    });
    state.screenerResults = { rows: results, total: results.length };
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
    render();
  }
}

async function setScreenerSort(col, dir) {
  state.screenerSort = { col, dir };
  await applyScreenerFilters();
}

async function loadQuotes(r) {
  state.error = null;
  state.loading = true;
  try {
    const cat = r && r.category ? r.category : state.quoteCategory || '';
    state.quoteCategory = cat;
    await loadMeta();
    const [meta, quotes] = await Promise.all([
      api('/api/quotes/meta'),
      api('/api/quotes', { category: cat, limit: 50 }),
    ]);
    state.quoteMeta = meta;
    state.quoteList = quotes;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadRandomQuote() {
  try {
    state.loading = true;
    const q = await api('/api/quotes/random');
    state.quoteList = q ? [q] : [];
    if (!state.quoteMeta) {
      state.quoteMeta = await api('/api/quotes/meta');
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
    render();
  }
}

function changeQuoteCategory(cat) {
  state.quoteCategory = cat;
  loadQuotes({ category: cat });
}

async function loadEarningsRevisions(r) {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, rows] = await Promise.all([
      api('/api/earnings-revisions/meta'),
      api('/api/earnings-revisions'),
    ]);
    state.ermMeta = meta;
    state.ermRows = rows;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- render ----------------
function render() {
  const root = document.getElementById('app');
  
  root.innerHTML = '';
  root.appendChild(renderMasthead());
  root.appendChild(renderNav());
  if (state.error) {
    root.appendChild(el('div', { class: 'error' }, state.error));
  }
  if (state.loading) {
    root.appendChild(el('div', { class: 'loading' }, 'LOADING…'));
  }
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

// Nav link definitions grouped by category
const NAV_GROUPS = [
  {
    label: 'Data Views',
    items: [
      { view: 'funds',     label: 'Funds' },
      { view: 'consensus', label: 'Consensus' },
      { view: 'sectors',   label: 'Sectors' },
    ],
  },
  {
    label: 'Scanners',
    items: [
      { view: 'snapshot',      label: 'Market Snapshot' },
      { view: 'shortinterest', label: 'Short Interest' },
      { view: 'economic',      label: 'Economic Calendar' },
      { view: 'insider',       label: 'Insider Trading' },
      { view: 'momentum',      label: 'Price Momentum' },
      { view: 'correlation',   label: 'Correlation Matrix' },
      { view: 'factors',       label: 'Factor Exposure' },
      { view: 'putcallratio',  label: 'Put/Call Ratio' },
      { view: 'ivrank',        label: 'IV Rank Tracker' },
      { view: 'news',          label: 'News Sentiment' },
      { view: 'screener',      label: 'Stock Screener' },
      { view: 'earningsrevisions', label: 'Earnings Revision' },
    ],
  },
  {
    label: 'Tools',
    items: [
      { view: 'positioning', label: 'Position Sizing' },
      { view: 'drawdown',    label: 'Drawdown Simulator' },
      { view: 'payoff',      label: 'Options Payoff' },
      { view: 'greeks',      label: 'Greeks Explainer' },
      { view: 'optionsexplainer', label: 'Options Explainer' },
      { view: 'quotes',           label: 'Famous Trader Quotes' },
    ],
  },
];

// Map nav item view → hash route
const NAV_ROUTES = {
  funds:       '#/funds',
  consensus:   '#/consensus',
  sectors:     '#/sectors',
  snapshot:    '#/snapshot',
  shortinterest: '#/short-interest',
  economic:    '#/economic-calendar',
  insider:     '#/insider',
  momentum:    '#/momentum',
  correlation: '#/correlation',
  factors:     '#/factors',
  putcallratio: '#/put-call-ratio',
  ivrank:       '#/iv-rank',
  news:         '#/news',
  positioning:  '#/position-sizing',
  drawdown:     '#/drawdown-simulator',
  payoff:       '#/payoff-visualizer',
  greeks:        '#/greeks-explainer',
  optionsexplainer: '#/options-explainer',
  unusualactivity: '#/unusual-activity',
  screener:       '#/screener',
  earningsrevisions: '#/earnings-revisions',
  quotes:         '#/quotes',
};

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
    intro: 'Tracks earnings revision momentum across the watchlist universe (~24 large-cap tickers). For each ticker, the scanner fetches yfinance\u2019s earnings_history (actual vs estimate for the last 4 reported quarters), computes a mean revision percentage, fraction of positive surprises, and a z-scored momentum rank. Ticklers are classified as improving / deteriorating / stable based on whether recent-quarter revisions are accelerating or decelerating. Data is fetched daily at 5:30 AM UTC+10 via cron and stored in the unified purrtfolio.db. The z-score compares each ticker\u2019s revision magnitude to the cross-sectional mean and standard deviation — higher scores indicate stronger positive earnings surprises relative to peers.',
    issues: 'yfinance earnings_history availability is inconsistent — ETFs (SPY, QQQ, IWM) and some foreign tickers return 404 and are silently skipped. The 4-quarter window means tickers with fewer reported quarters are excluded entirely, which can bias the universe toward larger, more consistent reporters. Revision pct uses (actual - estimate) / |estimate|, so small or negative estimates can produce extreme values; the z-score dampens this but outliers like BA can still dominate the ranking. The trend classification threshold (\u00b12% recent-vs-older delta) is a heuristic — a \u201cstable\u201d reading may still reflect meaningful acceleration below the threshold. Data lags real-time by 1-2 days during earnings season.',
  },
};

function renderPageDescription(view) {
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

function renderNav() {
  const nav = el('div', { class: 'nav' });

  // Brand / logo
  nav.appendChild(el('a', {
    class: 'nav-brand',
    href: '#/snapshot',
    onclick: (e) => { e.preventDefault(); setHash('#/snapshot'); },
  }, 'Purrtfolio'));

  // Dropdown groups
  for (const group of NAV_GROUPS) {
    const dropdown = el('div', { class: 'nav-dropdown' });

    // Trigger label
    const trigger = el('div', {
      class: 'nav-dropdown-label',
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

  // Global ticker search (stays flat, outside dropdowns)
  const search = el('input', {
    class: 'nav-search',
    type: 'search',
    placeholder: 'Search ticker (e.g. NVDA) and press Enter…',
    onkeydown: (e) => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        setHash('#/ticker/' + e.target.value.trim().toUpperCase());
      }
    }
  });
  nav.appendChild(search);
  nav.appendChild(el('div', { class: 'nav-spacer' }));
  return nav;
}

// Close all open dropdowns (click-outside, Escape, after navigation)
function closeNavDropdowns() {
  document.querySelectorAll('.nav-dropdown.open').forEach(d => d.classList.remove('open'));
}

// Click-outside handler
document.addEventListener('click', (e) => {
  if (!e.target.closest('.nav-dropdown')) {
    closeNavDropdowns();
  }
});

// Escape key closes dropdowns
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeNavDropdowns();
  }
});

// ---- Funds list view ----
function renderFunds() {
  const wrap = el('div', { class: 'section' });

  // Top stats
  const totalAum = state.funds.reduce((s, f) => s + (f.latest_aum_usd || 0), 0);
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Funds', state.funds.length));
  stats.appendChild(stat('Tracked AUM', fmtUSD(totalAum), 'brass'));
  stats.appendChild(stat('Quarters tracked', state.meta?.quarters?.length || 0));
  const latestQ = state.meta?.quarters?.[0]?.report_period || '';
  stats.appendChild(stat('Latest quarter', latestQ));
  wrap.appendChild(stats);

  // Funds table
  const tableWrap = el('div', { class: 'table-wrap' });
  const rows = state.funds;
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Strategy', 'Fund', 'CIK', 'Latest AUM', 'Holdings'].forEach((h, i) => {
    const th = el('th', { class: i >= 3 ? 'num' : '' }, h);
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const f of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/fund/' + f.cik),
    });
    tr.appendChild(el('td', {},
      el('span', { class: 'strategy-tag' }, f.strategy || '—')));
    tr.appendChild(el('td', { class: 'brass' }, f.name));
    tr.appendChild(el('td', { class: 'mono mut' }, f.cik));
    tr.appendChild(el('td', { class: 'num' },
      f.latest_aum_usd ? fmtUSD(f.latest_aum_usd) : '—'));
    tr.appendChild(el('td', { class: 'num mut' },
      f.latest_holdings_count?.toLocaleString() || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

function stat(label, value, cls = '') {
  return el('div', { class: 'stat' },
    el('div', { class: 'stat-label' }, label),
    el('div', { class: 'stat-value ' + cls }, value));
}

// ---- Fund detail view ----
function renderFund() {
  if (!state.fund) return el('div', { class: 'empty' }, 'Fund not found');
  const f = state.fund;
  const cik = f.cik;
  const latestQ = state.holdings.quarter || f.filings?.[0]?.report_period || '';
  const latestAum = f.filings?.[0]?.total_value_usd;

  const wrap = el('div');

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/funds',
    onclick: (e) => { e.preventDefault(); setHash('#/funds'); },
  }, '← Funds'));
  header.appendChild(el('h2', {}, f.name));
  if (f.strategy) header.appendChild(el('div', { class: 'strategy-tag' }, f.strategy));
  const meta = el('div', { class: 'meta-grid' });
  meta.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'CIK'),
    el('span', { class: 'meta-value mono' }, cik)));
  meta.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Latest AUM'),
    el('span', { class: 'meta-value brass' },
      latestAum ? fmtUSD(latestAum) : '—')));
  meta.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Holdings'),
    el('span', { class: 'meta-value' },
      f.filings?.[0]?.total_holdings?.toLocaleString() || '—')));
  meta.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Latest'),
    el('span', { class: 'meta-value' }, latestQ || '—')));
  header.appendChild(meta);
  wrap.appendChild(header);

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabHoldings = el('div', {
    class: 'tab' + (state.fundTab === 'holdings' ? ' active' : ''),
    onclick: () => setHash('#/fund/' + cik),
  }, 'Holdings',
    el('span', { class: 'badge' }, f.filings?.[0]?.total_holdings?.toLocaleString() || ''));
  const tabChanges = el('div', {
    class: 'tab' + (state.fundTab === 'changes' ? ' active' : ''),
    onclick: () => setHash('#/fund/' + cik + '?tab=changes'),
  }, 'Changes',
    el('span', { class: 'badge' }, state.changes.total || ''));
  tabs.appendChild(tabHoldings);
  tabs.appendChild(tabChanges);
  wrap.appendChild(tabs);

  // Tab body
  if (state.fundTab === 'holdings') wrap.appendChild(renderHoldingsTab(cik));
  else wrap.appendChild(renderChangesTab(cik));

  return wrap;
}

function renderHoldingsTab(cik) {
  const wrap = el('div', { class: 'section' });
  const filters = el('div', { class: 'filters' });

  // Sort buttons (value desc / asc, shares)
  const sortBtn = (col, label) => {
    const isCurrent = state.holdingsSort.col === col;
    const dir = isCurrent && state.holdingsSort.dir === 'desc' ? 'asc' : 'desc';
    return el('button', {
      class: isCurrent ? 'active' : '',
      onclick: async () => {
        state.holdingsSort = { col, dir };
        state.holdingsFilters.offset = 0;
        state.loading = true; render();
        state.holdings = await api(`/api/funds/${cik}/holdings`,
          { ...state.holdingsFilters, sort_by: col, sort_dir: dir });
        state.loading = false; render();
      },
    }, `${label} ${isCurrent ? (state.holdingsSort.dir === 'desc' ? '▾' : '▴') : ''}`);
  };
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Sort:'),
    sortBtn('value', '$ Value'),
    sortBtn('shares', 'Shares'),
    sortBtn('ticker', 'Ticker'),
  ));

  // Min value filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Min $:'),
    el('input', {
      type: 'text', placeholder: '1B',
      value: state.holdingsFilters.min_value,
      onkeydown: async (e) => {
        if (e.key === 'Enter') {
          const v = e.target.value.trim();
          const n = v.endsWith('B') ? parseFloat(v) * 1e9
                  : v.endsWith('M') ? parseFloat(v) * 1e6
                  : parseFloat(v);
          state.holdingsFilters.min_value = isNaN(n) ? '' : n;
          state.holdingsFilters.offset = 0;
          await reloadFundTab(cik, 'holdings');
        }
      }
    })));

  // Ticker filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Filter:'),
    el('input', {
      type: 'search', placeholder: 'ticker or name…',
      value: state.holdingsFilters.ticker,
      onkeydown: async (e) => {
        if (e.key === 'Enter') {
          state.holdingsFilters.ticker = e.target.value.trim();
          state.holdingsFilters.offset = 0;
          await reloadFundTab(cik, 'holdings');
        }
      }
    })));
  wrap.appendChild(filters);

  // Chart + Table container
  const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });
  
  // Chart canvas
  const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
  chartWrap.appendChild(el('canvas', { id: 'fund-holdings-chart' }));
  chartTableWrap.appendChild(chartWrap);

  // Holdings table
  const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: '400px' } });
  if (!state.holdings.holdings || state.holdings.holdings.length === 0) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No holdings match these filters.'));
    wrap.appendChild(tableWrap);
    return wrap;
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Issuer', 'CUSIP', 'Shares', 'Value'].forEach((h, i) => {
    const cls = i === 3 || i === 4 ? 'num' : '';
    const sorted = (i === 4 && state.holdingsSort.col === 'value') ||
                   (i === 3 && state.holdingsSort.col === 'shares') ? 'sorted' : '';
    trh.appendChild(el('th', { class: cls + ' ' + sorted }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const h of state.holdings.holdings) {
    const tr = el('tr', {
      style: { cursor: h.ticker ? 'pointer' : 'default' },
      onclick: () => h.ticker && setHash('#/ticker/' + h.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, h.ticker || '—'));
    tr.appendChild(el('td', {}, h.issuer_name));
    tr.appendChild(el('td', { class: 'mono mut' }, h.cusip));
    tr.appendChild(el('td', { class: 'num' }, fmtNum(h.shares)));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(h.market_value_usd)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  // Pagination
  const total = state.holdings.total;
  const offset = state.holdingsFilters.offset || 0;
  const limit = state.holdingsFilters.limit || 100;
  if (total > limit) {
    const pager = el('div', { class: 'pager' });
    pager.appendChild(el('span', {},
      `Showing ${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}`));
    const btns = el('div', { class: 'pager-buttons' });
    const prevDis = offset === 0;
    const nextDis = offset + limit >= total;
    btns.appendChild(el('button', {
      disabled: prevDis,
      onclick: async () => {
        state.holdingsFilters.offset = Math.max(0, offset - limit);
        await reloadFundTab(cik, 'holdings');
      },
    }, '← Prev'));
    btns.appendChild(el('button', {
      disabled: nextDis,
      onclick: async () => {
        state.holdingsFilters.offset = offset + limit;
        await reloadFundTab(cik, 'holdings');
      },
    }, 'Next →'));
    pager.appendChild(btns);
    wrap.appendChild(pager);
  }

  // Create chart after DOM is ready
  setTimeout(() => createFundHoldingsChart(state.holdings.holdings), 0);

  return wrap;
}

function renderChangesTab(cik) {
  const wrap = el('div', { class: 'section' });

  const filters = el('div', { class: 'filters' });
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Status:'),
    ...['', 'NEW', 'INCREASED', 'DECREASED', 'CLOSED', 'UNCHANGED'].map(s =>
      el('button', {
        class: state.changesFilters.status === s ? 'active' : '',
        onclick: async () => {
          state.changesFilters.status = s;
          state.changesFilters.offset = 0;
          state.loading = true; render();
          state.changes = await api(`/api/funds/${cik}/changes`, state.changesFilters);
          state.loading = false; render();
        },
      }, s || 'ALL')
    )
  ));
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Min |Δ$|:'),
    el('input', {
      type: 'text', placeholder: '100M',
      onkeydown: async (e) => {
        if (e.key === 'Enter') {
          const v = e.target.value.trim();
          const n = v.endsWith('B') ? parseFloat(v) * 1e9
                  : v.endsWith('M') ? parseFloat(v) * 1e6
                  : parseFloat(v);
          state.changesFilters.min_abs_value = isNaN(n) ? '' : n;
          state.changesFilters.offset = 0;
          await reloadFundTab(cik, 'changes');
        }
      }
    })));
  wrap.appendChild(filters);

  const tableWrap = el('div', { class: 'table-wrap' });
  if (!state.changes.changes || state.changes.changes.length === 0) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No changes match these filters.'));
    wrap.appendChild(tableWrap);
    return wrap;
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Status', 'Ticker', 'Issuer', 'Prev Sh', 'Curr Sh', 'Δ$'].forEach((h, i) => {
    const cls = (i >= 3) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const c of state.changes.changes) {
    const tr = el('tr', {
      style: { cursor: c.ticker ? 'pointer' : 'default' },
      onclick: () => c.ticker && setHash('#/ticker/' + c.ticker),
    });
    tr.appendChild(el('td', {},
      el('span', { class: 'status-pill status-' + c.status }, c.status)));
    tr.appendChild(el('td', { class: 'mono brass' }, c.ticker || '—'));
    tr.appendChild(el('td', {}, c.issuer_name));
    tr.appendChild(el('td', { class: 'num mut' }, fmtNum(c.prev_shares)));
    tr.appendChild(el('td', { class: 'num' }, fmtNum(c.curr_shares)));
    const v = c.value_change_usd;
    const cls = v > 0 ? 'num green' : v < 0 ? 'num red' : 'num';
    tr.appendChild(el('td', { class: cls }, fmtUSD(v, { sign: true })));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

// ---- Pie Chart helper ----
  async function renderPieChart(container, data, labels, options = {}) {
    await ensureChartJS();
    const canvas = el('canvas', { width: 300, height: 300 });
    container.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: [
            '#C9A24E', '#2E9E6B', '#C7564A', '#3B82F6', '#8B5CF6',
            '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#6366F1',
          ],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            position: 'right',
            labels: {
              color: '#E8EBEF',
              font: { size: 11, family: 'var(--font)' },
              padding: 12,
              usePointStyle: true,
              pointStyle: 'circle',
            },
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const pct = ((context.raw / total) * 100).toFixed(1);
                return `${context.label}: ${pct}% (${fmtUSD(context.raw, {compact: true})})`;
              },
            },
          },
        },
      },
    });
  }

  // ---- Ticker view ----
function renderTicker() {
  const t = state.ticker;
  if (!t) return el('div', { class: 'empty' }, 'Loading…');
  if (!t.found) {
    return el('div', { class: 'section' },
      el('a', { class: 'back', href: '#/', onclick: (e) => { e.preventDefault(); setHash('#/'); } },
        '← Funds'),
      el('div', { class: 'empty' }, `No holdings found for ticker "${state.ticker?.ticker || ''}"`));
  }
  const wrap = el('div');
  const hero = el('div', { class: 'ticker-hero' });
  hero.appendChild(el('div', { class: 'ticker-symbol' }, t.ticker));
  const meta = el('div', { class: 'ticker-meta' });
  meta.appendChild(el('div', { class: 'issuer' }, t.issuer_name));
  meta.appendChild(el('div', { class: 'stats-line' },
    el('div', {},
      el('span', {}, 'Holders: '),
      el('span', { class: 'v' }, String(t.current_holders))),
    el('div', {},
      el('span', {}, 'Total value: '),
      el('span', { class: 'v' }, fmtUSD(t.total_current_value_usd))),
  ));
  hero.appendChild(meta);
  wrap.appendChild(hero);

  // Short Interest summary section (if available — embedded in API response)
  if (t.latest_si) {
    const si = t.latest_si;
    const siMeta = t.si_meta;
    const changeCls = si.change_pct > 0 ? 'green' : si.change_pct < 0 ? 'red' : '';
    const siSection = el('div', { class: 'section' });
    siSection.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, 'Short Interest'),
      el('a', {
        href: '#/short-interest/' + t.ticker,
        onclick: (e) => { e.preventDefault(); setHash('#/short-interest/' + t.ticker); },
        class: 'hint',
      }, 'Latest settlement: ' + fmtDateISO(si.settlement_date) + ' · View full history →'),
    ));
    const siTableWrap = el('div', { class: 'table-wrap' });
    const siTable = el('table');
    const siThead = el('thead');
    const siTrh = el('tr');
    ['Metric', 'Value'].forEach((h) => {
      siTrh.appendChild(el('th', { class: h === 'Value' ? 'num' : '' }, h));
    });
    siThead.appendChild(siTrh);
    siTable.appendChild(siThead);
    const siTbody = el('tbody');
    const siRows = [
      ['Short $', fmtUSD(si.current_short), ''],
      ['% Change', fmtPct(si.change_pct), changeCls],
      ['Days to Cover', si.days_to_cover?.toFixed(1) || '—', ''],
      ['Avg Daily Vol', fmtNum(si.avg_daily_volume), ''],
      ['Peak Short $', siMeta && siMeta.peak_short ? fmtUSD(siMeta.peak_short) : '—', ''],
    ];
    for (const [label, val, cls] of siRows) {
      const tr = el('tr');
      tr.appendChild(el('td', {}, label));
      tr.appendChild(el('td', { class: 'num ' + cls }, val));
      siTbody.appendChild(tr);
    }
    siTable.appendChild(siTbody);
    siTableWrap.appendChild(siTable);
    siSection.appendChild(siTableWrap);
    wrap.appendChild(siSection);
  }

  // Cross-fund holders table
  const section = el('div', { class: 'section' });
    section.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, `Current holders · ${t.current_holders}`),
      el('div', { class: 'hint' }, t.history?.[0]?.report_period || ''),
    ));

    // Chart + Table container
    const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });

    // Chart canvas
    const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
    chartWrap.appendChild(el('canvas', { id: 'ticker-holders-chart' }));
    chartTableWrap.appendChild(chartWrap);

    // Table
    const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: '400px' } });
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
  ['Strategy', 'Fund', 'Shares', 'Value', 'Status', 'Δ Sh'].forEach((h, i) => {
    const cls = (i >= 2 && i <= 5) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const h of t.holders || []) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/fund/' + h.cik),
    });
    tr.appendChild(el('td', {},
      el('span', { class: 'strategy-tag' }, h.strategy || '—')));
    tr.appendChild(el('td', { class: 'brass' }, h.name));
    tr.appendChild(el('td', { class: 'num' }, fmtNum(h.shares)));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(h.market_value_usd)));
    tr.appendChild(el('td', {},
      h.status ? el('span', { class: 'status-pill status-' + h.status }, h.status)
               : el('span', { class: 'mut' }, '—')));
    const dsh = h.share_change;
    const cls = dsh > 0 ? 'num green' : dsh < 0 ? 'num red' : 'num mut';
    tr.appendChild(el('td', { class: cls },
      dsh !== null && dsh !== undefined
        ? (dsh > 0 ? '+' : '') + dsh.toLocaleString()
        : '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  section.appendChild(tableWrap);
  wrap.appendChild(section);

  // History section
  if (t.history && t.history.length > 1) {
    const histSec = el('div', { class: 'section' });
    histSec.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, `Quarterly history`)));
    const tableWrap2 = el('div', { class: 'table-wrap' });
    const table2 = el('table');
    const thead2 = el('thead');
    const trh2 = el('tr');
    ['Quarter', 'Holders', 'Total Value', 'Total Shares'].forEach((h, i) => {
      const cls = i >= 1 ? 'num' : '';
      trh2.appendChild(el('th', { class: cls }, h));
    });
    thead2.appendChild(trh2);
    table2.appendChild(thead2);
    const tbody2 = el('tbody');
    for (const r of [...t.history].reverse()) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'mono' }, r.report_period));
      tr.appendChild(el('td', { class: 'num' }, r.holders));
      tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.total_value_usd)));
      tr.appendChild(el('td', { class: 'num' }, fmtNum(r.total_shares)));
      tbody2.appendChild(tr);
    }
    table2.appendChild(tbody2);
    tableWrap2.appendChild(table2);
    histSec.appendChild(tableWrap2);
    wrap.appendChild(histSec);
  }

  // Create chart after DOM is ready
  setTimeout(() => createTickerHoldersChart(t.holders), 0);

  return wrap;
}

// ---- Consensus view ----
function renderConsensusView() {
  const wrap = el('div', { class: 'section' });
  const c = state.consensus;
  const filters = el('div', { class: 'filters' });
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Min funds:'),
    ...[1, 2, 3, 5, 8, 12].map(n =>
      el('button', {
        class: state.consensus.min_funds === n ? 'active' : '',
        onclick: async () => {
          state.consensus.min_funds = n;
          state.loading = true; render();
          state.consensus = await api('/api/consensus', { min_funds: n });
          state.loading = false; render();
        },
      }, String(n))
    )));
  wrap.appendChild(filters);
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, `Cross-fund momentum · ${c.quarter}`),
    el('div', { class: 'hint' }, `${(c.buys.length + c.sells.length)} tickers with cross-fund moves`),
  ));

  // Chart + Table container for buys
  const buysChartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
  buysChartWrap.appendChild(el('canvas', { id: 'consensus-buys-chart' }));

  // Chart + Table container for sells
  const sellsChartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
  sellsChartWrap.appendChild(el('canvas', { id: 'consensus-sells-chart' }));

  const chartsWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', marginBottom: '24px' } });
  chartsWrap.appendChild(buysChartWrap);
  chartsWrap.appendChild(sellsChartWrap);
  wrap.appendChild(chartsWrap);

  const grid = el('div', { class: 'consensus-grid' });
  grid.appendChild(renderConsensusColumn('Buys (net adds)', c.buys, true));
  grid.appendChild(renderConsensusColumn('Sells (net drops)', c.sells, false));
  wrap.appendChild(grid);

  // Create charts after DOM is ready
  setTimeout(() => createConsensusCharts(c.buys, c.sells), 0);

  return wrap;
}

function renderConsensusColumn(title, rows, isBuy) {
  const col = el('div', { class: 'consensus-col ' + (isBuy ? 'buys' : 'sells') });
  col.appendChild(el('h3', {},
    el('span', { class: 'dot' }), ` ${title} `,
    el('span', { class: 'hint', style: { color: 'var(--text-mut)' } }, `${rows.length}`),
  ));
  if (rows.length === 0) {
    col.appendChild(el('div', { class: 'empty' }, 'No data.'));
    return col;
  }
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Net Δ$', '#New', '#Inc', '#Dec', '#Cls'].forEach((h, i) => {
    const cls = (i >= 1) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/ticker/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    const v = r.net_change_usd;
    const cls = v > 0 ? 'num green' : 'num red';
    tr.appendChild(el('td', { class: cls }, fmtUSD(v, { sign: true })));
    tr.appendChild(el('td', { class: 'num mut' }, r.funds_new || 0));
    tr.appendChild(el('td', { class: 'num mut' }, r.funds_increased || 0));
    tr.appendChild(el('td', { class: 'num mut' }, r.funds_decreased || 0));
      tr.appendChild(el('td', { class: 'num mut' }, r.funds_closed || 0));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    col.appendChild(tableWrap);
    return col;
    }

    function renderSectors() {
      const s = state.sectors;
      const periods = state.sectorPeriods || {};
      const periodLabel = periods.prev_q && periods.curr_q
        ? `${periods.prev_q} → ${periods.curr_q}`
        : (periods.curr_q ? periods.curr_q : 'sectors');

      if (!s || !s.length) {
        return el('div', { class: 'section' },
          el('div', { class: 'section-header' },
            el('h2', {}, 'Sector Rotation'),
            el('div', { class: 'hint' }, `Period: ${periodLabel}`),
          ),
          el('div', { class: 'empty' }, 'No sector data available for these periods. Sector classifications are still being populated across the full ticker universe.'),
        );
      }

      const wrap = el('div', { class: 'section' });
      wrap.appendChild(el('div', { class: 'section-header' },
        el('h2', {}, 'Sector Rotation'),
        el('div', { class: 'hint' }, `Period: ${periodLabel} · ${s.length} sectors with holdings in either quarter`),
      ));

      // Chart + Table container
      const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });

      // Bar chart canvas
      const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
      chartWrap.appendChild(el('canvas', { id: 'sectors-chart' }));
      chartTableWrap.appendChild(chartWrap);

      // Table
      const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: '400px' } });
      const table = el('table');
      const thead = el('thead');
      const trh = el('tr');
      ['Sector', 'Prev', 'Current', 'Δ$', 'Δ%', 'Holder Δ', 'Pos Δ'].forEach((h, i) => {
        const cls = i >= 1 ? 'num' : '';
        trh.appendChild(el('th', { class: cls }, h));
      });
      thead.appendChild(trh);
      table.appendChild(thead);

      const tbody = el('tbody');
      for (const r of s) {
        const tr = el('tr');
        tr.appendChild(el('td', {}, r.sector));
        tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.prev_value_usd)));
        tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.curr_value_usd)));
        const delta = r.value_change_usd;
        const deltaCls = delta > 0 ? 'num green' : (delta < 0 ? 'num red' : 'num');
        tr.appendChild(el('td', { class: deltaCls }, fmtUSD(delta, { sign: true })));
        const pct = r.prev_value_usd && r.prev_value_usd > 0
          ? ((delta / r.prev_value_usd) * 100)
          : (r.curr_value_usd > 0 ? Infinity : 0);
        tr.appendChild(el('td', { class: pct > 0 ? 'num green' : (pct < 0 ? 'num red' : 'num') },
          pct === Infinity ? 'new' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`));
        const hDelta = r.holder_change;
        tr.appendChild(el('td', { class: hDelta > 0 ? 'num green' : (hDelta < 0 ? 'num red' : 'num') },
          hDelta > 0 ? `+${hDelta}` : (hDelta < 0 ? `${hDelta}` : '—')));
        const pDelta = r.position_change;
        tr.appendChild(el('td', { class: pDelta > 0 ? 'num green' : (pDelta < 0 ? 'num red' : 'num') },
          pDelta > 0 ? `+${pDelta}` : (pDelta < 0 ? `${pDelta}` : '—')));
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      chartTableWrap.appendChild(tableWrap);
      wrap.appendChild(chartTableWrap);

      // Bar chart of percentage value change per sector
      setTimeout(() => {
        const labels = s.map(r => r.sector);
        const pctData = s.map(r => {
          if (r.prev_value_usd && r.prev_value_usd > 0) {
            return ((r.value_change_usd / r.prev_value_usd) * 100);
          }
          return r.curr_value_usd > 0 ? Infinity : 0;
        });
        const absData = s.map(r => r.value_change_usd);
        const colors = pctData.map(d => d > 0 ? CHART_COLORS.green : (d < 0 ? CHART_COLORS.red : CHART_COLORS.brass));
        createBarChart('sectors-chart', {
          labels: labels,
          datasets: [{
            label: 'Net change (%)',
            data: pctData,
            backgroundColor: colors,
            borderColor: colors.map(c => c),
            borderWidth: 1,
          }],
        }, {
          indexAxis: 'y',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const idx = ctx.dataIndex;
                  return `Δ: ${pctData[idx] > 0 ? '+' : ''}${pctData[idx].toFixed(1)}% (${fmtUSD(absData[idx], { sign: true })})`;
                },
              },
            },
          },
          scales: {
            x: {
              ticks: {
                color: '#E8EBEF',
                font: { size: 10 },
                callback: (v) => v === Infinity ? 'new' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`,
              },
              grid: { color: '#1E2A38' },
            },
            y: {
              ticks: { color: '#E8EBEF', font: { size: 10 } },
              grid: { display: false },
            },
          },
        });
      }, 0);

      return wrap;
    }


// ---- Market Snapshot view ----
function renderSnapshot() {
  if (!state.snapshot) return el('div', { class: 'empty' }, 'Loading…');

  const s = state.snapshot;
  if (!s.date_str) {
    return el('div', { class: 'section' },
      el('div', { class: 'section-header' },
        el('h2', {}, 'Market Snapshot'),
      ),
      el('div', { class: 'empty' }, 'No snapshot available yet. Run the macro pipeline to generate one.'),
    );
  }

  const wrap = el('div', { class: 'section' });

  // Date label — handle both YYYYMMDD format and "latest" / other strings
  let dateLabel = '';
  if (s.date_str) {
    if (/^\d{8}$/.test(s.date_str)) {
      dateLabel = `${s.date_str.slice(4, 6)}/${s.date_str.slice(6, 8)}/${s.date_str.slice(0, 4)}`;
    } else {
      // e.g. "latest" — try the timestamp field as fallback
      const ts = s.timestamp || '';
      dateLabel = ts.slice(0, 10).replace(/(\d{4})-(\d{2})-(\d{2})/, '$2/$3/$1') || s.date_str;
    }
  }

  // Header
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Market Snapshot'),
    dateLabel ? el('div', { class: 'hint brass' }, dateLabel) : el('div', { class: 'hint' }, 'No date available'),
  ));

  // Headline / caption
  if (s.caption) {
    wrap.appendChild(el('div', { class: 'snapshot-caption' }, s.caption));
  }

  // What's driving the markets — top 3 movers with driver narratives (moved above the PNG)
  if (s.top_movers && s.top_movers.length > 0) {
    const mv = el('div', { class: 'snapshot-movers' });
    mv.appendChild(el('h3', {}, 'What\u2019s driving the markets'));
    const ul = el('ul');
    for (const m of s.top_movers) {
      const color = m.pct_change > 0 ? 'green' : m.pct_change < 0 ? 'red' : 'dim';
      const sign = m.pct_change > 0 ? '+' : '';
      ul.appendChild(el('li', {},
        el('span', { class: 'mono ' + color }, sign + m.pct_change.toFixed(2) + '%'),
        el('span', { class: 'mover-name' }, m.name),
        el('span', { class: 'mover-driver' }, m.driver),
      ));
    }
    mv.appendChild(ul);
    wrap.appendChild(mv);
  }

  // Hero: snapshot image
  const imgUrl = API + '/snapshots/' + s.png_filename;
  const hero = el('div', { class: 'snapshot-hero' });
  const img = el('img', {
    src: imgUrl,
    alt: 'Market Snapshot ' + dateLabel,
    style: { maxWidth: '100%', height: 'auto', borderRadius: '6px', border: '1px solid var(--line)' },
  });
  img.onerror = () => {
    img.src = '';
    img.style.minHeight = '200px';
    img.style.display = 'flex';
    img.style.alignItems = 'center';
    img.style.justifyContent = 'center';
    img.style.color = 'var(--text-dim)';
    img.textContent = 'Snapshot image not yet available';
  };
  hero.appendChild(img);
  wrap.appendChild(hero);

  return wrap;
}

// ---------------- Economic Calendar view ----------------
function renderEconomicCalendar() {
  const wrap = el('div', { class: 'section' });

  // Stats row
  const m = state.econMeta;
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Upcoming', m ? m.upcoming_count : '—'));
  stats.appendChild(stat('Categories', m && m.categories ? m.categories.length : '—'));
  const lastUpd = m && m.last_update
    ? `${String(m.last_update).slice(5, 7)}/${String(m.last_update).slice(8, 10)}/${String(m.last_update).slice(0, 4)}`
    : '—';
  stats.appendChild(stat('Last Updated', lastUpd, 'brass'));
  wrap.appendChild(stats);

  // Filters
  const filters = el('div', { class: 'filters' });
  // Impact filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Impact:'),
    ...['', 'high', 'medium', 'low'].map(imp =>
      el('button', {
        class: state.econImpact === imp ? 'active' : '',
        onclick: async () => {
          state.econImpact = imp;
          state.loading = true; render();
          const resp = await api('/api/econ/events', {
            days_ahead: state.econDaysAhead,
            impact: state.econImpact || undefined,
            category: state.econCategory || undefined,
          });
          state.econEvents = resp.events || resp;
          state.loading = false; render();
        },
      }, imp ? imp.charAt(0).toUpperCase() + imp.slice(1) : 'ALL')
    )
  ));
  // Days ahead filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Days:'),
    ...[14, 30, 60, 90].map(d =>
      el('button', {
        class: state.econDaysAhead === d ? 'active' : '',
        onclick: async () => {
          state.econDaysAhead = d;
          state.loading = true; render();
          const resp = await api('/api/econ/events', {
            days_ahead: d,
            impact: state.econImpact || undefined,
            category: state.econCategory || undefined,
          });
          state.econEvents = resp.events || resp;
          state.loading = false; render();
        },
      }, String(d))
    )
  ));
  wrap.appendChild(filters);

  // Table
  const tableWrap = el('div', { class: 'table-wrap' });
  const events = state.econEvents || [];
  if (!events.length) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No economic events match your filters.'));
    wrap.appendChild(tableWrap);
    return wrap;
  }

  // Group by date
  const byDate = {};
  for (const e of events) {
    const d = e.event_date;
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(e);
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Time', 'Event', 'Category', 'Impact', 'Forecast', 'Prior'].forEach((h, i) => {
    let cls = '';
    if (h === 'Date' || h === 'Time') cls = 'mono';
    if (['Impact', 'Forecast', 'Prior'].includes(h)) cls = 'num';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const [dateStr, dayEvents] of Object.entries(byDate)) {
    for (const e of dayEvents) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'mono' }, fmtDateISO(e.event_date)));
      tr.appendChild(el('td', { class: 'mono mut' }, e.event_time || '—'));
      tr.appendChild(el('td', {}, e.event_name));
      tr.appendChild(el('td', { class: 'mono mut' }, e.category || '—'));
      const impactCls = e.impact === 'high' ? 'num red'
        : e.impact === 'medium' ? 'num amber' : 'num mut';
      tr.appendChild(el('td', { class: impactCls }, e.impact || '—'));
      tr.appendChild(el('td', { class: 'num' }, e.forecast || '—'));
      tr.appendChild(el('td', { class: 'num mut' }, e.prior || '—'));
      tbody.appendChild(tr);
    }
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

// ---------------- Short Interest view ----------------
function renderShortInterest() {
  const wrap = el('div', { class: 'section' });

  // Stats row
  const m = state.siMeta;
  const settlement = m ? m.latest_settlement : '';
  const settlementFmt = settlement
    ? `${String(settlement).slice(5, 7)}/${String(settlement).slice(8, 10)}/${String(settlement).slice(0, 4)}`
    : '—';

  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Settlement', settlementFmt));
  stats.appendChild(stat('Total Short', m ? fmtUSD(m.total_short_interest) : '—', 'brass'));
  stats.appendChild(stat('Tracked Tickers', m ? m.ticker_count : '—'));
  const signalCounts = state.siSignals
    ? Object.fromEntries(Object.entries(state.siSignals).filter(([k]) => k !== 'latest_settlement').map(([k, v]) => [k, (v || []).length]))
    : {};
  stats.appendChild(stat('Signal Count', Object.values(signalCounts).reduce((a, n) => a + n, 0) || '—'));
  wrap.appendChild(stats);

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabLabels = [
    { key: 'latest', label: 'Latest Snapshot' },
    { key: 'signals', label: 'Signals' },
    { key: 'history', label: state.siTicker ? 'History' : 'Watchlist' },
  ];
  for (const t of tabLabels) {
    // In ticker drill-down mode, hide the first two tabs
    if (state.siTicker && t.key !== 'history') continue;
    tabs.appendChild(el('div', {
      class: 'tab' + (state.siActiveTab === t.key ? ' active' : ''),
      onclick: () => {
        if (state.siTicker && t.key !== 'history') return;
        state.siActiveTab = t.key;
        render();
        if (t.key === 'latest' || t.key === 'signals') {
          api('/api/si/latest', { min_short: state.siLatest.min_short, limit: state.siLatest.limit })
            .then(res => {
              state.siLatest.rows = res.rows || res;
              state.siLatest.total = state.siLatest.rows.length;
              render();
            });
        }
      },
    }, t.label));
  }
  wrap.appendChild(tabs);

  // Tab bodies
  if (state.siActiveTab === 'latest' && !state.siTicker) {
    wrap.appendChild(renderSILatestTable());
  } else if (state.siActiveTab === 'signals' && !state.siTicker) {
    wrap.appendChild(renderSISignals());
  } else if (state.siActiveTab === 'history' && state.siTicker) {
    wrap.appendChild(renderSITicker());
  } else if (state.siActiveTab === 'history' && !state.siTicker) {
    // "Watchlist" tab shows the same table as "Latest" but sorted by current_short
    wrap.appendChild(renderSILatestTable());
  }

  return wrap;
}

function renderSILatestTable() {
  const rows = state.siLatest?.rows || state.siLatest || [];
  const dataRows = Array.isArray(rows) ? rows : [];
  const tableWrap = el('div', { class: 'table-wrap' });

  // Min short filter (inline)
  const filterRow = el('div', { class: 'filters' });
  filterRow.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Min $:'),
    el('input', {
      type: 'text', placeholder: '1M', value: '',
      onkeydown: async (e) => {
        if (e.key === 'Enter') {
          const v = e.target.value.trim();
          const n = v.endsWith('B') ? parseFloat(v) * 1e9
                  : v.endsWith('M') ? parseFloat(v) * 1e6
                  : parseFloat(v);
          state.siLatest.min_short = isNaN(n) ? 1_000_000 : n;
          state.loading = true; render();
          const resp = await api('/api/si/latest', { min_short: state.siLatest.min_short, limit: state.siLatest.limit });
          state.siLatest.rows = resp.rows || resp;
          state.siLatest.total = state.siLatest.rows.length;
          state.loading = false; render();
        }
      }
    })));
  tableWrap.appendChild(filterRow);

  if (!dataRows.length) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No short interest data for this settlement date.'));
    return tableWrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Name', 'Short $', '% Free Float', '%Δ', 'DTC', 'Avg Vol'].forEach((h, i) => {
    const cls = i >= 2 ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of dataRows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/short-interest/' + r.symbol),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.symbol));
    tr.appendChild(el('td', {}, r.name || '—'));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.current_short)));
    tr.appendChild(el('td', { class: 'num mut' }, fmtFreeFloat(r)));
    const shortCls = r.change_pct > 0 ? 'num green' : r.change_pct < 0 ? 'num red' : 'num';
    tr.appendChild(el('td', { class: shortCls }, fmtPct(r.change_pct)));
    tr.appendChild(el('td', { class: 'num mut' }, r.days_to_cover?.toFixed(1) || '—'));
    tr.appendChild(el('td', { class: 'num mut' }, fmtNum(r.avg_daily_volume)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}

function renderSISignals() {
  const s = state.siSignals;
  const wrap = el('div');

  if (!s || s.latest_settlement == null) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No signal data available.'));
    return wrap;
  }

  const settlementFmt = String(s.latest_settlement).slice(5, 7) + '/' +
    String(s.latest_settlement).slice(8, 10) + '/' + String(s.latest_settlement).slice(0, 4);

  const signalSets = [
    { key: 'spikes', label: 'Spikes (≥50% change)', cols: ['Ticker', 'Name', 'Short $', '% Free Float', '%Δ', 'DTC'] },
    { key: 'high_dtc', label: 'High DTC (≥10 days)', cols: ['Ticker', 'Name', 'Short $', '% Free Float', 'DTC', '%Δ'] },
    { key: 'largest', label: 'Largest Positions', cols: ['Ticker', 'Name', 'Short $', '% Free Float', 'DTC', '%Δ'] },
    { key: 'covering', label: 'Covering (≤-30%)', cols: ['Ticker', 'Name', 'Short $', '% Free Float', '%Δ', 'DTC'] },
    { key: 'new_shorts', label: 'New Shorts (≥5x)', cols: ['Ticker', 'Name', 'Short $', '% Free Float', '%Δ', 'DTC'] },
  ];

  for (const ss of signalSets) {
    const rows = s[ss.key] || [];
    wrap.appendChild(el('div', { class: 'section' }));
    wrap.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, `${ss.label} (${rows.length})` ),
      el('div', { class: 'hint' }, `Settlement: ${settlementFmt}`)
    ));

    const tableWrap = el('div', { class: 'table-wrap' });
    if (!rows.length) {
      tableWrap.appendChild(el('div', { class: 'empty' }, 'No tickers match this signal.'));
      wrap.appendChild(tableWrap);
      continue;
    }
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ss.cols.forEach((h, i) => {
      trh.appendChild(el('th', { class: i >= 2 ? 'num' : '' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const r of rows) {
      const tr = el('tr', {
        style: { cursor: 'pointer' },
        onclick: () => setHash('#/short-interest/' + r.symbol),
      });
      tr.appendChild(el('td', { class: 'mono brass' }, r.symbol));
      tr.appendChild(el('td', {}, r.name || '—'));
      tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.current_short)));
      // % Free Float column (always after Short $ in signal tables)
      tr.appendChild(el('td', { class: 'num mut' }, fmtFreeFloat(r)));
      // Put %Δ or DTC depending on column order
      ss.cols.slice(4).forEach((col, ci) => {
        if (col === '%Δ') {
          const cls = r.change_pct > 0 ? 'num green' : r.change_pct < 0 ? 'num red' : 'num';
          tr.appendChild(el('td', { class: cls }, fmtPct(r.change_pct)));
        } else if (col === 'DTC') {
          tr.appendChild(el('td', { class: 'num mut' }, r.days_to_cover?.toFixed(1) || '—'));
        } else {
          tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.current_short)));
        }
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);
  }

  return wrap;
}

function renderSITicker() {
  const t = state.siTicker;
  if (!t) return el('div', { class: 'empty' }, 'Loading…');
  if (!t.history || !t.history.length) {
    return el('div', { class: 'section' },
      el('div', { class: 'section-header' },
        el('h2', {}, 'Short Interest History'),
      ),
      el('div', { class: 'empty' }, `No short interest data for "${t.symbol || ''}"`),
    );
  }

  const wrap = el('div');

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/short-interest',
    onclick: (e) => { e.preventDefault(); setHash('#/short-interest'); },
  }, '← Short Interest'));
  header.appendChild(el('h2', {}, t.symbol));
  header.appendChild(el('div', { class: 'strategy-tag' }, t.category || '—'));
  const metaGrid = el('div', { class: 'meta-grid' });
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Name'),
    el('span', { class: 'meta-value' }, t.name)));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Exchange'),
    el('span', { class: 'meta-value' }, t.exchange || '—')));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Industry'),
    el('span', { class: 'meta-value' }, t.industry || '—')));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, '% Free Float'),
    el('span', { class: 'meta-value brass' }, t.pct_free_float !== null && t.pct_free_float !== undefined ? t.pct_free_float.toFixed(2) + '%' : '—')));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Latest'),
    el('span', { class: 'meta-value mono' },
      t.history[0].settlement_date ? String(t.history[0].settlement_date).slice(5, 7) + '/' +
        String(t.history[0].settlement_date).slice(8, 10) + '/' + String(t.history[0].settlement_date).slice(0, 4)
        : '—')));
  header.appendChild(metaGrid);
  wrap.appendChild(header);

  // History table
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Short $', 'Prev Short', '%Δ', 'DTC', 'Avg Vol', 'Split?', 'Revision?'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i >= 1 ? 'num' : '' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of t.history) {
    const tr = el('tr');
    const dateStr = String(r.settlement_date).slice(5, 7) + '/' +
      String(r.settlement_date).slice(8, 10) + '/' + String(r.settlement_date).slice(0, 4);
    tr.appendChild(el('td', { class: 'mono' }, dateStr));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.current_short)));
    tr.appendChild(el('td', { class: 'num mut' }, r.previous_short ? fmtUSD(r.previous_short) : '—'));
    const cls = r.change_pct > 0 ? 'num green' : r.change_pct < 0 ? 'num red' : 'num';
    tr.appendChild(el('td', { class: cls }, fmtPct(r.change_pct)));
    tr.appendChild(el('td', { class: 'num mut' }, r.days_to_cover?.toFixed(1) || '—'));
    tr.appendChild(el('td', { class: 'num mut' }, fmtNum(r.avg_daily_volume)));
    tr.appendChild(el('td', { class: 'num mut' }, r.stock_split_flag ? 'Yes' : 'No'));
    tr.appendChild(el('td', { class: 'num mut' }, r.revision_flag ? 'Yes' : 'No'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

// ===================== Insider Trading render =====================

function fmtDateYMD(s) {
  return s ? String(s).slice(0, 4) + '-' + String(s).slice(5, 7) + '-' + String(s).slice(8, 10) : '—';
}

function renderInsider() {
  const wrap = el('div', { class: 'section' });

  // Stats row
  const m = state.insiderMeta;
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Last Updated', m ? fmtDateYMD(m.last_updated) : '—'));
  stats.appendChild(stat('Total Records', m ? fmtNum(m.total_records) : '—'));
  stats.appendChild(stat('Tracked Tickers', m ? m.ticker_count : '—'));
  stats.appendChild(stat('Latest Filing', m ? fmtDateYMD(m.latest_filing_date) : '—'));
  wrap.appendChild(stats);

  // Tabs (only when not in ticker detail mode)
  if (!state.insiderTicker) {
    const tabs = el('div', { class: 'tabs' });
    const tabLabels = [
      { key: 'latest', label: 'Latest Trades' },
      { key: 'signals', label: 'Top Signals' },
    ];
    for (const t of tabLabels) {
      tabs.appendChild(el('div', {
        class: 'tab' + (state.insiderActiveTab === t.key ? ' active' : ''),
        onclick: () => {
          if (state.insiderActiveTab === t.key) return;
          state.insiderActiveTab = t.key;
          render();
          if (state.insiderActiveTab === 'signals' && !state.insiderSignals) {
            api('/api/insider/signals', { limit: 100 })
              .then(resp => { state.insiderSignals = resp; })
              .catch(e => { state.error = e.message; })
              .finally(() => { render(); });
          }
        },
      }, t.label));
    }
    wrap.appendChild(tabs);
  }

  // Tab bodies
  if (state.insiderActiveTab === 'latest' && !state.insiderTicker) {
    wrap.appendChild(renderInsiderLatestTable());
  } else if (state.insiderActiveTab === 'signals' && !state.insiderTicker) {
    wrap.appendChild(renderInsiderSignals());
  } else if (state.insiderTicker) {
    wrap.appendChild(renderInsiderTicker());
  }

  return wrap;
}

function renderInsiderLatestTable() {
  const rows = state.insiderLatest?.rows || [];
  const tableWrap = el('div', { class: 'table-wrap' });

  // Filters
  const filterRow = el('div', { class: 'filters' });
  filterRow.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Min $:'),
    el('input', {
      type: 'text', placeholder: '1M', value: state.insiderLatest.min_value || '',
      onkeydown: async (e) => {
        if (e.key === 'Enter') {
          state.insiderLatest.min_value = e.target.value.trim();
          const v = state.insiderLatest.min_value || '';
          let n;
          if (v.endsWith('B')) n = parseFloat(v) * 1e9;
          else if (v.endsWith('M')) n = parseFloat(v) * 1e6;
          else n = parseFloat(v);
          state.insiderLatest.min_value = isNaN(n) ? 0 : n;
          const resp = await api('/api/insider/latest', {
            min_value: state.insiderLatest.min_value || undefined,
            limit: state.insiderLatest.limit,
          });
          state.insiderLatest.rows = resp.rows || resp;
          state.insiderLatest.total = state.insiderLatest.rows.length;
          render();
        }
      }
    })));
  tableWrap.appendChild(filterRow);

  if (!rows.length) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No insider trades found.'));
    return tableWrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Trade Date', 'Insider', 'Relationship', 'Type', 'Qty', 'Price $', 'Value $', 'Ownership'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 5 || i === 6 || i === 7 ? 'num' : '' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/insider/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', { class: 'mono' }, fmtDateYMD(r.trade_date)));
    tr.appendChild(el('td', {}, r.insider_name || '—'));
    tr.appendChild(el('td', {}, r.relationship || '—'));
    const isBuy = r.is_buy || r.transaction_type === 'P' || r.transaction_type === 'A' || r.transaction_type === 'M';
    const isSell = r.transaction_type === 'S' || !isBuy;
    const typeCls = isSell ? 'num red' : isBuy ? 'num green' : 'num';
    const typeLabel = r.transaction_type === 'P' ? 'Buy' : r.transaction_type === 'S' ? 'Sale' : r.transaction_type;
    tr.appendChild(el('td', { class: typeCls }, typeLabel));
    tr.appendChild(el('td', { class: 'num' }, fmtNum(r.quantity)));
    tr.appendChild(el('td', { class: 'num mut' }, r.price ? r.price.toFixed(2) : '—'));
    const valCls = isSell ? 'num red' : isBuy ? 'num green' : 'num';
    tr.appendChild(el('td', { class: valCls }, r.value ? fmtUSD(r.value) : '—'));
    tr.appendChild(el('td', {}, r.ownership_type || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);

  return tableWrap;
}

function renderInsiderSignals() {
  const s = state.insiderSignals;
  const wrap = el('div');

  if (!s) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No signal data available.'));
    return wrap;
  }

  const signalSets = [
    { key: 'top_buys', label: 'Largest Buys', cols: ['Ticker', 'Insider', 'Date', 'Value $', 'Type'] },
    { key: 'top_sells', label: 'Largest Sales', cols: ['Ticker', 'Insider', 'Date', 'Value $', 'Type'] },
    { key: 'officer_buys', label: 'Officer/CEO/CFO Buys', cols: ['Ticker', 'Insider', 'Date', 'Value $', 'Relationship'] },
    { key: 'recent_activity', label: 'Most Active', cols: ['Ticker', 'Insider', 'Date', 'Value $', 'Type'] },
  ];

  for (const ss of signalSets) {
    const signalRows = s[ss.key] || [];
    wrap.appendChild(el('div', { class: 'section' }));
    wrap.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, `${ss.label} (${signalRows.length})`),
    ));

    const tableWrap = el('div', { class: 'table-wrap' });
    if (!signalRows.length) {
      tableWrap.appendChild(el('div', { class: 'empty' }, 'No tickers match this signal.'));
      wrap.appendChild(tableWrap);
      continue;
    }

    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ss.cols.forEach((h, i) => {
      trh.appendChild(el('th', { class: i >= 3 ? 'num' : '' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = el('tbody');
    for (const r of signalRows) {
      const tr = el('tr', {
        style: { cursor: 'pointer' },
        onclick: () => setHash('#/insider/' + r.ticker),
      });
      tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
      tr.appendChild(el('td', {}, r.insider_name || r.insider || '—'));
      tr.appendChild(el('td', { class: 'mono' }, fmtDateYMD(r.trade_date || r.date)));
      const valCls = (r.is_buy === false || r.transaction_type === 'S' || ss.key === 'top_sells') ? 'num red' : 'num green';
      tr.appendChild(el('td', { class: valCls }, r.value ? fmtUSD(r.value) : '—'));
      // Last column varies by signal set
      if (ss.key === 'officer_buys') {
        tr.appendChild(el('td', {}, r.relationship || '—'));
      } else {
        const typeCls = (r.is_buy === false || r.transaction_type === 'S') ? 'num red' : (r.is_buy === true || r.transaction_type === 'P') ? 'num green' : 'num';
        tr.appendChild(el('td', { class: typeCls }, r.transaction_type === 'P' ? 'Buy' : r.transaction_type === 'S' ? 'Sale' : (r.transaction_type || '—')));
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);
  }

  return wrap;
}

function renderInsiderTicker() {
  const t = state.insiderTicker;
  if (!t) return el('div', { class: 'empty' }, 'Loading…');

  const wrap = el('div');

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/insider',
    onclick: (e) => { e.preventDefault(); setHash('#/insider'); },
  }, '← Insider Trading'));
  header.appendChild(el('h2', {}, t.ticker || t.symbol || ''));

  const metaGrid = el('div', { class: 'meta-grid' });
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Name'),
    el('span', { class: 'meta-value' }, t.name || t.company_name || '—')));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Total Trades'),
    el('span', { class: 'meta-value' }, fmtNum(t.trade_count || t.total_transactions || 0))));
  metaGrid.appendChild(el('div', {},
    el('span', { class: 'meta-label' }, 'Last Trade'),
    el('span', { class: 'meta-value mono' },
      t.last_trade_date && typeof t.last_trade_date === 'object'
        ? fmtDateYMD(t.last_trade_date.filing_date)
        : fmtDateYMD(t.last_trade_date))));
  header.appendChild(metaGrid);
  wrap.appendChild(header);

  if (!t.trades || !t.trades.length) {
    wrap.appendChild(el('div', { class: 'empty' }, `No insider trading data for "${t.ticker || t.symbol || ''}".`));
    return wrap;
  }

  // Trades table
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Trade Date', 'Insider', 'Relationship', 'Type', 'Qty', 'Price $', 'Value $', 'Ownership'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 4 || i === 5 || i === 6 ? 'num' : '' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of t.trades) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: 'mono' }, fmtDateYMD(r.trade_date)));
    tr.appendChild(el('td', {}, r.insider_name || '—'));
    tr.appendChild(el('td', {}, r.relationship || '—'));
    const isBuy = r.is_buy || r.transaction_type === 'P' || r.transaction_type === 'A' || r.transaction_type === 'M';
    const isSell = r.transaction_type === 'S' || !isBuy;
    const typeCls = isSell ? 'num red' : isBuy ? 'num green' : 'num';
    const typeLabel = r.transaction_type === 'P' ? 'Buy' : r.transaction_type === 'S' ? 'Sale' : r.transaction_type;
    tr.appendChild(el('td', { class: typeCls }, typeLabel));
    tr.appendChild(el('td', { class: 'num' }, fmtNum(r.quantity)));
    tr.appendChild(el('td', { class: 'num mut' }, r.price ? r.price.toFixed(2) : '—'));
    const valCls = isSell ? 'num red' : isBuy ? 'num green' : 'num';
    tr.appendChild(el('td', { class: valCls }, r.value ? fmtUSD(r.value) : '—'));
    tr.appendChild(el('td', {}, r.ownership_type || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}


// ===========================================================================
// Price Momentum
// ===========================================================================

function renderMomentum() {
  const wrap = el('div', { class: 'section' });

  // Stats bar
  const meta = state.momMeta || {};
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Latest Date', meta.latest_signal_date || '—'));
  stats.appendChild(stat('Tickers Tracked', meta.ticker_count || 0));
  stats.appendChild(stat('Bars Stored', meta.bar_count || 0));
  wrap.appendChild(stats);

  // Tab bar
  const TAB_DEFS = [
    { key: 'rankings',     label: 'Top Movers' },
    { key: 'volume-spikes', label: 'Volume Spikes' },
    { key: 'consolidation', label: 'Consolidation' },
    { key: 'gaps',          label: 'Earnings Gaps' },
  ];
  const tabBar = el('div', { class: 'tab-bar' });
  for (const t of TAB_DEFS) {
    const active = state.momActiveTab === t.key ? ' active' : '';
    tabBar.appendChild(el('a', {
      class: 'tab' + active,
      onclick: () => { state.momActiveTab = t.key; setHash(t.key === 'rankings' ? '#/momentum' : '#/momentum/' + t.key); },
    }, t.label));
  }
  wrap.appendChild(tabBar);

  // Tab content
  if (state.momActiveTab === 'rankings') {
    wrap.appendChild(renderMomentumTable('Top Movers', state.momRankings.rows, [
      { label: 'Ticker',     key: 'ticker',     cls: 'mono brass' },
      { label: 'Name',       key: 'name',       cls: '' },
      { label: '24h %',      key: 'pct_change', cls: 'num', fmt: fmtPct, color: true },
      { label: 'SMA 20d',    key: 'sma_20d',    cls: 'num mut', fmt: fmtUSD },
      { label: 'Vol Ratio',  key: 'volume_ratio', cls: 'num', fmt: (v) => v ? v.toFixed(1) + 'x' : '—' },
      { label: 'Spike?',     key: 'is_volume_spike', cls: 'num', fmt: (v) => v ? '⚡' : '' },
    ]));
  } else if (state.momActiveTab === 'volume-spikes') {
    wrap.appendChild(renderMomentumTable('Volume Spikes', state.momVolumeSpikes.rows, [
      { label: 'Ticker',     key: 'ticker',     cls: 'mono brass' },
      { label: 'Name',       key: 'name',       cls: '' },
      { label: '24h %',      key: 'pct_change', cls: 'num', fmt: fmtPct, color: true },
      { label: 'Vol Ratio',  key: 'volume_ratio', cls: 'num', fmt: (v) => v ? v.toFixed(1) + 'x' : '—' },
      { label: 'SMA 20d',    key: 'sma_20d',    cls: 'num mut', fmt: fmtUSD },
    ]));
  } else if (state.momActiveTab === 'consolidation') {
    wrap.appendChild(renderMomentumTable('Consolidation', state.momConsolidation.rows, [
      { label: 'Ticker',     key: 'ticker',     cls: 'mono brass' },
      { label: 'Name',       key: 'name',       cls: '' },
      { label: 'Category',   key: 'category',   cls: '' },
      { label: '20d ROC',    key: 'roc_20d',    cls: 'num', fmt: fmtPct, color: true },
      { label: 'Vol Ratio',  key: 'volume_ratio', cls: 'num', fmt: (v) => v ? v.toFixed(1) + 'x' : '—' },
    ]));
  } else if (state.momActiveTab === 'gaps') {
    wrap.appendChild(renderMomentumTable('Earnings Gaps', state.momGaps.rows, [
      { label: 'Ticker',     key: 'ticker',     cls: 'mono brass' },
      { label: 'Name',       key: 'name',       cls: '' },
      { label: 'Gap %',      key: 'gap_pct',    cls: 'num', fmt: fmtPct, color: true },
      { label: '20d ROC',    key: 'roc_20d',    cls: 'num', fmt: fmtPct, color: true },
      { label: 'SMA 20d',    key: 'sma_20d',    cls: 'num mut', fmt: fmtUSD },
    ]));
  }

  // Ticker history modal/link
  if (state.momTickerHistory) {
    wrap.appendChild(renderMomentumTickerHistory(state.momTickerHistory));
  }

  return wrap;
}

function renderMomentumTable(title, rows, cols) {
  const wrap = el('div', { class: 'table-wrap' });
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No data available yet.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  for (const c of cols) {
    trh.appendChild(el('th', { class: c.cls }, c.label));
  }
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/momentum/' + r.ticker),
    });
    for (const c of cols) {
      let val = r[c.key];
      if (c.fmt) val = c.fmt(val);
      let tdClass = c.cls;
      if (c.color && typeof val === 'string' && val.includes('+')) tdClass += ' green';
      else if (c.color && typeof val === 'string' && val.includes('−') || (val && typeof val === 'string' && val.startsWith('−'))) tdClass += ' red';
      tr.appendChild(el('td', { class: tdClass }, val != null ? val : '—'));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderMomentumTickerHistory(data) {
  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('h2', {}, `Price History: ${data.ticker}`));
  const bars = data.bars || [];
  if (!bars.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No price history.'));
    return wrap;
  }

  // Simple table
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Open', 'High', 'Low', 'Close', 'Volume'].forEach(h => {
    trh.appendChild(el('th', { class: h === 'Volume' ? 'num' : '' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const b of bars) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: 'mono' }, fmtDateYMD(b.date)));
    tr.appendChild(el('td', { class: 'num' }, b.open?.toFixed(2) || '—'));
    tr.appendChild(el('td', { class: 'num green' }, b.high?.toFixed(2) || '—'));
    tr.appendChild(el('td', { class: 'num red' }, b.low?.toFixed(2) || '—'));
    tr.appendChild(el('td', { class: 'num' }, b.close?.toFixed(2) || '—'));
    tr.appendChild(el('td', { class: 'num mut' }, fmtNum(b.volume)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

// ===========================================================================
// Correlation Matrix
// ===========================================================================

function renderCorrelation() {
  const wrap = el('div', { class: 'section' });
  const meta = state.corrMeta || {};

  // Stats bar
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Latest Date', meta.latest_date || '—'));
  stats.appendChild(stat('Total Rows', meta.total_rows || 0));
  wrap.appendChild(stats);

  // Tab bar: matrix vs pivot
  const tabBar = el('div', { class: 'tab-bar' });
  for (const t of [{ key: 'matrix', label: 'Matrix' }, { key: 'pivot', label: 'Pivot View' }]) {
    const active = state.corrActiveTab === t.key ? ' active' : '';
    tabBar.appendChild(el('a', {
      class: 'tab' + active,
      onclick: () => { state.corrActiveTab = t.key; setHash('#/correlation'); },
    }, t.label));
  }
  wrap.appendChild(tabBar);

  if (state.corrActiveTab === 'pivot') {
    wrap.appendChild(renderCorrelationPivot());
  } else {
    wrap.appendChild(renderCorrelationMatrixView());
  }

  return wrap;
}

function renderCorrelationMatrixView() {
  const m = state.corrMatrix;
  if (!m || !m.tickers || !m.tickers.length) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No correlation data available yet.'));
  }

  const wrap = el('div', { class: 'table-wrap' });

  // Window selector
  const PIVOTS = m.pivots || [];
  const WINDOWS = ['1_month', '3_month', '6_month', '12_month'];

  // Controls
  const controls = el('div', { class: 'filters' });
  controls.appendChild(el('span', {}, `Date: ${m.date || '—'}  |  `));
  controls.appendChild(el('span', {}, `Rows: ${m.tickers.length}  |  `));
  controls.appendChild(el('span', {}, `Pivots: ${PIVOTS.length}`));
  wrap.appendChild(controls);

  // Build a heatmap-style table
  // Columns: ticker + pivots
  const table = el('table', { class: 'corr-matrix' });
  const thead = el('thead');
  const trh = el('tr');
  trh.appendChild(el('th', {}, 'Ticker'));
  for (const p of PIVOTS) {
    trh.appendChild(el('th', { class: 'num' }, p));
  }
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const tkr of m.tickers) {
    const rowData = m.matrix[tkr] || {};
    const tr = el('tr');
    tr.appendChild(el('td', { class: 'mono brass' }, tkr));
    for (const p of PIVOTS) {
      const val = rowData[p];
      const txt = val != null ? val.toFixed(2) : '—';
      let cls = 'num';
      let bg = null;
      if (val != null) {
        if (val >= 0.5) cls += ' green';
        else if (val <= -0.5) cls += ' red';
        // Background tint
        const intensity = Math.min(Math.abs(val), 1) * 0.3;
        bg = val >= 0
          ? `rgba(46,154,105,${intensity})`
          : `rgba(199,62,76,${intensity})`;
      }
      tr.appendChild(el('td', { class: cls, style: { background: bg || undefined } }, txt));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  // Click a pivot to drill in
  wrap.appendChild(el('div', { class: 'hint', style: { marginTop: '0.5rem' } },
    '💡 Click any pivot header to see full ranking via #/correlation/' + PIVOTS[0]));

  return wrap;
}

function renderCorrelationPivot() {
  const p = state.corrPivotView;
  if (!p || !p.length) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No pivot data available.'));
  }

  const wrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Name', 'Category', 'Correlation'].forEach(h => {
    trh.appendChild(el('th', { class: h === 'Correlation' ? 'num' : '' }, h));
  });
  thead.appendChild(trh);

  const tbody = el('tbody');
  for (const r of p) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/ticker/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', {}, r.name || '—'));
    tr.appendChild(el('td', {}, r.category || '—'));
    const val = r.corr;
    const txt = val != null ? val.toFixed(2) : '—';
    const cls = `num ${val >= 0.5 ? 'green' : val <= -0.5 ? 'red' : ''}`;
    tr.appendChild(el('td', { class: cls }, txt));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

// ---------------- factor helpers ----------------
function factorColorHex(dimKey, bucket) {
  if (dimKey === 'size') return bucket === 'Large' ? CHART_COLORS.green
    : bucket === 'Mid' ? CHART_COLORS.brass
    : bucket === 'Small' ? CHART_COLORS.red : CHART_COLORS.dim;
  if (dimKey === 'value_growth') return bucket === 'Value' ? CHART_COLORS.green
    : bucket === 'Growth' ? CHART_COLORS.cyan
    : bucket === 'Blend' ? CHART_COLORS.brass : CHART_COLORS.dim;
  if (dimKey === 'momentum') return bucket === 'Momentum' ? CHART_COLORS.green
    : bucket === 'Contrarian' ? CHART_COLORS.red
    : bucket === 'Neutral' ? CHART_COLORS.brass : CHART_COLORS.dim;
  return CHART_COLORS.brass;
}

function bucketClass(dimKey, bucket) {
  if (dimKey === 'size') return bucket === 'Large' ? 'green'
    : bucket === 'Mid' ? 'brass' : bucket === 'Small' ? 'red' : 'dim';
  if (dimKey === 'value_growth') return bucket === 'Value' ? 'green'
    : bucket === 'Growth' ? 'brass' : bucket === 'Blend' ? 'brass' : 'dim';
  if (dimKey === 'momentum') return bucket === 'Momentum' ? 'green'
    : bucket === 'Contrarian' ? 'red' : bucket === 'Neutral' ? 'brass' : 'dim';
  return 'brass';
}

function dominantBucket(breakdown, order) {
  let best = order[0], bestPct = -1;
  for (const b of order) {
    const p = breakdown[b] || 0;
    if (p > bestPct) { bestPct = p; best = b; }
  }
  return { bucket: best, pct: bestPct };
}

// ---------------- Factor Exposure view ----------------
function renderFactors() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });
  const meta = state.factorMeta || {};

  // stats bar
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Quarter', fmtDateISO(meta.quarter) || '—'));
  stats.appendChild(stat('Coverage', meta.coverage_pct != null ? meta.coverage_pct + '%' : '—'));
  stats.appendChild(stat('Classified', meta.classified_tickers || 0));
  wrap.appendChild(stats);

  // tab bar
  const TAB_DEFS = [
    { key: 'drift', label: 'Style Drift' },
    { key: 'crowded', label: 'Crowded Trades' },
  ];
  const tabBar = el('div', { class: 'tabs' });
  for (const t of TAB_DEFS) {
    const active = state.factorActiveTab === t.key ? ' active' : '';
    tabBar.appendChild(el('a', {
      class: 'tab' + active,
      onclick: () => {
        state.factorActiveTab = t.key;
        setHash(t.key === 'drift' ? '#/factors' : '#/factors/' + t.key);
      },
    }, t.label));
  }
  wrap.appendChild(tabBar);

  if (meta.ready === false) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Factor data table not yet populated. Run the enrich_factors cron job over the latest 13F quarter.'));
    return wrap;
  }

  if (state.factorActiveTab === 'crowded') {
    wrap.appendChild(renderCrowdedTrades());
  } else if (state.factorActiveTab === 'ticker' && state.factorTicker) {
    wrap.appendChild(renderFactorTicker());
  } else {
    wrap.appendChild(renderFactorDrift());
  }
  return wrap;
}

function renderFactorDrift() {
  const exp = state.factorExposure;
  if (!exp) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No factor exposure data available yet.'));
  }

  const wrap = el('div');

  wrap.appendChild(el('div', { class: 'hint' },
    `Portfolio-value-weighted exposure for the latest 13F quarter (${fmtDateISO(exp.quarter)}). ` +
    `${exp.coverage_pct}% of ${fmtUSD(exp.total_aum_usd)} total AUM classified across ` +
    `${exp.classified_tickers} tickers.`));

  // one section per factor dimension
  for (const dim of exp.dimensions || []) {
    const sec = el('div', { class: 'section', style: { marginBottom: '20px' } });
    sec.appendChild(el('h3', { style: { marginTop: '0' } }, dim.label));

    // bar chart
    const canvas = el('canvas', {
      id: 'fc-' + dim.key,
      width: '400',
      height: '200',
      style: { width: '100%', height: '200px' },
    });
    sec.appendChild(canvas);
    setTimeout(() => {
      const labels = dim.overall.map(r => r.bucket);
      const data = {
        labels,
        datasets: [{
          label: 'Portfolio %',
          data: dim.overall.map(r => r.pct),
          backgroundColor: dim.overall.map(r => factorColorHex(dim.key, r.bucket)),
          borderColor: '#11161D',
          borderWidth: 0,
        }],
      };
      createBarChart('fc-' + dim.key, data, { indexAxis: 'y',
        scales: {
          x: { beginAtZero: true, max: 100, grid: { display: false } },
          y: { grid: { display: false } },
        },
        plugins: { tooltip: {
          callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed.x.toFixed(1)}%` }
        }},
      });
    }, 0);

    sec.appendChild(renderFactorTable(dim));
    wrap.appendChild(sec);
  }

  // strategy-tilt summary table
  wrap.appendChild(renderStrategyTilt(exp));
  return wrap;
}

function renderFactorTable(dim) {
  const wrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  const cols = [{ l: 'Bucket', c: '' }, { l: 'Portfolio $', c: 'num' },
                { l: '%', c: 'num' }, { l: 'Tickers', c: 'num' },
                { l: 'Funds', c: 'num' }];
  for (const c of cols) trh.appendChild(el('th', { class: c.c }, c.l));
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of dim.overall) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: bucketClass(dim.key, r.bucket) }, r.bucket));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.value_usd)));
    tr.appendChild(el('td', { class: 'num' }, r.pct.toFixed(1) + '%'));
    tr.appendChild(el('td', { class: 'num' }, r.tickers || 0));
    tr.appendChild(el('td', { class: 'num' }, r.holders || 0));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderStrategyTilt(exp) {
  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('h3', {}, 'Strategy Tilt'));
  const dims = exp.dimensions || [];
  // build per-strategy breakdown map
  const stratMap = {};
  for (const dim of dims) {
    for (const s of dim.by_strategy || []) {
      if (!stratMap[s.strategy]) stratMap[s.strategy] = { aum: 0, buckets: {} };
      stratMap[s.strategy].buckets[dim.key] = s.breakdown || {};
      if (s.aum_usd > (stratMap[s.strategy].aum || 0)) {
        stratMap[s.strategy].aum = s.aum_usd;
      }
    }
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  for (const h of ['Strategy', 'AUM', 'Size', 'Value/Growth', 'Momentum']) {
    trh.appendChild(el('th', { class: h === 'AUM' ? 'num' : '' }, h));
  }
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  const strategies = Object.keys(stratMap).sort();
  if (!strategies.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No strategy-level data.'));
    return wrap;
  }
  for (const strat of strategies) {
    const sm = stratMap[strat];
    const tr = el('tr');
    tr.appendChild(el('td', {}, strat));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(sm.aum)));
    for (const dim of dims) {
      const d = dominantBucket(sm.buckets[dim.key] || {}, dim.buckets);
      const cell = d.pct > 0 ? `${d.bucket} (${d.pct.toFixed(1)}%)` : '—';
      tr.appendChild(el('td', { class: 'num ' + bucketClass(dim.key, d.bucket) }, cell));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  wrap.appendChild(el('div', { class: 'hint' },
    'Dominant factor bucket per strategy (portfolio-value-weighted). Click any ticker below in Crowded Trades to drill down.'));
  return wrap;
}

function renderCrowdedTrades() {
  const data = state.crowdedTrades;
  if (!data) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No crowded-trades data available yet.'));
  }
  const wrap = el('div');
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Quarter', fmtDateISO(data.quarter) || '—'));
  stats.appendChild(stat('Positions', (data.rows || []).length));
  wrap.appendChild(stats);

  const rows = data.rows || [];
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No holdings data for this quarter.'));
    return wrap;
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  for (const h of ['Ticker', 'Name', 'Sector', 'Funds', 'Total $', 'Added', 'Removed']) {
    trh.appendChild(el('th', { class: h === 'Funds' || h === 'Total $' || h === 'Added' || h === 'Removed' ? 'num' : '' }, h));
  }
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/factors/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', {}, r.name || '—'));
    tr.appendChild(el('td', {}, r.sector || '—'));
    tr.appendChild(el('td', { class: 'num' }, r.holders || 0));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.total_value)));
    tr.appendChild(el('td', { class: 'num green' }, (r.funds_added || 0) > 0 ? ('+' + (r.funds_added)) : (r.funds_added || 0)));
    tr.appendChild(el('td', { class: 'num red' }, (r.funds_removed || 0) > 0 ? ('−' + (r.funds_removed)) : (r.funds_removed || 0)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  wrap.appendChild(el('div', { class: 'hint' },
    'Crowd score ~ funds holding × portfolio weight. Added/Removed = funds that increased/decreased this quarter.'));
  return wrap;
}

function renderFactorTicker() {
  const t = state.factorTicker;
  if (!t) {
    return el('div', { class: 'section' },
      el('div', { class: 'empty' }, 'No factor data for this ticker.'));
  }
  const wrap = el('div');

  // drill header
  const hdr = el('div', { class: 'drill-header' });
  hdr.appendChild(el('a', {
    class: 'back', href: '#/factors/crowded',
    onclick: (e) => { e.preventDefault(); setHash('#/factors/crowded'); },
  }, '← Crowded Trades'));
  hdr.appendChild(el('h2', {}, t.ticker));
  wrap.appendChild(hdr);

  // factor classification table
  const info = el('div', { class: 'table-wrap' });
  const itable = el('table');
  const itbody = el('tbody');
  const irows = [
    ['Size', fmtUSD(t.market_cap), 'size', t.size_bucket],
    ['Value / Growth', '\u2014', 'value_growth', t.value_bucket],
    ['Momentum (20d ROC)', t.momentum_roc_20d != null ? fmtPct(t.momentum_roc_20d) : '\u2014', 'momentum', t.momentum_bucket],
    ['P/E (trailing)', t.pe_ratio != null ? t.pe_ratio.toFixed(2) : '\u2014', '', ''],
    ['P/B', t.price_to_book != null ? t.price_to_book.toFixed(2) : '\u2014', '', ''],
  ];
  for (const [k, v, dimKey, bucket] of irows) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, k));
    tr.appendChild(el('td', { class: 'num' }, v));
    tr.appendChild(el('td', { class: dimKey ? bucketClass(dimKey, bucket) : 'dim' }, bucket || '\u2014'));
    itbody.appendChild(tr);
  }
  itable.appendChild(itbody);
  info.appendChild(itable);
  wrap.appendChild(info);

  // holders table
  const holders = t.holders || [];
  wrap.appendChild(el('h4', {}, `Fund Holders (${holders.length})`));
  if (holders.length) {
    const htable = el('table');
    const hthead = el('thead');
    const htrh = el('tr');
    for (const h of ['Fund', 'Strategy', 'Position $', '% of Fund', 'Shares']) {
      htrh.appendChild(el('th', { class: ['Position $','% of Fund','Shares'].includes(h) ? 'num' : '' }, h));
    }
    hthead.appendChild(htrh);
    htable.appendChild(hthead);
    const htbody = el('tbody');
    for (const h of holders) {
      const tr = el('tr', {
        style: { cursor: 'pointer' },
        onclick: () => setHash('#/fund/' + h.fund_cik),
      });
      tr.appendChild(el('td', {}, h.fund_name || '—'));
      tr.appendChild(el('td', {}, h.strategy || '—'));
      tr.appendChild(el('td', { class: 'num' }, fmtUSD(h.position_value)));
      tr.appendChild(el('td', { class: 'num' }, h.pct_of_fund != null ? h.pct_of_fund.toFixed(2) + '%' : '—'));
      tr.appendChild(el('td', { class: 'num' }, fmtNum(h.shares)));
      htbody.appendChild(tr);
    }
    htable.appendChild(htbody);
    wrap.appendChild(htable);
  }
  return wrap;
}

// ── Put/Call Ratio series labels ──
const PCR_SERIES_LABELS = {
  'TOTAL':   'Total Market',
  'INDEX':   'Index Options',
  'EQUITY':  'Equity Options',
  'ETP':     'ETP Options',
  'VIX':     'VIX Options',
  'SPX_SPXW':'SPX+SPXW',
  'OEX':     'OEX',
  'MRUT':    'MRUT',
};

function pcrSignalClass(signal) {
  if (signal === 'EXTREME_BULLISH' || signal === 'BULLISH') return 'green';
  if (signal === 'EXTREME_BEARISH' || signal === 'BEARISH') return 'red';
  return 'dim';
}

function pcrSignalLabel(signal) {
  if (!signal) return '—';
  const map = {
    'EXTREME_BULLISH': 'Extreme Bullish',
    'BULLISH':         'Bullish',
    'BEARISH':         'Bearish',
    'EXTREME_BEARISH': 'Extreme Bearish',
    'NEUTRAL':         'Neutral',
  };
  return map[signal] || signal.replace(/_/g, ' ');
}

function renderPutCallRatio() {
  const wrap = el('div', { class: 'section' });

  if (!state.pcrLatest && !state.pcrMeta) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading put/call ratio data…'));
    return wrap;
  }

  const latest = state.pcrLatest || { latest_date: '', rows: [] };
  const m = state.pcrMeta || {};

  // Stats row
  const dateFmt = latest.latest_date
    ? `${String(latest.latest_date).slice(5, 7)}/${String(latest.latest_date).slice(8, 10)}/${String(latest.latest_date).slice(0, 4)}`
    : '—';
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('As of', dateFmt));
  stats.appendChild(stat('Series', m.series_count || latest.rows?.length || 0, 'brass'));
  stats.appendChild(stat('Signals', m.extreme_count || 0));
  if (m.last_update) {
    const lu = `${String(m.last_update).slice(5, 7)}/${String(m.last_update).slice(8, 10)}/${String(m.last_update).slice(0, 4)}`;
    stats.appendChild(stat('Last Update', lu, 'brass'));
  }
  wrap.appendChild(stats);

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabLabels = [
    { key: 'latest',   label: 'Latest' },
    { key: 'signals',  label: 'Signals' },
    { key: 'history',  label: 'History' },
  ];
  for (const t of tabLabels) {
    tabs.appendChild(el('div', {
      class: 'tab' + (state.pcrActiveTab === t.key ? ' active' : ''),
      onclick: () => { state.pcrActiveTab = t.key; render(); },
    }, t.label));
  }
  wrap.appendChild(tabs);

  // Tab bodies
  if (state.pcrActiveTab === 'latest') {
    wrap.appendChild(renderPcrLatest());
  } else if (state.pcrActiveTab === 'signals') {
    wrap.appendChild(renderPcrSignals());
  } else if (state.pcrActiveTab === 'history') {
    wrap.appendChild(renderPcrHistory());
  }

  return wrap;
}

function renderPcrLatest() {
  const rows = state.pcrLatest?.rows || [];
  const wrap = el('div', { class: 'table-wrap' });

  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No put/call ratio data available yet.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Series', 'P/C Ratio', '5-Day MA', '20-Day MA', 'Vol', 'Open Interest', 'Signal'].forEach((h, i) => {
    const cls = (i >= 1 && i <= 3) ? 'num' : (i === 5 || i === 6) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, PCR_SERIES_LABELS[row.series] || row.series));

    const ratioVal = row.ratio != null ? row.ratio.toFixed(3) : '—';
    const ratioCls = row.ratio != null
      ? (row.ratio > 1.0 ? 'num red' : row.ratio < 0.7 ? 'num green' : 'num')
      : 'num';
    tr.appendChild(el('td', { class: ratioCls }, ratioVal));

    tr.appendChild(el('td', { class: 'num mut' }, row.ma5 != null ? row.ma5.toFixed(3) : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, row.ma20 != null ? row.ma20.toFixed(3) : '—'));

    const vol = row.total_volume != null ? fmtNum(row.total_volume) : '—';
    tr.appendChild(el('td', { class: 'num mut' }, vol));

    const oi = row.total_oi != null ? fmtNum(row.total_oi) : '—';
    tr.appendChild(el('td', { class: 'num mut' }, oi));

    const signal = row.signal || 'NEUTRAL';
    tr.appendChild(el('td', { class: 'num ' + pcrSignalClass(signal) }, pcrSignalLabel(signal)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  // Interpretation legend
  wrap.appendChild(el('div', { class: 'hint', style: { marginTop: '12px', fontSize: '12px' } },
    'Interpretation: High ratio (>1.2) = bearish sentiment / contrarian buy · Low ratio (<0.6) = bullish complacency / contrarian sell · Equity PCR < 0.6 often coincides with market tops.'));

  return wrap;
}

function renderPcrSignals() {
  const s = state.pcrSignals || { latest_date: '', signals: [] };
  const wrap = el('div', { class: 'table-wrap' });

  if (!s.signals || !s.signals.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No extreme readings in the recent window.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Series', 'Ratio', '5-Day MA', 'Z-Score', 'Signal'].forEach((h, i) => {
    const cls = i >= 2 ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of s.signals) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: 'mono' }, fmtDateISO(row.date)));
    tr.appendChild(el('td', {}, PCR_SERIES_LABELS[row.series] || row.series));

    const ratioCls = row.ratio > 1.0 ? 'num red' : row.ratio < 0.7 ? 'num green' : 'num';
    tr.appendChild(el('td', { class: ratioCls }, row.ratio.toFixed(3)));

    tr.appendChild(el('td', { class: 'num mut' }, row.ma5 != null ? row.ma5.toFixed(3) : '—'));

    const z = row.z_score != null ? (row.z_score > 0 ? '+' : '') + row.z_score.toFixed(2) : '—';
    const zCls = row.z_score > 2 ? 'num red' : row.z_score < -2 ? 'num green' : 'num mut';
    tr.appendChild(el('td', { class: zCls }, z));

    tr.appendChild(el('td', { class: 'num ' + pcrSignalClass(row.signal) }, pcrSignalLabel(row.signal)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  return wrap;
}

function renderPcrHistory() {
  const h = state.pcrHistory;
  const wrap = el('div', { class: 'section' });

  if (!h || !h.rows || !h.rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No historical data available.'));
    return wrap;
  }

  // Series selector
  const selWrap = el('div', { class: 'filters' });
  selWrap.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Series:'),
    el('select', {
      onchange: (e) => {
        state.pcrHistorySeries = e.target.value;
        render();
      },
    }, ...['TOTAL', 'INDEX', 'EQUITY', 'ETP', 'VIX'].map(s =>
      el('option', { value: s, selected: s === (state.pcrHistorySeries || 'TOTAL') }, PCR_SERIES_LABELS[s] || s)
    ))));
  wrap.appendChild(selWrap);

  // Chart container
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '400px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'pcr-history-chart' }));
  wrap.appendChild(chartWrap);

  // Render chart after DOM ready
  setTimeout(() => {
    const rows = h.rows;
    const labels = rows.map(r => r.date ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}` : '');
    const ratios = rows.map(r => r.ratio);
    const ma5 = rows.map(r => r.ma5);

    const ctx = document.getElementById('pcr-history-chart');
    if (charts['pcr-history-chart']) charts['pcr-history-chart'].destroy();
    charts['pcr-history-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Put/Call Ratio',
            data: ratios,
            borderColor: '#3B82F6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
          },
          {
            label: '5-Day MA',
            data: ma5,
            borderColor: '#C9A24E',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#E8EBEF', font: { size: 10 } },
          },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 12,
            callbacks: {
              label: (ctx) => {
                const idx = ctx.dataIndex;
                const v = ctx.raw;
                if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
                const band = v >= 1.0 ? '#C7564A' : v <= 0.6 ? '#2E9E6B' : '#C9A24E';
                const label = ctx.dataset.label || '';
                const cls = label.includes('MA') ? '' : (v > 1.0 ? 'Bearish' : v < 0.6 ? 'Bullish' : 'Neutral');
                return `${label}: ${v.toFixed(3)} ${cls}`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }, 0);

  return wrap;
}


// ──────────────────────────────────────────────────────────────
// IV Rank & IV Percentile renderers
// ──────────────────────────────────────────────────────────────
function renderIVRank() {
  const wrap = el('div', { class: 'section' });

  if (!state.ivMeta && !state.ivLatest) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading IV Rank data…'));
    return wrap;
  }

  const m = state.ivMeta || {};
  const latest = state.ivLatest || { rows: [] };
  const rows = latest.rows || [];

  // Stats row
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('As of', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', m.ticker_count || 0, 'brass'));
    stats.appendChild(stat('Sell-Side', m.high_iv_count || 0, 'green'));
    stats.appendChild(stat('Buy-Side', m.low_iv_count || 0, 'red'));
    if (m.last_ingestion) {
      stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
    }
    wrap.appendChild(stats);
  }

  // Empty state
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      m.latest_date
        ? 'No IV data available for this date.'
        : 'No IV data in database yet. Run the IV Rank cron to ingest.'));
    return wrap;
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.ivActiveTab === 'latest' ? 'active' : ''),
    onclick: () => { state.ivActiveTab = 'latest'; render(); },
  }, 'Latest'));
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.ivActiveTab === 'history' ? 'active' : ''),
    onclick: () => { state.ivActiveTab = 'history'; render(); },
  }, 'History'));
  wrap.appendChild(tabs);

  if (state.ivActiveTab === 'history') {
    wrap.appendChild(renderIVRankHistory());
  } else {
    wrap.appendChild(renderIVRankTable());
  }

  return wrap;
}

function renderIVRankTable() {
  const rows = state.ivLatest?.rows || [];
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');

  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'IV', 'IV Rank', 'IV %', 'Signal', '52w Range', 'Days'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const isHigh = r.signal === 'HIGH_IV';
    const isLow = r.signal === 'LOW_IV';
    const signalCls = isHigh ? 'green' : isLow ? 'red' : 'mut';
    const signalLabel = isHigh ? 'Sell-Side' : isLow ? 'Buy-Side' : 'Neutral';

    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/iv-rank/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', { class: 'num' }, r.iv ? r.iv.toFixed(1) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num' },
      r.iv_rank != null ? r.iv_rank.toFixed(0) : '—'));
    tr.appendChild(el('td', { class: 'num' },
      r.iv_pctile != null ? r.iv_pctile.toFixed(0) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num ' + signalCls }, signalLabel));
    const rangeStr = (r.iv_min_52w && r.iv_max_52w)
      ? `${r.iv_min_52w.toFixed(1)}%–${r.iv_max_52w.toFixed(1)}%` : '—';
    tr.appendChild(el('td', { class: 'num mut' }, rangeStr));
    tr.appendChild(el('td', { class: 'num mut' }, r.days_52w || 0));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}

function renderIVRankHistory() {
  const h = state.ivHistory;
  const wrap = el('div', { class: 'section' });

  if (!h || !h.rows || !h.rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Select a ticker from the Latest tab to view its IV history.'));
    return wrap;
  }

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/iv-rank',
    onclick: (e) => { e.preventDefault(); setHash('#/iv-rank'); },
  }, '← Back'));
  header.appendChild(el('h2', {}, `${h.ticker} — IV History`));
  wrap.appendChild(header);

  // Chart
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '400px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'iv-history-chart' }));
  wrap.appendChild(chartWrap);

  setTimeout(async () => {
    await ensureChartJS();
    const rows = h.rows;
    const labels = rows.map(r => r.date
      ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}/${String(r.date).slice(2, 4)}`
      : '');
    const ivs = rows.map(r => r.iv);
    const ranks = rows.map(r => r.iv_rank);

    // Moving averages
    const ma5 = [], ma20 = [];
    for (let i = 0; i < rows.length; i++) {
      const w5 = ivs.slice(Math.max(0, i - 4), i + 1);
      const w20 = ivs.slice(Math.max(0, i - 19), i + 1);
      ma5.push(w5.reduce((a, b) => a + b, 0) / w5.length);
      ma20.push(w20.reduce((a, b) => a + b, 0) / w20.length);
    }

    const ctx = document.getElementById('iv-history-chart');
    if (!ctx) return;
    if (charts['iv-history-chart']) charts['iv-history-chart'].destroy();
    charts['iv-history-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'IV',
            data: ivs,
            borderColor: '#C9A24E',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
          {
            label: 'IV Rank',
            data: ranks,
            borderColor: '#3B82F6',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            yAxisID: 'y1',
          },
          {
            label: '5-Day MA',
            data: ma5,
            borderColor: '#C9A24E',
            borderWidth: 1,
            borderDash: [3, 3],
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
          {
            label: '20-Day MA',
            data: ma20,
            borderColor: '#2E9E6B',
            borderWidth: 1,
            borderDash: [3, 3],
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#E8EBEF', font: { size: 10 } } },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 12,
            callbacks: {
              label: (ctx) => {
                const v = ctx.raw;
                if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
                const lbl = ctx.dataset.label;
                if (lbl === 'IV') return `IV: ${v.toFixed(1)}%`;
                if (lbl === 'IV Rank') return `Rank: ${v.toFixed(0)}`;
                return `${lbl}: ${v.toFixed(1)}`;
              },
            },
          },
        },
        scales: {
          y: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'IV %', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y1: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'IV Rank', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { drawBorder: false, color: 'rgba(30,42,56,0.3)' },
            min: 0,
            max: 100,
          },
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }, 0);

  return wrap;
}


// ---------------- data loaders ----------------
async function loadNews(r) {
  state.newsActiveTab = r.newsTab || 'headlines';
  state.newsTicker = r.newsTicker || null;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, headlines, signals] = await Promise.all([
      api('/api/news/meta'),
      api('/api/news/headlines'),
      api('/api/news/signals'),
    ]);
    state.newsMeta = meta;
    state.newsHeadlines = headlines;
    state.newsSignals = signals;
    if (state.newsActiveTab === 'ticker' && state.newsTicker) {
      state.newsTickerDetail = await api(`/api/news/tickers/${state.newsTicker}`);
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- render ----------------
function renderNews() {
  const wrap = el('div', { class: 'section' });

  if (!state.newsMeta && !state.newsHeadlines) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading news sentiment data…'));
    return wrap;
  }

  const m = state.newsMeta || {};
  const headlines = state.newsHeadlines || { headlines: [] };
  const signals = state.newsSignals || { bullish: [], bearish: [] };

  // Stats row
  const dateFmt = fmtDateISO(m.latest_date);
  const sigDate = fmtDateISO(signals.latest_date);
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('As of', dateFmt));
  stats.appendChild(stat('Headlines', m.total_headlines || 0, 'brass'));
  stats.appendChild(stat('Sources', m.sources ? m.sources.length : 0));
  stats.appendChild(stat('Signals', sigDate, 'brass'));
  const bullishN = (signals.bullish || []).length;
  const bearishN = (signals.bearish || []).length;
  stats.appendChild(stat('Bullish', bullishN, 'green'));
  stats.appendChild(stat('Bearish', bearishN, 'red'));
  if (m.last_ingestion) {
    stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
  }
  wrap.appendChild(stats);

  // Sources badge
  if (m.sources && m.sources.length) {
    const badgeWrap = el('div', { class: 'badge-row' });
    for (const src of m.sources) {
      badgeWrap.appendChild(el('span', { class: 'badge' }, src));
    }
    wrap.appendChild(badgeWrap);
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabLabels = [
    { key: 'headlines', label: 'Headlines' },
    { key: 'signals',   label: 'Signals' },
    { key: 'ticker',    label: state.newsTicker || 'Ticker' },
  ];
  for (const t of tabLabels) {
    if (t.key === 'ticker' && !state.newsTicker) continue;
    tabs.appendChild(el('div', {
      class: 'tab' + (state.newsActiveTab === t.key ? ' active' : ''),
      onclick: () => {
        if (t.key === 'ticker' && !state.newsTicker) {
          const tkr = prompt('Enter ticker symbol (e.g. AAPL):');
          if (tkr) {
            state.newsTicker = tkr.trim().toUpperCase();
            state.newsActiveTab = 'ticker';
            state.newsTickerDetail = null;
            location.hash = '#/news/' + state.newsTicker;
            return;
          }
          return;
        }
        state.newsActiveTab = t.key;
        if (state.newsTicker) {
          location.hash = '#/news/' + (t.key === 'ticker' ? state.newsTicker : t.key);
        } else {
          location.hash = '#/news/' + t.key;
        }
      },
    }, t.label));
  }
  wrap.appendChild(tabs);

  // Tab bodies
  if (state.newsActiveTab === 'headlines') {
    wrap.appendChild(renderNewsHeadlines());
  } else if (state.newsActiveTab === 'signals') {
    wrap.appendChild(renderNewsSignals());
  } else if (state.newsActiveTab === 'ticker') {
    wrap.appendChild(renderNewsTicker());
  }

  return wrap;
}

function renderNewsHeadlines() {
  const h = state.newsHeadlines || { headlines: [] };
  const rows = h.headlines || [];
  const wrap = el('div', { class: 'table-wrap' });

  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No headlines available yet.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Score', 'Source', 'Headline', 'Tickers'].forEach((hdr, i) => {
    trh.appendChild(el('th', { class: i === 0 ? 'num' : '' }, hdr));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  const fmtTime = (s) => s ? String(s).slice(11, 16) : '—';
  for (const row of rows) {
    const tr = el('tr', { style: { '--hl-sentiment': row.sentiment_score } });
    const scoreCls = row.sentiment_label === 'bullish' ? 'num green' :
                     row.sentiment_label === 'bearish' ? 'num red' : 'num mut';
    const arrow = row.sentiment_label === 'bullish' ? '↑' :
                  row.sentiment_label === 'bearish' ? '↓' : '≈';
    const score = row.sentiment_score != null ? row.sentiment_score.toFixed(2) : '0.00';
    tr.appendChild(el('td', { class: scoreCls }, arrow + ' ' + score));
    tr.appendChild(el('td', { class: 'sm mut' }, row.source || '—'));
    const linkCell = el('td');
    const link = el('a', {
      href: row.url || '#',
      target: '_blank',
      class: 'link',
      onclick: (e) => { e.preventDefault(); window.open(row.url || '#', '_blank'); },
    }, row.title);
    linkCell.appendChild(link);
    if (row.tickers_mentioned) {
      const chips = row.tickers_mentioned.split(',').map(t => el('span', { class: 'ticker-chip' }, t.trim()));
      linkCell.appendChild(el('div', { class: 'ticker-chips' }, ...chips));
    }
    tr.appendChild(linkCell);
    tr.appendChild(el('td', { class: 'mono sm mut' }, row.tickers_mentioned || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderNewsSignals() {
  const s = state.newsSignals || { latest_date: null, bullish: [], bearish: [] };
  const wrap = el('div', { class: 'table-wrap' });

  if (!s.bullish?.length && !s.bearish?.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'No significant sentiment signals. Tickers need ≥2 headlines with avg sentiment ≥0.15 (bullish) or ≤−0.15 (bearish).'));
    return wrap;
  }

  const dateFmt = fmtDateISO(s.latest_date);
  wrap.appendChild(el('div', { class: 'section-title' }, 'Signals as of ' + dateFmt));

  function renderSignalTable(label, rows, signClass) {
    if (!rows || !rows.length) return null;
    const block = el('div', { class: 'signal-block' });
    block.appendChild(el('h4', { class: 'signal-label ' + signClass }, label));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['Ticker', 'Headlines', 'Avg', '↑ Bull', '↓ Bear'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of rows) {
      const tr = el('tr');
      const tickerLink = el('a', {
        href: '#/news/' + row.ticker,
        class: 'ticker-link',
        onclick: (e) => {
          e.preventDefault();
          state.newsActiveTab = 'ticker';
          state.newsTicker = row.ticker;
          state.newsTickerDetail = null;
          location.hash = '#/news/' + row.ticker;
          render();
        },
      }, row.ticker);
      tr.appendChild(el('td', {}, tickerLink));
      tr.appendChild(el('td', { class: 'num' }, row.headline_count));
      const avgCls = row.avg_sentiment > 0 ? 'num green' : 'num red';
      tr.appendChild(el('td', { class: avgCls },
        (row.avg_sentiment > 0 ? '+' : '') + (row.avg_sentiment || 0).toFixed(2)));
      tr.appendChild(el('td', { class: 'num green' }, row.bullish_count || 0));
      tr.appendChild(el('td', { class: 'num red' }, row.bearish_count || 0));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    block.appendChild(table);
    return block;
  }

  const b = renderSignalTable('Bullish', s.bullish, 'green');
  if (b) wrap.appendChild(b);
  const be = renderSignalTable('Bearish', s.bearish, 'red');
  if (be) wrap.appendChild(be);

  return wrap;
}

function renderNewsTicker() {
  const d = state.newsTickerDetail;
  const wrap = el('div', { class: 'table-wrap' });

  if (!d) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading ticker data…'));
    return wrap;
  }

  if (!d.history?.length && !d.headlines?.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      `No news sentiment data for ${d.ticker} yet. Try another ticker.`));
    return wrap;
  }

  // History table
  if (d.history && d.history.length) {
    wrap.appendChild(el('h4', { class: 'signal-label brass' }, d.ticker + ' — Daily Sentiment History'));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['Date', 'Headlines', 'Avg Sentiment', '↑', '↓', '≈'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? 'mono' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of d.history.reverse()) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'mono sm' }, fmtDateISO(row.date)));
      tr.appendChild(el('td', { class: 'num' }, row.headline_count));
      const avgCls = row.avg_sentiment > 0.15 ? 'num green' :
                     row.avg_sentiment < -0.15 ? 'num red' : 'num mut';
      tr.appendChild(el('td', { class: avgCls },
        (row.avg_sentiment > 0 ? '+' : '') + (row.avg_sentiment || 0).toFixed(3)));
      tr.appendChild(el('td', { class: 'num green' }, row.bullish_count || 0));
      tr.appendChild(el('td', { class: 'num red' }, row.bearish_count || 0));
      tr.appendChild(el('td', { class: 'num mut' }, row.neutral_count || 0));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    d.history.reverse(); // restore
  }

  // Headlines table
  if (d.headlines && d.headlines.length) {
    wrap.appendChild(el('h4', { class: 'signal-label brass' }, d.ticker + ' — Recent Headlines'));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['', 'Headline', 'Sentiment'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? 'sm mut' : i === 1 ? '' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of d.headlines) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'sm mut' }, row.source || '—'));
      const link = el('a', {
        href: row.url || '#',
        target: '_blank',
        class: 'link',
      }, row.title);
      tr.appendChild(el('td', {}, link));
      const scoreCls = row.sentiment_label === 'bullish' ? 'num green' :
                       row.sentiment_label === 'bearish' ? 'num red' : 'num mut';
      const arrow = row.sentiment_label === 'bullish' ? '↑' :
                    row.sentiment_label === 'bearish' ? '↓' : '≈';
      const score = row.sentiment_score != null ? row.sentiment_score.toFixed(2) : '0.00';
      tr.appendChild(el('td', { class: scoreCls }, arrow + ' ' + score));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  return wrap;
}

// ---------------- Position Sizing Calculator (Kelly Criterion) ----------------
function renderPositionSizing() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  // ---- Header ----
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Position Sizing Calculator'),
    el('div', { class: 'hint' }, 'Kelly Criterion · Full · Half · Quarter')));

  // ---- Explainer ----
  wrap.appendChild(el('p', { class: 'page-description-para' },
    'The Kelly Criterion determines the fraction of your capital to risk on each trade to maximise long-term compound growth. Given your edge — expressed as a win rate and reward-to-risk ratio — Kelly gives the theoretically optimal bet size. Most traders use Half or Quarter Kelly to reduce volatility and overshoot risk.'));

  // ---- Calculator ----
  const form = el('div', { class: 'calc-form' });

  // --- Inputs ---
  const inputPanel = el('div', { class: 'calc-inputs' });

  const accountInput = el('input', { type: 'number', id: 'ps-account', min: '0', step: '1000', value: '100000' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-account' }, 'Account size'),
    accountInput));

  const winRateInput = el('input', { type: 'number', id: 'ps-winrate', min: '0', max: '100', step: '0.5', value: '60' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-winrate' }, 'Win rate'),
    el('div', { class: 'calc-input-row' },
      winRateInput,
      el('span', { class: 'unit' }, '%'))));

  const rrrInput = el('input', { type: 'number', id: 'ps-rrr', min: '0.01', step: '0.1', value: '2.0' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-rrr' }, 'Reward : Risk'),
    rrrInput));

  const variantSelect = el('select', { id: 'ps-variant' },
    el('option', { value: 'full' }, 'Full Kelly'),
    el('option', { value: 'half', selected: true }, 'Half Kelly'),
    el('option', { value: 'quarter' }, 'Quarter Kelly'));
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-variant' }, 'Allocation'),
    variantSelect));

  // --- Results ---
  const resultsPanel = el('div', { class: 'calc-results' });

  const elKellyFull    = el('span', { class: 'calc-stat-value mono' }, '—');
  const elKellyHalf    = el('span', { class: 'calc-stat-value mono brass' }, '—');
  const elKellyQuarter = el('span', { class: 'calc-stat-value mono' }, '—');
  const elRisk         = el('span', { class: 'calc-stat-value mono' }, '—');
  const elPosition     = el('span', { class: 'calc-stat-value mono' }, '—');
  const elEv           = el('span', { class: 'calc-stat-value mono' }, '—');

  resultsPanel.appendChild(el('div', { class: 'calc-result-group' },
    el('h3', {}, 'Kelly allocation'),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Full'),
      elKellyFull),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Half'),
      elKellyHalf),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Quarter'),
      elKellyQuarter)));

  resultsPanel.appendChild(el('div', { class: 'calc-result-group' },
    el('h3', {}, 'Position sizing'),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Risk per trade'),
      elRisk),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Position value'),
      elPosition),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Expected value'),
      elEv)));

  form.appendChild(inputPanel);
  form.appendChild(resultsPanel);
  wrap.appendChild(form);

  // ---- Formula footnote ----
  wrap.appendChild(el('p', { class: 'calc-formula' },
    'f* = p − (1−p)/b  |  p = win rate, b = reward:risk ratio  |  position = risk × b'));

  // ---- Calculation (pure functions, no DOM lookups) ----
  function fmtPct(n) {
    if (n === 0) return '0.0%';
    return (n * 100).toFixed(1) + '%';
  }
  function fmtSignedPct(n) {
    if (n === 0) return '0.0%';
    return (n > 0 ? '+' : '−') + Math.abs(n * 100).toFixed(1) + '%';
  }

  function recalc() {
    const account = parseFloat(accountInput.value) || 0;
    const winRate = parseFloat(winRateInput.value) || 0;
    const rrr     = parseFloat(rrrInput.value) || 1;
    const variant = variantSelect.value;

    const p = winRate / 100;
    const q = 1 - p;
    const b = rrr;

    // Kelly Criterion: f* = p − q/b
    const kelly = p - q / b;
    const kellyFull    = Math.max(0, kelly);
    const kellyHalf    = Math.max(0, kelly / 2);
    const kellyQuarter = Math.max(0, kelly / 4);

    elKellyFull.textContent    = fmtPct(kellyFull);
    elKellyHalf.textContent    = fmtPct(kellyHalf);
    elKellyQuarter.textContent = fmtPct(kellyQuarter);

    const variantMap = { full: kellyFull, half: kellyHalf, quarter: kellyQuarter };
    const selected = variantMap[variant];

    const riskPerTrade  = account * selected;
    const positionValue = riskPerTrade * b;
    const ev            = p * b - q;  // expected value per dollar risked

    const hasEdge = kelly > 0;

    elRisk.textContent     = hasEdge ? fmtUSD(riskPerTrade,   { compact: false }) : '—';
    elPosition.textContent = hasEdge ? fmtUSD(positionValue, { compact: false }) : '—';
    elEv.textContent       = fmtSignedPct(ev);

    elEv.className = 'calc-stat-value mono ' + (ev > 0 ? 'green' : ev < 0 ? 'red' : '');
  }

  // Attach listeners to captured element references
  accountInput.addEventListener('input', recalc);
  winRateInput.addEventListener('input', recalc);
  rrrInput.addEventListener('input', recalc);
  variantSelect.addEventListener('change', recalc);

  recalc();
  return wrap;
}

// ---------------- Drawdown Simulator (Monte Carlo) ----------------
function renderDrawdownSimulator() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  // ---- Header ----
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Drawdown Simulator'),
    el('div', { class: 'hint' }, 'Monte Carlo · Kelly-compatible')));

  // ---- Explainer ----
  wrap.appendChild(el('p', { class: 'page-description-para' },
    'Monte Carlo drawdown simulator. Simulate hundreds of possible trade sequences to see how your edge — win rate, reward-to-risk ratio, and risk per trade — translates into real-world outcomes. The equity curve shows multiple simulation paths plus the median; statistics summarise the distribution of final values and drawdowns.'));

  // ---- Inputs ----
  const ctrl = el('div', { class: 'sim-controls' });

  const accountInput = el('input', { type: 'number', id: 'ds-account', min: '0', step: '1000', value: '100000' });
  const winRateInput = el('input', { type: 'number', id: 'ds-winrate', min: '0', max: '100', step: '0.5', value: '60' });
  const rrrInput     = el('input', { type: 'number', id: 'ds-rrr', min: '0.01', step: '0.1', value: '2.0' });
  const riskInput    = el('input', { type: 'number', id: 'ds-risk', min: '0', max: '100', step: '0.5', value: '2' });
  const tradesInput  = el('input', { type: 'number', id: 'ds-trades', min: '1', max: '1000', step: '1', value: '250' });
  const simsInput    = el('input', { type: 'number', id: 'ds-sims', min: '10', max: '200', step: '10', value: '50' });

  /** Helper: build a labelled input row with optional unit suffix */
  function addCtrl(label, inputEl, unit) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', { for: inputEl.id }, label));
    const row = el('div', { class: 'calc-input-row' });
    row.appendChild(inputEl);
    if (unit) row.appendChild(el('span', { class: 'unit' }, unit));
    field.appendChild(row);
    return field;
  }

  ctrl.appendChild(addCtrl('Account size', accountInput));
  ctrl.appendChild(addCtrl('Win rate', winRateInput, '%'));
  ctrl.appendChild(addCtrl('Reward : Risk', rrrInput));
  ctrl.appendChild(addCtrl('Risk per trade', riskInput, '%'));
  ctrl.appendChild(addCtrl('Trades', tradesInput));
  ctrl.appendChild(addCtrl('Simulations', simsInput));
  wrap.appendChild(ctrl);

  // ---- Stats panel ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addStat('Avg final value',  'avgFinal', 'brass');
  addStat('Median final',     'median');
  addStat('Avg max drawdown', 'avgDD',    'red');
  addStat('Prob >20% DD',     'probDD',   'amber');
  addStat('Prob of ruin',     'probRuin', 'red');
  addStat('Worst 5%',         'worst5');
  addStat('Avg CAGR',         'cagr',     'green');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'sim-chart' });
  chartWrap.appendChild(el('canvas', { id: 'ds-equity-chart' }));
  wrap.appendChild(chartWrap);

  // ---- Formula ----
  wrap.appendChild(el('p', { class: 'calc-formula' },
    'Trade: win → account × (1 + r×b),  loss → account × (1 − r)  |  r = risk %, b = reward:risk  |  252 trading days/year'));

  // ---- Helpers ----
  /** Set stat value text, optionally overriding the value color class */
  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      if (cls !== undefined) v.className = 'stat-value ' + cls;
    }
  }

  // ---- Simulation ----
  async function runSim() {
    const account   = parseFloat(accountInput.value)  || 100000;
    const winRate   = parseFloat(winRateInput.value)  || 60;
    const rrr       = parseFloat(rrrInput.value)        || 2;
    const riskPct   = parseFloat(riskInput.value)     || 2;
    const numTrades = Math.max(1, parseInt(tradesInput.value) || 250);
    const numSims   = Math.min(200, Math.max(10, parseInt(simsInput.value) || 50));

    const p = winRate / 100;
    const b = rrr;
    const r = riskPct / 100;
    const ruinThreshold = account * 0.5;

    const finals = [];
    const maxDDs = [];
    const allPaths = [];

    for (let s = 0; s < numSims; s++) {
      let cap = account;
      let peak = cap;
      let maxDD = 0;
      const path = [cap];

      for (let t = 0; t < numTrades; t++) {
        if (Math.random() < p) {
          cap *= (1 + r * b);
        } else {
          cap *= (1 - r);
        }
        path.push(cap);
        if (cap > peak) peak = cap;
        const dd = (peak - cap) / peak;
        if (dd > maxDD) maxDD = dd;
      }

      finals.push(cap);
      maxDDs.push(maxDD * 100);
      allPaths.push(path);
    }

    // ---- Aggregate stats ----
    const sortedFinals = [...finals].sort((a, b) => a - b);
    const worst5th    = sortedFinals[Math.floor(numSims * 0.05) || 0];
    const medianFinal = sortedFinals[Math.floor(numSims * 0.5)];
    const cagrs       = finals.map(f => Math.pow(f / account, 252 / numTrades) - 1);
    const avgCagr     = cagrs.reduce((a, v) => a + v, 0) / numSims;
    const avgFinal    = finals.reduce((a, v) => a + v, 0) / numSims;
    const avgMaxDD    = maxDDs.reduce((a, v) => a + v, 0) / numSims;
    const probDD      = maxDDs.filter(dd => dd > 20).length / numSims * 100;
    const probRuin    = finals.filter(f => f < ruinThreshold).length / numSims * 100;

    setStat('avgFinal', fmtUSD(avgFinal, { compact: false }));
    setStat('median',   fmtUSD(medianFinal, { compact: false }));
    setStat('avgDD',    avgMaxDD.toFixed(1) + '%', avgMaxDD > 20 ? 'red' : avgMaxDD > 10 ? 'amber' : '');
    setStat('probDD',   probDD.toFixed(0) + '%',   probDD > 50 ? 'red' : probDD > 0 ? 'amber' : 'green');
    setStat('probRuin', probRuin.toFixed(0) + '%', probRuin > 0 ? 'red' : 'green');
    setStat('worst5',   fmtUSD(worst5th, { compact: false }));
    setStat('cagr',     (avgCagr * 100).toFixed(1) + '%', avgCagr > 0 ? 'green' : avgCagr < 0 ? 'red' : '');

    // ---- Chart ----
    const chartPaths = allPaths.slice(0, Math.min(20, numSims));

    // Compute median path across all sims
    const medianPath = [];
    for (let t = 0; t <= numTrades; t++) {
      const vals = allPaths.map(pa => pa[t] || account).sort((a, b) => a - b);
      medianPath.push(vals[Math.floor(vals.length / 2)]);
    }

    const labelStep = Math.max(1, Math.floor(numTrades / 10));
    const labels = Array.from({ length: numTrades + 1 }, (_, i) =>
      i % labelStep === 0 ? String(i) : '');

    const canvas = document.getElementById('ds-equity-chart');
    if (!canvas) return;
    if (charts['ds-equity-chart']) charts['ds-equity-chart'].destroy();

    await ensureChartJS();

    const ctx = canvas.getContext('2d');
    charts['ds-equity-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          // Individual sim paths (dim)
          ...chartPaths.map((path, i) => ({
            label: 'Sim ' + (i + 1),
            data: path,
            borderColor: 'rgba(126, 138, 154, 0.25)',
            borderWidth: 1,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          })),
          // Starting capital reference
          {
            label: 'Starting capital',
            data: Array(numTrades + 1).fill(account),
            borderColor: 'rgba(126, 138, 154, 0.5)',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
          },
          // Median path (brass, bold)
          {
            label: 'Median',
            data: medianPath,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2.5,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: (c) => '$' + Math.round(c.raw).toLocaleString(),
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            beginAtZero: false,
            ticks: {
              color: '#7E8A9A',
              font: { size: 9 },
              callback: (v) => '$' + Math.round(v).toLocaleString(),
            },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }

  // Attach listeners
  [accountInput, winRateInput, rrrInput, riskInput, tradesInput, simsInput]
    .forEach(inp => inp.addEventListener('input', runSim));

  runSim();
  return wrap;
}

// ---------------- Options Payoff Visualizer ----------------
function renderPayoffVisualizer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Options Payoff Visualizer'),
    el('div', { class: 'hint brass' }, 'Multi-leg builder · P&L at expiration · Client-side')));

  const _desc = renderPageDescription('payoff');
  if (_desc) wrap.appendChild(_desc);

  // ---- Legs container ----
  const legsContainer = el('div', { class: 'legs-container' });
  wrap.appendChild(legsContainer);

  const addBtn = el('button', { class: 'payoff-add-btn', onclick: addLeg }, '+ Add Leg');
  wrap.appendChild(addBtn);

  // ---- Stats panel ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addStat('Max profit',  'maxProfit', 'green');
  addStat('Max loss',    'maxLoss',   'red');
  addStat('Breakevens',  'breakevens');
  addStat('P&L at low',  'pnlLow');
  addStat('P&L at high', 'pnlHigh');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'sim-chart' });
  chartWrap.appendChild(el('canvas', { id: 'pv-chart' }));
  wrap.appendChild(chartWrap);

  // ---- Formula footnote ----
  wrap.appendChild(el('div', { class: 'calc-formula' },
    'Long call: max(S−K,0) − premium  |  Long put: max(K−S,0) − premium  |  Short:  premium − max(intrinsic,0)'));

  // ---- Helpers ----
  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      if (cls !== undefined) v.className = 'stat-value ' + cls;
    }
  }

  function makeSelect(opts, cls, label) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', {}, label));
    const sel = el('select', { class: cls || '' });
    opts.forEach(([v, t]) => sel.appendChild(el('option', { value: v }, t)));
    field.appendChild(sel);
    return field;
  }

  function makeNumField(label, cls, val) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', {}, label));
    field.appendChild(el('input', { type: 'number', class: cls, min: '0', step: '0.01', value: val ?? '' }));
    return field;
  }

  function addLeg(defaults) {
    defaults = defaults || {};
    const row = el('div', { class: 'leg-row' });
    row.appendChild(makeSelect([['call','Call'],['put','Put']], 'leg-type', 'Type'));
    row.appendChild(makeSelect([['buy','Buy'],['sell','Sell']], 'leg-action', 'Action'));
    row.appendChild(makeNumField('Strike',  'leg-strike',  defaults.strike ?? ''));
    row.appendChild(makeNumField('Premium',  'leg-premium', defaults.premium ?? ''));
    row.appendChild(el('button', { class: 'leg-remove', onclick: () => { row.remove(); recalc(); } }, '✕'));
    legsContainer.appendChild(row);
    row.querySelectorAll('input, select').forEach(i => i.addEventListener('input', recalc));
    const firstEmpty = row.querySelector('input[value=""]');
    if (firstEmpty) firstEmpty.focus(); else row.querySelector('input').focus();
    recalc();
  }

  // ---- Payoff math ----
  function calcLegPayoff(leg, price) {
    const intrinsic = leg.type === 'call' ? Math.max(price - leg.strike, 0) : Math.max(leg.strike - price, 0);
    return leg.action === 'buy' ? intrinsic - leg.premium : leg.premium - intrinsic;
  }

  function readLegs() {
    const legs = [];
    const rows = legsContainer.querySelectorAll('.leg-row');
    for (const row of rows) {
      const type   = row.querySelector('.leg-type').value;
      const action = row.querySelector('.leg-action').value;
      const strike  = parseFloat(row.querySelector('.leg-strike').value);
      const premium = parseFloat(row.querySelector('.leg-premium').value);
      if (!isNaN(strike) && !isNaN(premium) && strike > 0 && premium >= 0) {
        legs.push({ type, action, strike, premium });
      }
    }
    return legs;
  }

  function findBreakevens(prices, payoffs) {
    const result = [];
    for (let i = 1; i < payoffs.length; i++) {
      const a = payoffs[i - 1], b = payoffs[i];
      if ((a <= 0 && b > 0) || (a >= 0 && b < 0)) {
        const t = a === b ? 0 : -a / (b - a);
        result.push(prices[i - 1] + t * (prices[i] - prices[i - 1]));
      }
    }
    return result;
  }

  // ---- Main recalc ----
  async function recalc() {
    const legs = readLegs();

    if (legs.length === 0) {
      setStat('maxProfit',  '—');
      setStat('maxLoss',    '—');
      setStat('breakevens', '—');
      setStat('pnlLow',     '—');
      setStat('pnlHigh',    '—');
      if (charts['pv-chart']) charts['pv-chart'].destroy();
      return;
    }

    // Price range (60% below lowest strike to 40% above highest)
    const strikes = legs.map(l => l.strike);
    const lo = Math.min(...strikes), hi = Math.max(...strikes);
    const priceMin = Math.max(0.01, lo * 0.6);
    const priceMax = hi * 1.4;
    const N = 200;
    const step = (priceMax - priceMin) / N;
    const prices = [], payoffs = [];
    for (let i = 0; i <= N; i++) {
      const p = priceMin + i * step;
      prices.push(p);
      payoffs.push(legs.reduce((sum, leg) => sum + calcLegPayoff(leg, p), 0));
    }

    const maxProfit = Math.max(...payoffs);
    const maxLoss   = Math.min(...payoffs);
    const bbs       = findBreakevens(prices, payoffs);

    setStat('maxProfit',  fmtUSD(maxProfit, { compact: false }), maxProfit >= 0 ? 'green' : 'red');
    setStat('maxLoss',    fmtUSD(maxLoss, { compact: false }),   maxLoss  < 0 ? 'red'   : 'green');
    setStat('breakevens', bbs.length ? bbs.map(b => '$' + b.toFixed(2)).join(', ') : 'None');
    setStat('pnlLow',     fmtUSD(payoffs[0], { compact: false }));
    setStat('pnlHigh',    fmtUSD(payoffs[N], { compact: false }));

    // Chart
    await ensureChartJS();
    const canvas = document.getElementById('pv-chart');
    if (!canvas) return;
    if (charts['pv-chart']) charts['pv-chart'].destroy();
    const ctx = canvas.getContext('2d');
    const zeroData = prices.map(() => 0);

    charts['pv-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: prices.map(p => p.toFixed(0)),
        datasets: [
          {
            label: 'P&L',
            data: payoffs,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          },
          {
            label: 'Break-even',
            data: zeroData,
            borderColor: '#5C6B7A',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
          },
          ...bbs.map(price => ({
            label: 'Breakeven',
            data: [{ x: price, y: 0 }],
            backgroundColor: CHART_COLORS.brass,
            borderColor: CHART_COLORS.brass,
            pointRadius: 5,
            pointHoverRadius: 7,
            showLine: false,
          })),
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: (c) => '$' + Math.round(c.raw).toLocaleString(),
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Underlying Price ($)', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            title: { display: true, text: 'P&L ($)', color: '#7E8A9A', font: { size: 10 } },
            ticks: {
              color: '#7E8A9A',
              font: { size: 9 },
              callback: (v) => '$' + Math.round(v).toLocaleString(),
            },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }

  // Seed with a single long call for immediate visual feedback
  addLeg({ strike: 100, premium: 5 });

  return wrap;
}

// ---------------- Greeks Explainer ----------------
// Black-Scholes-Merton Greeks calculator (client-side, no API)

function normCDF(x) {
  // Abramowitz & Stegun 26.2.17 approximation
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3734358 + t * (1.7814779 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

function normPDF(x) {
  return 0.3989423 * Math.exp(-x * x / 2);
}

function computeGreeks(S, K, r, q, sigma, T, isCall) {
  // Convert T from days to years
  const tau = T / 365;
  if (tau <= 0 || sigma <= 0 || S <= 0) {
    return { price: 0, delta: 0, gamma: 0, theta: 0, vega: 0, probITM: 0 };
  }

  const d1 = (Math.log(S / K) + (r - q + sigma * sigma / 2) * tau) / (sigma * Math.sqrt(tau));
  const d2 = d1 - sigma * Math.sqrt(tau);

  const _Nd1 = normCDF(d1);
  const _Nd2 = normCDF(d2);
  const pdf1 = normPDF(d1);

  // Discount factors
  const disc_r = Math.exp(-r * tau);
  const disc_q = Math.exp(-q * tau);

  // Option price (for reference)
  const price = isCall
    ? S * disc_q * _Nd1 - K * disc_r * normCDF(d2)
    : K * disc_r * normCDF(-d2) - S * disc_q * normCDF(-d1);

  // Delta
  const delta = isCall
    ? disc_q * _Nd1
    : disc_q * (_Nd1 - 1);

  // Gamma (same for call and put)
  const gamma = disc_q * pdf1 / (S * sigma * Math.sqrt(tau));

  // Theta (annualized, then converted to daily)
  const theta = isCall
    ? -(S * sigma * pdf1 * disc_q) / (2 * Math.sqrt(tau))
      - r * K * disc_r * normCDF(d2)
      + q * S * disc_q * _Nd1
    : -(S * sigma * pdf1 * disc_q) / (2 * Math.sqrt(tau))
      + r * K * disc_r * normCDF(-d2)
      - q * S * disc_q * normCDF(-d1);
  const thetaDaily = -theta / 365; // Convert to daily decay (positive = decay)

  // Vega (per 1% vol change)
  const vega = S * disc_q * pdf1 * Math.sqrt(tau) / 100;

  // Probability of expiring ITM
  const probITM = isCall ? _Nd2 : normCDF(-d2);

  return {
    price: price,
    delta: delta,
    gamma: gamma,
    theta: thetaDaily,
    vega: vega,
    probITM: probITM,
  };
}

function renderGreeksExplainer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Greeks Explainer'),
    el('div', { class: 'hint brass' }, 'Black-Scholes-Merton · Live Greeks · Client-side')));

  const _desc = renderPageDescription('greeks');
  if (_desc) wrap.appendChild(_desc);

  // ---- Controls ----
  const defaults = { spot: 100, strike: 100, vol: 20, rate: 2, div: 1, days: 30, type: 'call' };

  const controls = el('div', { class: 'greeks-controls' });
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Spot Price'),
    el('input', { type: 'number', class: 'g-input', min: '0.01', step: '0.1', value: defaults.spot })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Strike Price'),
    el('input', { type: 'number', class: 'g-input', min: '0.01', step: '0.1', value: defaults.strike })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Implied Volatility (%)'),
    el('input', { type: 'number', class: 'g-input', min: '0.1', step: '0.1', value: defaults.vol })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Days to Expiry'),
    el('input', { type: 'number', class: 'g-input', min: '1', step: '1', value: defaults.days })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Interest Rate (%)'),
    el('input', { type: 'number', class: 'g-input', min: '-5', step: '0.1', value: defaults.rate })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Dividend Yield (%)'),
    el('input', { type: 'number', class: 'g-input', min: '0', step: '0.1', value: defaults.div })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Option Type'),
    el('select', { class: 'g-type' },
      el('option', { value: 'call' }, 'Call'),
      el('option', { value: 'put' }, 'Put'))));
  wrap.appendChild(controls);

  // ---- Stats grid ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addGreeksStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addGreeksStat('Option Price',  'price',   '');
  addGreeksStat('Delta',         'delta',   '');
  addGreeksStat('Gamma',         'gamma',   '');
  addGreeksStat('Theta (daily)', 'theta',   '');
  addGreeksStat('Vega (/1% vol)', 'vega',   '');
  addGreeksStat('Prob ITM',      'probITM', '');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'greeks-chart' });
  chartWrap.appendChild(el('canvas', { id: 'greeks-chart' }));
  wrap.appendChild(chartWrap);

  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      v.className = 'stat-value ' + (cls || '');
    }
  }

  function readInputs() {
    const inputs = controls.querySelectorAll('.g-input');
    return {
      spot:  parseFloat(inputs[0].value),
      strike: parseFloat(inputs[1].value),
      vol:   parseFloat(inputs[2].value),
      days:  parseFloat(inputs[3].value),
      rate:  parseFloat(inputs[4].value),
      div:   parseFloat(inputs[5].value),
      type:  controls.querySelector('.g-type').value,
    };
  }

  function fmtDelta(v) {
    if (isNaN(v)) return '—';
    const s = v < 0 ? '' : '+';
    return `${s}${v.toFixed(4)}`;
  }

  function fmtGamma(v) {
    if (isNaN(v)) return '—';
    return `${v.toFixed(6)}`;
  }

  function fmtTheta(v) {
    if (isNaN(v)) return '—';
    const s = v > 0 ? '+' : '';
    return `$${s}${v.toFixed(2)}`;
  }

  function fmtVega(v) {
    if (isNaN(v)) return '—';
    const s = v > 0 ? '+' : '';
    return `$${s}${v.toFixed(2)}`;
  }

  function computeAndRender() {
    const p = readInputs();
    const isCall = p.type === 'call';
    const g = computeGreeks(p.spot, p.strike, p.rate / 100, p.div / 100, p.vol / 100, p.days, isCall);

    setStat('price', fmtUSD(g.price, { sign: false, compact: false }));
    setStat('delta', fmtDelta(g.delta), g.delta > 0 ? 'green' : 'red');
    setStat('gamma', fmtGamma(g.gamma));
    setStat('theta', fmtTheta(g.theta), g.theta > 0 ? 'red' : 'green');
    setStat('vega',  fmtVega(g.vega),  g.vega > 0 ? 'green' : '');
    setStat('probITM', `${(g.probITM * 100).toFixed(1)}%`);

    // Chart: Delta vs Spot
    const center = p.spot;
    const lo = center * 0.5;
    const hi = center * 1.5;
    const N = 100;
    const step = (hi - lo) / N;
    const labels = [], deltas = [], gammas = [];
    for (let i = 0; i <= N; i++) {
      const s = lo + i * step;
      labels.push(s.toFixed(0));
      const dg = computeGreeks(s, p.strike, p.rate / 100, p.div / 100, p.vol / 100, p.days, isCall);
      deltas.push(dg.delta);
      gammas.push(dg.gamma * 100); // scale for visibility
    }

    // Render or update chart
    const canvas = document.getElementById('greeks-chart');
    if (!canvas) return;
    if (charts['greeks-chart']) charts['greeks-chart'].destroy();
    const ctx = canvas.getContext('2d');

    charts['greeks-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Delta',
            data: deltas,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.2,
            yAxisID: 'y',
          },
          {
            label: 'Gamma ×100',
            data: gammas,
            borderColor: CHART_COLORS.blue,
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            tension: 0.2,
            yAxisID: 'y1',
            borderDash: [4, 4],
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 8,
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Underlying Price ($)', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            title: { display: true, text: 'Delta', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'Gamma ×100', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { display: false },
            offset: true,
          },
        },
      },
    });
  }

  // Wire up inputs
  controls.querySelectorAll('.g-input').forEach(i => i.addEventListener('input', computeAndRender));
  controls.querySelector('.g-type').addEventListener('change', computeAndRender);

  // Initial render
  computeAndRender();

  return wrap;
}

// ──────────────────────────────────────────────────────────────
// Stock Screener
// ──────────────────────────────────────────────────────────────
function renderScreener() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Stock Screener'),
    el('div', { class: 'hint brass' }, 'Filter · Sort · Scan (~' + ((state.screenerMeta && state.screenerMeta.ticker_count) || '—') + ' securities)')));

  const _desc = renderPageDescription('screener');
  if (_desc) wrap.appendChild(_desc);

  if (state.loading) {
    wrap.appendChild(el('div', { class: 'loading' }, 'SCANNING UNIVERSE…'));
    return wrap;
  }

  const m = state.screenerMeta || {};
  const rows = (state.screenerResults || { rows: [] }).rows;

  // ── Filter controls ──
  const controls = el('div', { class: 'screener-controls' });
  const f = { ...state.screenerFilters };
  const sortCol = state.screenerSort.col;
  const sortDir = state.screenerSort.dir;

  function numInput(placeholder, field, min, max) {
    const input = el('input', {
      type: 'number', class: 's-input', step: 'any', min, max,
      placeholder, value: f[field] != null ? f[field] : '',
    });
    input.addEventListener('change', (e) => {
      const v = e.target.value;
      f[field] = v === '' ? '' : Number(v);
      state.screenerFilters = f;
      applyScreenerFilters();
    });
    return input;
  }

  function sectorSelect() {
    const opts = m.sectors || [];
    const sel = el('select', { class: 's-select' });
    sel.appendChild(el('option', { value: '' }, 'All Sectors'));
    opts.forEach(s => sel.appendChild(el('option', { value: s, selected: f.sector === s }, s)));
    sel.addEventListener('change', (e) => {
      f.sector = e.target.value;
      state.screenerFilters = f;
      applyScreenerFilters();
    });
    return sel;
  }

  function checkbox(label, field) {
    const id = 'scr-' + field;
    const cb = el('input', { type: 'checkbox', id, checked: !!f[field] });
    cb.addEventListener('change', (e) => {
      f[field] = e.target.checked;
      state.screenerFilters = f;
      applyScreenerFilters();
    });
    return el('label', { class: 's-check', for: id }, cb, el('span', {}, label));
  }

  controls.appendChild(sectorSelect());
  controls.appendChild(numInput('Min $', 'min_price', 0));
  controls.appendChild(numInput('Max $', 'max_price', 0));
  controls.appendChild(numInput('Min Volume', 'min_volume', 0));
  controls.appendChild(numInput('Min Market Cap ($B)', 'min_market_cap', 0));
  controls.appendChild(checkbox('ETF only', 'etf_only'));
  controls.appendChild(checkbox('Stocks only', 'stocks_only'));
  wrap.appendChild(controls);

  // ── Sort chips ──
  const chips = el('div', { class: 's-sort-chips' });
  const sortCols = [
    ['market_cap', 'Market Cap'],
    ['price', 'Price'],
    ['volume', 'Volume'],
    ['pct_change', '% Change'],
    ['ticker', 'Ticker'],
  ];
  sortCols.forEach(([col, label]) => {
    const active = sortCol === col;
    const dir = active ? sortDir : 'desc';
    const cls = 's-chip ' + (active ? (dir === 'desc' ? 's-chip-down' : 's-chip-up') : '');
    const chip = el('div', { class: cls, title: 'Sort by ' + label },
      label, el('span', { class: 's-arrow' }, active ? (dir === 'desc' ? '▼' : '▲') : ''));
    if (active) {
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        setScreenerSort(col, dir === 'desc' ? 'asc' : 'desc');
      });
    }
    chips.appendChild(chip);
  });
  wrap.appendChild(chips);

  // ── Stats row ──
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('As of', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Results', rows.length));
    wrap.appendChild(stats);
  }

  // ── Results table ──
  if (rows.length === 0) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No tickers match the current filters.'));
    return wrap;
  }

  const table = el('table', { class: 's-table' });
  const hdr = el('thead', {},
    el('tr', {},
      th('Ticker'), th('Name'), th('Sector'), th('Price'), th('% Chg'), th('Volume'), th('Mkt Cap')));
  table.appendChild(hdr);

  const tbody = el('tbody', {});
  rows.forEach(r => {
    const chgClass = r.pct_change > 0 ? 'num pos' : (r.pct_change < 0 ? 'num neg' : 'num');
    tbody.appendChild(el('tr', {},
      el('td', { class: 's-ticker' }, r.ticker),
      el('td', {}, r.name),
      el('td', {}, r.sector || '—'),
      el('td', { class: 'num' }, fmtUSD(r.price, { compact: false })),
      el('td', { class: chgClass }, fmtPct(r.pct_change)),
      el('td', { class: 'num' }, fmtNum(r.volume)),
      el('td', { class: 'num' }, (r.market_cap / 1e9).toFixed(1) + 'B'),
    ));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);

  return wrap;
}

function th(label) {
  return el('th', {}, label);
}

// ──────────────────────────────────────────────────────────────
// Famous Trader Quotes
// ──────────────────────────────────────────────────────────────
function renderQuotes() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Famous Trader Quotes'),
    el('div', { class: 'hint brass' }, 'Curated · ' + ((state.quoteMeta && state.quoteMeta.categories) ? state.quoteMeta.categories.length : 0) + ' categories')));

  const _desc = renderPageDescription('quotes');
  if (_desc) wrap.appendChild(_desc);

  // ── Controls ──
  const controls = el('div', { class: 'q-controls' });

  // Category filter
  const cats = (state.quoteMeta && state.quoteMeta.categories) || [];
  const sel = el('select', { class: 'q-select' });
  sel.appendChild(el('option', { value: '', selected: !state.quoteCategory }, 'All Categories'));
  cats.forEach(c => sel.appendChild(el('option', { value: c, selected: state.quoteCategory === c }, c)));
  sel.addEventListener('change', () => changeQuoteCategory(sel.value));
  controls.appendChild(sel);

  // Random button
  const randBtn = el('button', { class: 'btn btn-ghost btn-sm', type: 'button' }, '🎲 Random');
  randBtn.addEventListener('click', loadRandomQuote);
  controls.appendChild(randBtn);

  if (state.quoteList.length > 0 || state.loading) {
    controls.appendChild(el('span', { class: 'q-count hint' },
      state.loading ? 'Loading…' : state.quoteList.length + ' quote' + (state.quoteList.length === 1 ? '' : 's')));
  }
  wrap.appendChild(controls);

  if (state.loading) {
    wrap.appendChild(el('div', { class: 'loading' }, 'FETCHING WISDOM…'));
    return wrap;
  }

  const rows = state.quoteList;
  if (rows.length === 0) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No quotes match the current filter.'));
    return wrap;
  }

  // ── Quote grid ──
  const grid = el('div', { class: 'q-grid' });
  rows.forEach(q => {
    grid.appendChild(el('div', { class: 'q-card' },
      el('div', { class: 'q-mark' }, '"'),
      el('div', { class: 'q-text' }, q.quote),
      el('div', { class: 'q-author-row' },
        el('span', { class: 'q-author' }, q.author),
        q.category ? el('span', { class: 'q-badge' }, q.category) : null,
      ),
      q.source ? el('div', { class: 'q-source' }, q.source) : null,
    ));
  });
  wrap.appendChild(grid);

  return wrap;
}

// ──────────────────────────────────────────────────────────────
// Earnings Revision Momentum
// ──────────────────────────────────────────────────────────────
function renderEarningsRevisions() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Earnings Revision Momentum'),
    el('div', { class: 'hint brass' }, 'Earnings surprise trend across '
      + ((state.ermMeta && state.ermMeta.ticker_count) || '…') + ' tickers')));

  const _desc = renderPageDescription('earningsrevisions');
  if (_desc) wrap.appendChild(_desc);

  if (state.loading) {
    wrap.appendChild(el('div', { class: 'loading' }, 'SCANNING EARNINGS REVISIONS…'));
    return wrap;
  }

  const m = state.ermMeta || {};
  const rows = state.ermRows || [];

  // ── Stats row ──
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('Last updated', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', rows.length));
    stats.appendChild(stat('Improving', m.improving || 0));
    stats.appendChild(stat('Deteriorating', m.deteriorating || 0));
    wrap.appendChild(stats);
  }

  if (rows.length === 0) {
    wrap.appendChild(el('div', { class: 'empty' },
      'No earnings revision data yet. The cron runs daily at 5:30 AM UTC+10.'));
    return wrap;
  }

  // ── Results table ──
  const table = el('table', { class: 'erm-table' });
  const hdr = el('thead', {}, el('tr', {},
    th('Ticker'), th('Report'), th('Avg Revision'),
    th('% Positive'), th('Avg Surprise'), th('Trend'), th('Z-Score')));
  table.appendChild(hdr);

  const tbody = el('tbody', {});
  rows.forEach(r => {
    const trendClass = r.trend === 'improving' ? 'pos'
      : r.trend === 'deteriorating' ? 'neg' : 'dim';
    const zClass = (r.zscore || 0) > 0 ? 'pos'
      : (r.zscore || 0) < 0 ? 'neg' : 'dim';
    tbody.appendChild(el('tr', {},
      el('td', { class: 's-ticker' }, r.ticker),
      el('td', {}, fmtDateISO(r.latest_report_date)),
      el('td', { class: 'num' }, fmtPct(r.avg_revision_4q * 100)),
      el('td', { class: 'num' }, fmtPct(r.pct_positive * 100)),
      el('td', { class: 'num' }, fmtPct(r.avg_surprise_pct)),
      el('td', { class: trendClass }, r.trend),
      el('td', { class: 'num ' + zClass }, (r.zscore || 0).toFixed(2)),
    ));
  });
  table.appendChild(tbody);
  wrap.appendChild(table);

  return wrap;
}

// ──────────────────────────────────────────────────────────────
// Options Explainer (educational reference)
// ──────────────────────────────────────────────────────────────
function renderOptionsExplainer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Options Explainer'),
    el('div', { class: 'hint brass' }, 'Concepts · Strategies · Risks · Client-side')));

  const _desc = renderPageDescription('optionsexplainer');
  if (_desc) wrap.appendChild(_desc);

  function section(title, html) {
    const s = el('div', { class: 'options-section' });
    s.appendChild(el('h3', { class: 'options-section-title' }, title));
    s.appendChild(el('div', { class: 'options-section-body', html }));
    return s;
  }

  function termRow(term, def) {
    return el('div', { class: 'options-term-row' },
      el('span', { class: 'options-term' }, term),
      el('span', { class: 'options-def' }, def));
  }

  function stratCard(name, desc, pnl) {
    const c = el('div', { class: 'options-strat' });
    c.appendChild(el('div', { class: 'options-strat-name' }, name));
    c.appendChild(el('div', { class: 'options-strat-desc' }, desc));
    c.appendChild(el('div', { class: 'options-strat-pnl' }, pnl));
    return c;
  }

  wrap.appendChild(section('What Are Options?',
    '<p>An <strong>option</strong> is a contract giving the buyer the <em>right</em> (not the obligation) to buy or sell an underlying asset at a set price before a set date. The <strong>seller</strong> of an option has the <em>obligation</em> if the buyer exercises.</p>' +
    '<ul><li><strong>Call option</strong> — right to <em>buy</em> (go long) at the strike.</li>' +
    '<li><strong>Put option</strong> — right to <em>sell</em> (go long) at the strike.</li>' +
    '<li><strong>Premium</strong> — the price of the option contract (quoted per share; 1 contract = 100 shares).</li></ul>'));

  const terms = el('div', { class: 'options-terms' });
  terms.appendChild(el('h3', { class: 'options-section-title' }, 'Key Concepts'));
  terms.appendChild(termRow('Strike Price', 'The price at which the underlying can be bought/sold if the option is exercised.'));
  terms.appendChild(termRow('Expiration', 'The last day the option can be exercised. After expiry it becomes worthless.'));
  terms.appendChild(termRow('Moneyness', 'An option is <strong>ITM</strong> (in-the-money) if it has intrinsic value, <strong>OTM</strong> (out-of-the-money) if it has no intrinsic value, and <strong>ATM</strong> (at-the-money) if the strike ≈ spot.'));
  terms.appendChild(termRow('Intrinsic Value', 'Spot − Strike (calls) or Strike − Spot (puts). This is the immediate exercise value.'));
  terms.appendChild(termRow('Time Value', 'Premium − Intrinsic Value. It reflects the probability of ending up ITM before expiry.'));
  terms.appendChild(termRow('American vs European', '<strong>American</strong> can be exercised any time before expiry; <strong>European</strong> only at expiry.'));
  wrap.appendChild(terms);

  wrap.appendChild(section('The Greeks at a Glance',
    '<p>The Greeks measure how an option&rsquo;s price responds to changes in its inputs. Each Greek is the partial derivative of the option price:</p>' +
    '<ul><li><strong>Delta (Δ)</strong> — sensitivity to the underlying&rsquo;s price. Calls: 0→1; Puts: −1→0.</li>' +
    '<li><strong>Gamma (Γ)</strong> — rate of change of Delta. Highest near ATM, at expiry.</li>' +
    '<li><strong>Theta (Θ)</strong> — time decay per day. Options lose value as expiry approaches.</li>' +
    '<li><strong>Vega (ν)</strong> — sensitivity to implied volatility. Long options benefit from rising IV.</li>' +
    '<li><strong>Rho (ρ)</strong> — sensitivity to interest rates (minor for short-dated options).</li></ul>' +
    '<p><a href="#/greeks-explainer">Interactive Greeks Calculator &rarr;</a> · ' +
    '<a href="#/iv-rank">IV Rank & Percentile Tracker</a></p>'));

  wrap.appendChild(section('Time Decay & Volatility',
    '<p><strong>Theta</strong> accelerates non-linearly near expiry — the last 30 days can erase more time value than the first 90. Long option holders are negatively exposed to theta; short sellers (writers) collect it as income.</p>' +
    '<p><strong>Implied Volatility (IV)</strong> is the market&rsquo;s consensus forecast of future volatility, backed out of the option price. When IV is <em>high</em> (IV Rank > 50%), options are expensive to buy — consider selling premium. When IV is <em>low</em> (IV Rank < 30%), options are cheap to buy.</p>'));

  const stratGrid = el('div', { class: 'options-strats' });
  const strats = [
    ['Covered Call', 'Own the stock, sell a call against it. Generates income but caps upside.', 'Max profit = premium + (strike − stock cost), capped upside'],
    ['Protective Put', 'Own the stock, buy a put for downside insurance. Costs premium for protection.', 'Max loss = put premium + (stock cost − strike), downside limited'],
    ['Long Straddle', 'Buy a call + put at the same strike. Profits from big moves either direction.', 'Max loss = total premium paid, unlimited profit'],
    ['Long Strangle', 'Buy an OTM call + OTM put (lower strike). Cheaper but needs bigger move.', 'Max loss = total premium paid, wider breakeven range needed'],
    ['Vertical Spread', 'Sell an OTM option against a further-OTM or ITM option in the same class.', 'Defined risk, income strategy — direction and volatility neutral'],
    ['Iron Condor', 'Sell an OTM strangle, buy further OTM strangle. Income from range-bound action.', 'Max loss = width − credit received, max profit = net credit'],
  ];
  strats.forEach(s => stratGrid.appendChild(stratCard(...s)));
  wrap.appendChild(el('h3', { class: 'options-section-title' }, 'Common Strategies'));
  wrap.appendChild(stratGrid);

  wrap.appendChild(section('Before You Trade',
    '<p><strong>Risk checklist:</strong></p>' +
    '<ul><li>Options can expire worthless — 60–90% of contracts expire out of the money.</li>' +
    '<li>Selling options has <em>unlimited</em> risk on short calls; defined risk on short puts.</li>' +
    '<li>Position size matters: never risk more than 1–2% of capital on a single options trade.</li>' +
    '<li>Consider the <a href="#/position-sizing">Position Sizing Calculator</a> for Kelly-based sizing.</li>' +
    '<li>Check <a href="#/payoff-visualizer">Options Payoff Visualizer</a> to model multi-leg P/L before entry.</li></ul>'));

  return wrap;
}

// ──────────────────────────────────────────────────────────────
// Unusual Activity trackers
// ──────────────────────────────────────────────────────────────
function renderUnusualActivity() {
  const wrap = el('div', { class: 'section' });

  if (!state.uaMeta && !state.uaLatest) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading unusual activity data…'));
    return wrap;
  }

  const m = state.uaMeta || {};
  const latest = state.uaLatest || { rows: [] };
  const rows = latest.rows || [];

  // Stats row
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('As of', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', m.ticker_count || 0, 'brass'));
    stats.appendChild(stat('Extreme', m.extreme_count || 0, 'red'));
    stats.appendChild(stat('High', m.high_count || 0, 'amber'));
    if (m.last_ingestion) {
      stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
    }
    wrap.appendChild(stats);
  }

  // Empty state
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      m.latest_date
        ? 'No flagged activity for this date.'
        : 'No activity data in database yet. Run the Unusual Activity cron to ingest.'));
    return wrap;
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.uaActiveTab === 'latest' ? 'active' : ''),
    onclick: () => { state.uaActiveTab = 'latest'; render(); },
  }, 'Latest'));
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.uaActiveTab === 'history' ? 'active' : ''),
    onclick: () => { state.uaActiveTab = 'history'; render(); },
  }, 'History'));
  wrap.appendChild(tabs);

  if (state.uaActiveTab === 'history') {
    wrap.appendChild(renderUAHistory());
  } else {
    wrap.appendChild(renderUATable(rows));
  }

  return wrap;
}

function fmtNotional(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9)  return '$' + (abs / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6)  return '$' + (abs / 1e6).toFixed(0) + 'M';
  if (abs >= 1e3)  return '$' + (abs / 1e3).toFixed(0) + 'K';
  return '$' + abs.toLocaleString();
}

function renderUATable(rows) {
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Type', 'CP', 'Expiry', 'Strike', 'Vol', 'OI', 'VOI', 'Notional', 'IV', 'Price', 'Vol Ratio', 'Severity', 'Signal'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const isExtreme = r.signal === 'EXTREME';
    const isHigh = r.signal === 'HIGH';
    const signalCls = isExtreme ? 'red' : isHigh ? 'amber' : 'mut';
    const typeLabel = r.activity_type === 'options' ? 'Options' : 'Volume';
    const cpLabel = r.call_put ? r.call_put.toUpperCase() : '—';
    const expiryLabel = r.expiry || '—';
    const strikeLabel = r.strike != null ? r.strike.toFixed(0) : '—';
    const oiLabel = r.open_interest != null ? r.open_interest.toLocaleString() : '—';
    const voiLabel = r.voi_ratio != null ? r.voi_ratio.toFixed(2) : '—';

    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/unusual-activity/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', { class: 'num' }, typeLabel));
    tr.appendChild(el('td', { class: 'num' }, cpLabel));
    tr.appendChild(el('td', { class: 'num mut' }, expiryLabel));
    tr.appendChild(el('td', { class: 'num' }, strikeLabel));
    tr.appendChild(el('td', { class: 'num' }, r.volume ? r.volume.toLocaleString() : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, oiLabel));
    tr.appendChild(el('td', { class: 'num mut' }, voiLabel));
    tr.appendChild(el('td', { class: 'num' }, fmtNotional(r.notional_usd)));
    tr.appendChild(el('td', { class: 'num' }, r.iv_pct != null ? r.iv_pct.toFixed(1) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num' }, r.price != null ? '$' + r.price.toFixed(1) : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, r.vol_ratio != null ? r.vol_ratio.toFixed(1) + 'x' : '—'));
    tr.appendChild(el('td', { class: 'num' }, r.severity_score != null ? r.severity_score.toFixed(0) : '—'));
    tr.appendChild(el('td', { class: 'num ' + signalCls }, r.signal));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}

function renderUAHistory() {
  const h = state.uaHistory;
  const wrap = el('div', { class: 'section' });

  if (!h || !h.rows || !h.rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Select a ticker from the Latest tab to view its activity history.'));
    return wrap;
  }

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/unusual-activity',
    onclick: (e) => { e.preventDefault(); setHash('#/unusual-activity'); },
  }, '← Back'));
  header.appendChild(el('h2', {}, `${h.ticker} — Activity History`));
  wrap.appendChild(header);

  // Summary stats
  const totalActivities = h.rows.length;
  const activityTypes = h.rows.filter(r => r.activity_type === 'options').length;
  const volumeTypes = h.rows.filter(r => r.activity_type === 'volume').length;
  const extremeCount = h.rows.filter(r => r.signal === 'EXTREME').length;
  const highCount = h.rows.filter(r => r.signal === 'HIGH').length;

  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Total Events', totalActivities, 'brass'));
  stats.appendChild(stat('Options', activityTypes, activityTypes > 0 ? 'amber' : 'mut'));
  stats.appendChild(stat('Volume', volumeTypes, volumeTypes > 0 ? 'teal' : 'mut'));
  stats.appendChild(stat('Extreme', extremeCount, 'red'));
  stats.appendChild(stat('High', highCount, highCount > 0 ? 'amber' : 'mut'));
  wrap.appendChild(stats);

  // Activity table
  wrap.appendChild(renderUATable(h.rows));

  // Chart: Severity over time
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '300px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'ua-history-chart' }));
  wrap.appendChild(chartWrap);

  setTimeout(async () => {
    await ensureChartJS();
    const canvas = document.getElementById('ua-history-chart');
    if (!canvas) return;

    const data = h.rows;
    const labels = data.map(r => r.date
      ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}/${String(r.date).slice(2, 4)}`
      : '');
    const severities = data.map(r => r.severity_score || 0);
    const colors = data.map(r =>
      r.signal === 'EXTREME' ? CHART_COLORS.red :
      r.signal === 'HIGH' ? CHART_COLORS.amber :
      CHART_COLORS.blue
    );

    if (charts['ua-history-chart']) charts['ua-history-chart'].destroy();
    charts['ua-history-chart'] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Severity',
          data: severities,
          borderColor: CHART_COLORS.brass,
          backgroundColor: colors.map(c => c + '20'),
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: colors,
          fill: false,
          tension: 0.1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: (ctx) => `Severity: ${ctx.raw.toFixed(0)}`,
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Date', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            title: { display: true, text: 'Severity (0–100)', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
            min: 0,
            max: 100,
          },
        },
      },
    });
  }, 0);

  return wrap;
}

// ---------------- boot ----------------
async function boot() {
  await loadMeta();
  await handleRoute();
}
boot().catch(e => {
  document.getElementById('app').innerHTML =
    '<div class="error">Failed to start: ' + e.message + '</div>';
});
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
*/
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
};

// ---------------- helpers ----------------
async function api(path, params = {}) {
  const url = new URL(API + path, location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
  });
  const r = await fetch(url);
  if (!r.ok) {
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
  if (h === 'short-interest' || h === 'short-interest/') return { view: 'shortinterest' };
  if (h.startsWith('short-interest/')) {
    const rest = h.slice('short-interest/'.length);
    if (rest === 'signals') return { view: 'shortinterest', siTab: 'signals' };
    return { view: 'shortinterest', siTab: 'ticker', siTicker: rest.toUpperCase() };
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

function createPieChart(canvasId, data, options = {}) {
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

function createBarChart(canvasId, data, options = {}) {
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
  try {
    if (r.view === 'funds')        await loadFunds();
    else if (r.view === 'fund')    await loadFund(r.cik, r.tab);
    else if (r.view === 'ticker')  await loadTicker(r.ticker);
    else if (r.view === 'consensus') await loadConsensus();
    else if (r.view === 'sectors') await loadSectors();
    else if (r.view === 'shortinterest') await loadShortInterest(r);
    else if (r.view === 'snapshot') await loadSnapshot();
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

async function loadShortInterest(r) {
  state.error = null;
  state.loading = true;
  state.siActiveTab = r.siTab || (r.siTicker ? 'history' : 'latest');
  try {
    await loadMeta();
    const [meta, signals] = await Promise.all([
      api('/api/si/meta'),
      api('/api/si/signals'),
    ]);
    state.siMeta = meta;
    state.siSignals = signals;
    if (state.siActiveTab === 'latest' || state.siActiveTab === 'signals') {
      const latestResp = await api('/api/si/latest', { min_short: state.siLatest.min_short, limit: state.siLatest.limit });
      state.siLatest.rows = latestResp.rows || latestResp;
      state.siLatest.total = state.siLatest.rows.length;
    }
    if (r.siTicker) {
      state.siActiveTab = 'history';
      state.siTicker = await api('/api/si/tickers/' + r.siTicker);
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
  if (state.view === 'funds')        root.appendChild(renderFunds());
  else if (state.view === 'fund')     root.appendChild(renderFund());
  else if (state.view === 'ticker')   root.appendChild(renderTicker());
  else if (state.view === 'consensus') root.appendChild(renderConsensusView());
  else if (state.view === 'sectors')  root.appendChild(renderSectors());
  else if (state.view === 'shortinterest') root.appendChild(renderShortInterest());
  else if (state.view === 'snapshot')  root.appendChild(renderSnapshot());
}

function renderMasthead() {
  const q = state.meta?.quarters?.[0]?.report_period || '';
  const title = state.view === 'snapshot' ? 'Market Snapshot'
    : state.view === 'shortinterest' ? 'Short Interest'
    : 'Trading Tools';
  return el('div', { class: 'masthead' },
    el('h1', {}, title),
    el('div', { class: 'sub' },
      q ? `Latest quarter: ${q} · ` : '',
      `${state.meta?.counts.filings || 0} filings · `,
      `${state.meta?.counts.funds || 0} funds · `,
      `${state.meta?.counts.unique_tickers?.toLocaleString() || 0} tickers`),
  );
}

function renderNav() {
  const nav = el('div', { class: 'nav' });
  const links = [
    { view: 'snapshot',  label: 'Market Snapshot' },
    { view: 'funds',     label: 'Funds' },
    { view: 'consensus', label: 'Consensus' },
    { view: 'sectors',   label: 'Sectors' },
    { view: 'shortinterest', label: 'Short Interest' },
  ];
  for (const l of links) {
    const href = l.view === 'snapshot' ? '#/snapshot'
      : l.view === 'funds' ? '#/funds'
      : l.view === 'shortinterest' ? '#/short-interest'
      : '#/' + l.view;
    const a = el('a', {
      class: 'nav-link' + (state.view === l.view ? ' active' : ''),
      href: href,
    }, l.label);
    nav.appendChild(a);
  }
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
  function renderPieChart(container, data, labels, options = {}) {
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

  // Date label
  const dateLabel = s.date_str
    ? `${s.date_str.slice(4, 6)}/${s.date_str.slice(6, 8)}/${s.date_str.slice(0, 4)}`
    : '';

  // Headline / caption (moved above the PNG)
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

  // Hero: snapshot image (moved below caption + movers)
  const imgUrl = API + '/snapshots/' + s.png_filename;
  const hero = el('div', { class: 'snapshot-hero' });
  hero.appendChild(el('div', { class: 'snapshot-date' }, 'Market Snapshot \u00b7 ' + dateLabel));
  const img = el('img', {
    src: imgUrl,
    alt: 'Market Snapshot ' + dateLabel,
    style: { maxWidth: '100%', height: 'auto', borderRadius: '4px', border: '1px solid var(--line)' },
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

// ---------------- boot ----------------
async function boot() {
  await loadMeta();
  await handleRoute();
}
boot().catch(e => {
  document.getElementById('app').innerHTML =
    '<div class="error">Failed to start: ' + e.message + '</div>';
});
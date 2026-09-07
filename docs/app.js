/* 13F Tracker — single-page drill-down
   No framework. State is in `state` object; view = render(state).
   Routing via hash: #/  (funds list)
                    #/fund/{cik}  (fund detail)
                    #/fund/{cik}?tab=changes  (changes subview)
                    #/ticker/{ticker}  (cross-fund view)
                    #/consensus  (cross-fund momentum)
*/
'use strict';

const API = 'https://one3f-tracker-wpj6.onrender.com';

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
  if (!h) return { view: 'funds' };
  if (h === 'consensus') return { view: 'consensus' };
  if (h === 'sectors') return { view: 'sectors' };
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
            font: { family: 'var(--mono)', size: 10 },
            color: 'var(--text)',
            padding: 8,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: 'var(--panel)',
          titleColor: 'var(--text)',
          bodyColor: 'var(--text-dim)',
          borderColor: 'var(--line)',
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

async function handleRoute() {
  const r = parseHash();
  state.view = r.view;
  if (r.view === 'funds')        await loadFunds();
  else if (r.view === 'fund')    await loadFund(r.cik, r.tab);
  else if (r.view === 'ticker')  await loadTicker(r.ticker);
  else if (r.view === 'consensus') await loadConsensus();
  else if (r.view === 'sectors') await loadSectors();
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
    state.sectors = await api('/api/sectors');
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
  
  // Destroy any existing charts before re-rendering
  destroyAllCharts();
  
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
}

function renderMasthead() {
  const q = state.meta?.quarters?.[0]?.report_period || '';
  return el('div', { class: 'masthead' },
    el('h1', {}, '13F Tracker'),
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
    { view: 'funds',     label: 'Funds' },
    { view: 'consensus', label: 'Consensus' },
    { view: 'sectors',   label: 'Sectors' },
  ];
  for (const l of links) {
    const a = el('a', {
      class: 'nav-link' + (state.view === l.view ? ' active' : ''),
      href: '#/' + (l.view === 'funds' ? '' : l.view),
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
    href: '#/',
    onclick: (e) => { e.preventDefault(); setHash('#/'); },
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
  if (!s || !s.length) {
    return el('div', { class: 'section' },
      el('div', { class: 'section-header' },
        el('h2', {}, 'Sector Rotation'),
        el('div', { class: 'hint' }, 'Sector data is limited (only ~49 of 11,837 tickers have sector data). Consider this a preview.'),
      ),
      el('div', { class: 'empty' }, 'Insufficient sector data for meaningful analysis. Only ~0.4% of tracked tickers have sector classifications.')
    );
  }

  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Sector Rotation'),
    el('div', { class: 'hint' }, `Sector data covers ${s.length} sectors (limited coverage)`),
  ));

  // Chart + Table container
  const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });

  // Chart canvas
  const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: '300px', maxHeight: '400px' } });
  chartWrap.appendChild(el('canvas', { id: 'sectors-chart' }));
  chartTableWrap.appendChild(chartWrap);

  // Table
  const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: '400px' } });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Sector', 'Holders', 'Total Value', 'Positions'].forEach((h, i) => {
    const cls = i >= 1 ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of s) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, r.sector));
    tr.appendChild(el('td', { class: 'num' }, r.holders.toLocaleString()));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.total_value_usd)));
    tr.appendChild(el('td', { class: 'num' }, r.positions.toLocaleString()));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  chartTableWrap.appendChild(tableWrap);
  wrap.appendChild(chartTableWrap);

  // Create chart after DOM is ready
  setTimeout(() => {
    const labels = s.map(r => r.sector);
    const data = s.map(r => r.total_value_usd);
    createPieChart('sectors-chart', {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: CHART_COLOR_ARRAY.slice(0, labels.length),
        borderWidth: 1,
        borderColor: 'var(--bg)',
      }],
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
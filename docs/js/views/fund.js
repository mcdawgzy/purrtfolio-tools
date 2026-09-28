import { api, loadMeta } from '../core/api.js';
import { CHART_COLOR_ARRAY, createPieChart } from '../core/charts.js';
import { el } from '../core/dom.js';
import { fmtUSD, fmtNum } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

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

export async function loadFund(cik, tab) {
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

// ---- Fund detail view ----
export function renderFund() {
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
  const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: 'min(300px, 100%)', maxHeight: '400px' } });
  chartWrap.appendChild(el('canvas', { id: 'fund-holdings-chart' }));
  chartTableWrap.appendChild(chartWrap);

  // Holdings table
  const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: 'min(400px, 100%)' } });
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

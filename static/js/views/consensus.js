import { api, loadMeta } from '../core/api.js';
import { CHART_COLORS, generateColorShades, createPieChart } from '../core/charts.js';
import { el } from '../core/dom.js';
import { fmtUSD } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

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

export async function loadConsensus() {
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

// ---- Consensus view ----
export function renderConsensusView() {
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
  const buysChartWrap = el('div', { style: { flex: '1 1 350px', minWidth: 'min(300px, 100%)', maxHeight: '400px' } });
  buysChartWrap.appendChild(el('canvas', { id: 'consensus-buys-chart' }));

  // Chart + Table container for sells
  const sellsChartWrap = el('div', { style: { flex: '1 1 350px', minWidth: 'min(300px, 100%)', maxHeight: '400px' } });
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

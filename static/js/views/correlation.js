import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

export async function loadCorrelation(r) {
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

// ===========================================================================
// Correlation Matrix
// ===========================================================================

export function renderCorrelation() {
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

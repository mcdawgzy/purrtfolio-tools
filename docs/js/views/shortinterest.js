import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtPct, fmtFreeFloat } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

export async function loadShortInterest(r) {
  state.error = null;
  state.loading = true;
  // The ticker drill-down renders under the 'history' tab (see renderShortInterest).
  state.siActiveTab = r.siTicker ? 'history' : (r.siTab || 'latest');
  state.siTicker = null;
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
    if (r.siTicker) state.siTicker = tickerResp;
  } catch (e) {
      state.error = e.message;
    } finally {
      state.loading = false;
    }
  }

// ---------------- Short Interest view ----------------
export function renderShortInterest() {
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

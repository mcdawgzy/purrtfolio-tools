import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtDateYMD } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

export async function loadInsider(r) {
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

// ===================== Insider Trading render =====================

export function renderInsider() {
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

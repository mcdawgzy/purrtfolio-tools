import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtPct, fmtDateYMD } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

export async function loadMomentum(r) {
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

// ===========================================================================
// Price Momentum
// ===========================================================================

export function renderMomentum() {
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

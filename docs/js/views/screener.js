import { api, loadMeta } from '../core/api.js';
import { el, stat, th } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtPct, fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { render } from '../router.js';

export async function loadScreener(r) {
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

// ──────────────────────────────────────────────────────────────
// Stock Screener
// ──────────────────────────────────────────────────────────────
export function renderScreener() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Stock Screener'),
    el('div', { class: 'hint brass' }, 'Filter · Sort · Scan (~' + ((state.screenerMeta && state.screenerMeta.ticker_count) || '—') + ' securities)')));

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
  wrap.appendChild(el('div', { class: 'table-wrap' }, table));

  return wrap;
}

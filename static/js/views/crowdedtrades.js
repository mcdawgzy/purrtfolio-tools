import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

// ---------------- Crowded Trades loader ----------------
export async function loadCrowdedTrades(r) {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, latest] = await Promise.all([
      api('/api/ct/meta'),
      api('/api/ct/latest'),
    ]);
    state.ctMeta = meta;
    state.ctLatest = latest;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---- Crowded Trades Scanner view ----
const CT_COLS = ['Ticker', 'Score', 'Signal', 'Direction', 'Short', 'Options', 'IV', 'Momentum', 'PCR', 'Corr'];

const CT_BAND_COLORS = { HIGH: 'red', MEDIUM: 'orange', NEUTRAL: 'mut' };

function signalPill(signal) {
  const cls = CT_BAND_COLORS[signal] || 'mut';
  return el('span', { class: 'status-pill signal-' + signal.toLowerCase() }, signal);
}

function signalColor(score) {
  if (score >= 80) return 'green';
  if (score <= 30) return 'red';
  return '';
}

export function renderCrowdedTradesPage() {
  const wrap = el('div', { class: 'section' });

  if (!state.ctMeta) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No recent scan data available. Run the daily cron job to populate the crowded_trades table.'));
    return wrap;
  }

  const meta = state.ctMeta;
  const scanDate = meta.latest_date || '—';
  const counts = meta.signal_counts || {};
  const total = meta.total_tickers || 0;

  // Top stats
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Scan Date', fmtDateISO(scanDate)));
  stats.appendChild(stat('Tickers', total));
  const highEl = el('span', { class: 'red' }, (counts.HIGH || 0).toString());
  const medEl = el('span', { class: 'brass' }, (counts.MEDIUM || 0).toString());
  const neutEl = el('span', { class: 'mut' }, (counts.NEUTRAL || 0).toString());
  stats.appendChild(stat('Signals', el('span', {}, [highEl, ' HIGH · ', medEl, ' MED · ', neutEl, ' NEUTRAL'])));
  wrap.appendChild(stats);

  // Table
  const rows = (state.ctLatest && state.ctLatest.rows) || [];
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  CT_COLS.forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/ticker/' + r.ticker),
    });

    // Ticker — brass, clickable
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker || '—'));

    // Total Score — bold with color
    const scoreCls = signalColor(r.total_score);
    tr.appendChild(el('td', { class: 'num ' + scoreCls }, r.total_score?.toFixed(1) || '—'));

    // Signal
    tr.appendChild(el('td', { class: 'num' }, signalPill(r.signal || 'NEUTRAL')));

    // Direction
    const dirCls = r.direction === 'bilateral' ? 'brass'
                 : r.direction === 'net-long' ? 'green'
                 : r.direction === 'net-short' ? 'red' : 'mut';
    tr.appendChild(el('td', { class: 'num ' + dirCls }, r.direction || '—'));

    // Component scores (each out of their component max)
    const components = [
      { key: 'short_crowd',     label: 'Short' },
      { key: 'options_crowd',   label: 'Options' },
      { key: 'iv_crowd',        label: 'IV' },
      { key: 'momentum_crowd',  label: 'Momentum' },
      { key: 'pcr_crowd',       label: 'PCR' },
      { key: 'corr_crowd',      label: 'Corr' },
    ];
    // We only show 6 of the 6 components in the table (corr replaces the last slot)
    const shown = components.slice(0, 5); // Short, Options, IV, Momentum, PCR
    shown.forEach(c => {
      const val = r[c.key];
      const cls = val > 0 ? 'num green' : val < 0 ? 'num red' : 'num mut';
      tr.appendChild(el('td', { class: cls }, val != null ? val.toFixed(1) : '—'));
    });
    // Correlation (6th component, replaces the last column)
    const corrVal = r.corr_crowd;
    const corrCls = corrVal > 0 ? 'num green' : corrVal < 0 ? 'num red' : 'num mut';
    tr.appendChild(el('td', { class: corrCls }, corrVal != null ? corrVal.toFixed(1) : '—'));

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

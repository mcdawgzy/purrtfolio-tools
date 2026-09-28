import { api, loadMeta } from '../core/api.js';
import { el, stat, th } from '../core/dom.js';
import { fmtPct, fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';

export async function loadEarningsRevisions(r) {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, rows] = await Promise.all([
      api('/api/earnings-revisions/meta'),
      api('/api/earnings-revisions'),
    ]);
    state.ermMeta = meta;
    state.ermRows = rows;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ──────────────────────────────────────────────────────────────
// Earnings Revision Momentum
// ──────────────────────────────────────────────────────────────
export function renderEarningsRevisions() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Earnings Revision Momentum'),
    el('div', { class: 'hint brass' }, 'Earnings surprise trend across '
      + ((state.ermMeta && state.ermMeta.ticker_count) || '…') + ' tickers')));

  if (state.loading) {
    wrap.appendChild(el('div', { class: 'loading' }, 'SCANNING EARNINGS REVISIONS…'));
    return wrap;
  }

  const m = state.ermMeta || {};
  const rows = state.ermRows || [];

  // ── Stats row ──
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('Last updated', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', rows.length));
    stats.appendChild(stat('Improving', m.improving || 0));
    stats.appendChild(stat('Deteriorating', m.deteriorating || 0));
    wrap.appendChild(stats);
  }

  if (rows.length === 0) {
    wrap.appendChild(el('div', { class: 'empty' },
      'No earnings revision data yet. The cron runs daily at 5:30 AM UTC+10.'));
    return wrap;
  }

  // ── Results table ──
  const table = el('table', { class: 'erm-table' });
  const hdr = el('thead', {}, el('tr', {},
    th('Ticker'), th('Report'), th('Avg Revision'),
    th('% Positive'), th('Avg Surprise'), th('Trend'), th('Z-Score')));
  table.appendChild(hdr);

  const tbody = el('tbody', {});
  rows.forEach(r => {
    const trendClass = r.trend === 'improving' ? 'pos'
      : r.trend === 'deteriorating' ? 'neg' : 'dim';
    const zClass = (r.zscore || 0) > 0 ? 'pos'
      : (r.zscore || 0) < 0 ? 'neg' : 'dim';
    tbody.appendChild(el('tr', {},
      el('td', { class: 's-ticker' }, r.ticker),
      el('td', {}, fmtDateISO(r.latest_report_date)),
      el('td', { class: 'num' }, fmtPct(r.avg_revision_4q * 100)),
      el('td', { class: 'num' }, fmtPct(r.pct_positive * 100)),
      el('td', { class: 'num' }, fmtPct(r.avg_surprise_pct)),
      el('td', { class: trendClass }, r.trend),
      el('td', { class: 'num ' + zClass }, (r.zscore || 0).toFixed(2)),
    ));
  });
  table.appendChild(tbody);
  wrap.appendChild(el('div', { class: 'table-wrap' }, table));

  return wrap;
}

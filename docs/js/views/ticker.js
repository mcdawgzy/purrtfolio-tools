import { api, loadMeta } from '../core/api.js';
import { CHART_COLOR_ARRAY, createPieChart } from '../core/charts.js';
import { el } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtPct, fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

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

export async function loadTicker(ticker) {
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

  // ---- Ticker view ----
export function renderTicker() {
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

  // Short Interest summary section (if available — embedded in API response)
  if (t.latest_si) {
    const si = t.latest_si;
    const siMeta = t.si_meta;
    const changeCls = si.change_pct > 0 ? 'green' : si.change_pct < 0 ? 'red' : '';
    const siSection = el('div', { class: 'section' });
    siSection.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, 'Short Interest'),
      el('a', {
        href: '#/short-interest/' + t.ticker,
        onclick: (e) => { e.preventDefault(); setHash('#/short-interest/' + t.ticker); },
        class: 'hint',
      }, 'Latest settlement: ' + fmtDateISO(si.settlement_date) + ' · View full history →'),
    ));
    const siTableWrap = el('div', { class: 'table-wrap' });
    const siTable = el('table');
    const siThead = el('thead');
    const siTrh = el('tr');
    ['Metric', 'Value'].forEach((h) => {
      siTrh.appendChild(el('th', { class: h === 'Value' ? 'num' : '' }, h));
    });
    siThead.appendChild(siTrh);
    siTable.appendChild(siThead);
    const siTbody = el('tbody');
    const siRows = [
      ['Short $', fmtUSD(si.current_short), ''],
      ['% Change', fmtPct(si.change_pct), changeCls],
      ['Days to Cover', si.days_to_cover?.toFixed(1) || '—', ''],
      ['Avg Daily Vol', fmtNum(si.avg_daily_volume), ''],
      ['Peak Short $', siMeta && siMeta.peak_short ? fmtUSD(siMeta.peak_short) : '—', ''],
    ];
    for (const [label, val, cls] of siRows) {
      const tr = el('tr');
      tr.appendChild(el('td', {}, label));
      tr.appendChild(el('td', { class: 'num ' + cls }, val));
      siTbody.appendChild(tr);
    }
    siTable.appendChild(siTbody);
    siTableWrap.appendChild(siTable);
    siSection.appendChild(siTableWrap);
    wrap.appendChild(siSection);
  }

  // Cross-fund holders table
  const section = el('div', { class: 'section' });
    section.appendChild(el('div', { class: 'section-header' },
      el('h2', {}, `Current holders · ${t.current_holders}`),
      el('div', { class: 'hint' }, t.history?.[0]?.report_period || ''),
    ));

    // Chart + Table container
    const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });

    // Chart canvas
    const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: 'min(300px, 100%)', maxHeight: '400px' } });
    chartWrap.appendChild(el('canvas', { id: 'ticker-holders-chart' }));
    chartTableWrap.appendChild(chartWrap);

    // Table
    const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: 'min(400px, 100%)' } });
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
  ['Strategy', 'Fund', 'Shares', 'Value', 'Status', 'Δ Sh'].forEach((h, i) => {
    const cls = (i >= 2 && i <= 5) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  // is_current is false for funds whose latest filing no longer holds the ticker
  for (const h of (t.holders || []).filter(h => h.is_current !== false)) {
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

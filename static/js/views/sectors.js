import { api } from '../core/api.js';
import { CHART_COLORS, createBarChart, cssVar } from '../core/charts.js';
import { el } from '../core/dom.js';
import { fmtUSD } from '../core/format.js';
import { state } from '../core/state.js';

export async function loadSectors() {
  state.error = null;
  state.loading = true;
  try {
    const r = await api('/api/sectors');
    state.sectors = r.sectors || [];
    state.sectorPeriods = r.periods || { prev_q: null, curr_q: null };
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

export function renderSectors() {
  const s = state.sectors;
  const periods = state.sectorPeriods || {};
  const periodLabel = periods.prev_q && periods.curr_q
    ? `${periods.prev_q} → ${periods.curr_q}`
    : (periods.curr_q ? periods.curr_q : 'sectors');

  if (!s || !s.length) {
    return el('div', { class: 'section' },
      el('div', { class: 'section-header' },
        el('h2', {}, 'Sector Rotation'),
        el('div', { class: 'hint' }, `Period: ${periodLabel}`),
      ),
      el('div', { class: 'empty' }, 'No sector data available for these periods. Sector classifications are still being populated across the full ticker universe.'),
    );
  }

  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Sector Rotation'),
    el('div', { class: 'hint' }, `Period: ${periodLabel} · ${s.length} sectors with holdings in either quarter`),
  ));

  // Chart + Table container
  const chartTableWrap = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', alignItems: 'flex-start' } });

  // Bar chart canvas
  const chartWrap = el('div', { style: { flex: '1 1 350px', minWidth: 'min(300px, 100%)', maxHeight: '400px' } });
  chartWrap.appendChild(el('canvas', { id: 'sectors-chart' }));
  chartTableWrap.appendChild(chartWrap);

  // Table
  const tableWrap = el('div', { class: 'table-wrap', style: { flex: '1 1 400px', minWidth: 'min(400px, 100%)' } });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Sector', 'Prev', 'Current', 'Δ$', 'Δ%', 'Holder Δ', 'Pos Δ'].forEach((h, i) => {
    const cls = i >= 1 ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of s) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, r.sector));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.prev_value_usd)));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.curr_value_usd)));
    const delta = r.value_change_usd;
    const deltaCls = delta > 0 ? 'num green' : (delta < 0 ? 'num red' : 'num');
    tr.appendChild(el('td', { class: deltaCls }, fmtUSD(delta, { sign: true })));
    const pct = r.prev_value_usd && r.prev_value_usd > 0
      ? ((delta / r.prev_value_usd) * 100)
      : (r.curr_value_usd > 0 ? Infinity : 0);
    tr.appendChild(el('td', { class: pct > 0 ? 'num green' : (pct < 0 ? 'num red' : 'num') },
      pct === Infinity ? 'new' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`));
    const hDelta = r.holder_change;
    tr.appendChild(el('td', { class: hDelta > 0 ? 'num green' : (hDelta < 0 ? 'num red' : 'num') },
      hDelta > 0 ? `+${hDelta}` : (hDelta < 0 ? `${hDelta}` : '—')));
    const pDelta = r.position_change;
    tr.appendChild(el('td', { class: pDelta > 0 ? 'num green' : (pDelta < 0 ? 'num red' : 'num') },
      pDelta > 0 ? `+${pDelta}` : (pDelta < 0 ? `${pDelta}` : '—')));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  chartTableWrap.appendChild(tableWrap);
  wrap.appendChild(chartTableWrap);

  // Bar chart of percentage value change per sector
  setTimeout(() => {
    const labels = s.map(r => r.sector);
    const pctData = s.map(r => {
      if (r.prev_value_usd && r.prev_value_usd > 0) {
        return ((r.value_change_usd / r.prev_value_usd) * 100);
      }
      return r.curr_value_usd > 0 ? Infinity : 0;
    });
    const absData = s.map(r => r.value_change_usd);
    const colors = pctData.map(d => d > 0 ? CHART_COLORS.green : (d < 0 ? CHART_COLORS.red : CHART_COLORS.brass));
    createBarChart('sectors-chart', {
      labels: labels,
      datasets: [{
        label: 'Net change (%)',
        data: pctData,
        backgroundColor: colors,
        borderColor: colors.map(c => c),
        borderWidth: 1,
      }],
    }, {
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const idx = ctx.dataIndex;
              return `Δ: ${pctData[idx] > 0 ? '+' : ''}${pctData[idx].toFixed(1)}% (${fmtUSD(absData[idx], { sign: true })})`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: cssVar('--text'),
            font: { size: 10 },
            callback: (v) => v === Infinity ? 'new' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`,
          },
          grid: { color: cssVar('--line') },
        },
        y: {
          ticks: { color: cssVar('--text'), font: { size: 10 } },
          grid: { display: false },
        },
      },
    });
  }, 0);

  return wrap;
}

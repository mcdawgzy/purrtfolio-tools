import { api, loadMeta } from '../core/api.js';
import { ensureChartJS, charts } from '../core/charts.js';
import { el, stat } from '../core/dom.js';
import { fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

// ---------------- IV Rank loader ----------------
export async function loadIVRank(r) {
  state.ivActiveTab = r.ivTab || 'latest';
  state.ivSelectedTicker = r.ivTicker || null;
  state.ivHistoryDays = r.ivHistoryDays || 300;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, latest] = await Promise.all([
      api('/api/iv/meta'),
      api('/api/iv/latest'),
    ]);
    state.ivMeta = meta;
    state.ivLatest = latest;
    if (state.ivSelectedTicker) {
      state.ivHistory = await api(`/api/iv/history/${state.ivSelectedTicker}?days=${state.ivHistoryDays}`);
      state.ivActiveTab = 'history';
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ──────────────────────────────────────────────────────────────
// IV Rank & IV Percentile renderers
// ──────────────────────────────────────────────────────────────
export function renderIVRank() {
  const wrap = el('div', { class: 'section' });

  if (!state.ivMeta && !state.ivLatest) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading IV Rank data…'));
    return wrap;
  }

  const m = state.ivMeta || {};
  const latest = state.ivLatest || { rows: [] };
  const rows = latest.rows || [];

  // Stats row
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('As of', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', m.ticker_count || 0, 'brass'));
    stats.appendChild(stat('Sell-Side', m.high_iv_count || 0, 'green'));
    stats.appendChild(stat('Buy-Side', m.low_iv_count || 0, 'red'));
    if (m.last_ingestion) {
      stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
    }
    wrap.appendChild(stats);
  }

  // Empty state
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      m.latest_date
        ? 'No IV data available for this date.'
        : 'No IV data in database yet. Run the IV Rank cron to ingest.'));
    return wrap;
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.ivActiveTab === 'latest' ? 'active' : ''),
    onclick: () => { state.ivActiveTab = 'latest'; render(); },
  }, 'Latest'));
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.ivActiveTab === 'history' ? 'active' : ''),
    onclick: () => { state.ivActiveTab = 'history'; render(); },
  }, 'History'));
  wrap.appendChild(tabs);

  if (state.ivActiveTab === 'history') {
    wrap.appendChild(renderIVRankHistory());
  } else {
    wrap.appendChild(renderIVRankTable());
  }

  return wrap;
}

function renderIVRankTable() {
  const rows = state.ivLatest?.rows || [];
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');

  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'IV', 'IV Rank', 'IV %', 'Signal', '52w Range', 'Days'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const isHigh = r.signal === 'HIGH_IV';
    const isLow = r.signal === 'LOW_IV';
    const signalCls = isHigh ? 'green' : isLow ? 'red' : 'mut';
    const signalLabel = isHigh ? 'Sell-Side' : isLow ? 'Buy-Side' : 'Neutral';

    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/iv-rank/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', { class: 'num' }, r.iv ? r.iv.toFixed(1) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num' },
      r.iv_rank != null ? r.iv_rank.toFixed(0) : '—'));
    tr.appendChild(el('td', { class: 'num' },
      r.iv_pctile != null ? r.iv_pctile.toFixed(0) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num ' + signalCls }, signalLabel));
    const rangeStr = (r.iv_min_52w && r.iv_max_52w)
      ? `${r.iv_min_52w.toFixed(1)}%–${r.iv_max_52w.toFixed(1)}%` : '—';
    tr.appendChild(el('td', { class: 'num mut' }, rangeStr));
    tr.appendChild(el('td', { class: 'num mut' }, r.days_52w || 0));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}

function renderIVRankHistory() {
  const h = state.ivHistory;
  const wrap = el('div', { class: 'section' });

  if (!h || !h.rows || !h.rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Select a ticker from the Latest tab to view its IV history.'));
    return wrap;
  }

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/iv-rank',
    onclick: (e) => { e.preventDefault(); setHash('#/iv-rank'); },
  }, '← Back'));
  header.appendChild(el('h2', {}, `${h.ticker} — IV History`));
  wrap.appendChild(header);

  // Chart
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '400px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'iv-history-chart' }));
  wrap.appendChild(chartWrap);

  setTimeout(async () => {
    await ensureChartJS();
    const rows = h.rows;
    const labels = rows.map(r => r.date
      ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}/${String(r.date).slice(2, 4)}`
      : '');
    const ivs = rows.map(r => r.iv);
    const ranks = rows.map(r => r.iv_rank);

    // Moving averages
    const ma5 = [], ma20 = [];
    for (let i = 0; i < rows.length; i++) {
      const w5 = ivs.slice(Math.max(0, i - 4), i + 1);
      const w20 = ivs.slice(Math.max(0, i - 19), i + 1);
      ma5.push(w5.reduce((a, b) => a + b, 0) / w5.length);
      ma20.push(w20.reduce((a, b) => a + b, 0) / w20.length);
    }

    const ctx = document.getElementById('iv-history-chart');
    if (!ctx) return;
    if (charts['iv-history-chart']) charts['iv-history-chart'].destroy();
    charts['iv-history-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'IV',
            data: ivs,
            borderColor: '#C9A24E',
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
          {
            label: 'IV Rank',
            data: ranks,
            borderColor: '#3B82F6',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            yAxisID: 'y1',
          },
          {
            label: '5-Day MA',
            data: ma5,
            borderColor: '#C9A24E',
            borderWidth: 1,
            borderDash: [3, 3],
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
          {
            label: '20-Day MA',
            data: ma20,
            borderColor: '#2E9E6B',
            borderWidth: 1,
            borderDash: [3, 3],
            pointRadius: 0,
            fill: false,
            yAxisID: 'y',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#E8EBEF', font: { size: 10 } } },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 12,
            callbacks: {
              label: (ctx) => {
                const v = ctx.raw;
                if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
                const lbl = ctx.dataset.label;
                if (lbl === 'IV') return `IV: ${v.toFixed(1)}%`;
                if (lbl === 'IV Rank') return `Rank: ${v.toFixed(0)}`;
                return `${lbl}: ${v.toFixed(1)}`;
              },
            },
          },
        },
        scales: {
          y: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'IV %', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y1: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'IV Rank', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { drawBorder: false, color: 'rgba(30,42,56,0.3)' },
            min: 0,
            max: 100,
          },
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }, 0);

  return wrap;
}

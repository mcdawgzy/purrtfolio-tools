import { api, loadMeta } from '../core/api.js';
import { ensureChartJS, charts } from '../core/charts.js';
import { el, stat } from '../core/dom.js';
import { fmtNum, fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { render } from '../router.js';

// ---------------- Put/Call Ratio loader ----------------
export async function loadPutCallRatio(r) {
  state.pcrActiveTab = r.pcrTab || 'latest';
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    // Batch all three calls in parallel
    const [meta, latest, signals] = await Promise.all([
      api('/api/pcr/meta'),
      api('/api/pcr/latest'),
      api('/api/pcr/signals'),
    ]);
    state.pcrMeta = meta;
    state.pcrLatest = latest;
    state.pcrSignals = signals;
    if (state.pcrActiveTab === 'history') await loadPcrHistory();
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadPcrHistory() {
  state.pcrHistory = await api('/api/pcr/history/' + encodeURIComponent(state.pcrHistorySeries || 'TOTAL'),
    { days: state.pcrHistoryDays });
}

// Load (or reload) the PCR history for the selected series, then re-render.
async function refreshPcrHistory() {
  state.loading = true; state.error = null; render();
  try { await loadPcrHistory(); }
  catch (e) { state.error = e.message; }
  finally { state.loading = false; render(); }
}

// ── Put/Call Ratio series labels ──
const PCR_SERIES_LABELS = {
  'TOTAL':   'Total Market',
  'INDEX':   'Index Options',
  'EQUITY':  'Equity Options',
  'ETP':     'ETP Options',
  'VIX':     'VIX Options',
  'SPX_SPXW':'SPX+SPXW',
  'OEX':     'OEX',
  'MRUT':    'MRUT',
};

function pcrSignalClass(signal) {
  if (signal === 'EXTREME_BULLISH' || signal === 'BULLISH') return 'green';
  if (signal === 'EXTREME_BEARISH' || signal === 'BEARISH') return 'red';
  return 'dim';
}

function pcrSignalLabel(signal) {
  if (!signal) return '—';
  const map = {
    'EXTREME_BULLISH': 'Extreme Bullish',
    'BULLISH':         'Bullish',
    'BEARISH':         'Bearish',
    'EXTREME_BEARISH': 'Extreme Bearish',
    'NEUTRAL':         'Neutral',
  };
  return map[signal] || signal.replace(/_/g, ' ');
}

export function renderPutCallRatio() {
  const wrap = el('div', { class: 'section' });

  if (!state.pcrLatest && !state.pcrMeta) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading put/call ratio data…'));
    return wrap;
  }

  const latest = state.pcrLatest || { latest_date: '', rows: [] };
  const m = state.pcrMeta || {};

  // Stats row
  const dateFmt = latest.latest_date
    ? `${String(latest.latest_date).slice(5, 7)}/${String(latest.latest_date).slice(8, 10)}/${String(latest.latest_date).slice(0, 4)}`
    : '—';
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('As of', dateFmt));
  stats.appendChild(stat('Series', m.series_count || latest.rows?.length || 0, 'brass'));
  stats.appendChild(stat('Signals', m.extreme_count ?? state.pcrSignals?.signals?.length ?? 0));
  // /api/pcr/meta returns last_update as an ingestion-log object
  const luRaw = m.last_update && (m.last_update.started_at || m.last_update.date || m.last_update);
  if (luRaw && typeof luRaw === 'string') {
    const lu = `${luRaw.slice(5, 7)}/${luRaw.slice(8, 10)}/${luRaw.slice(0, 4)}`;
    stats.appendChild(stat('Last Update', lu, 'brass'));
  }
  wrap.appendChild(stats);

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabLabels = [
    { key: 'latest',   label: 'Latest' },
    { key: 'signals',  label: 'Signals' },
    { key: 'history',  label: 'History' },
  ];
  for (const t of tabLabels) {
    tabs.appendChild(el('div', {
      class: 'tab' + (state.pcrActiveTab === t.key ? ' active' : ''),
      onclick: () => {
        state.pcrActiveTab = t.key;
        const wantSeries = state.pcrHistorySeries || 'TOTAL';
        if (t.key === 'history' && (!state.pcrHistory || state.pcrHistory.series !== wantSeries)) refreshPcrHistory();
        else render();
      },
    }, t.label));
  }
  wrap.appendChild(tabs);

  // Tab bodies
  if (state.pcrActiveTab === 'latest') {
    wrap.appendChild(renderPcrLatest());
  } else if (state.pcrActiveTab === 'signals') {
    wrap.appendChild(renderPcrSignals());
  } else if (state.pcrActiveTab === 'history') {
    wrap.appendChild(renderPcrHistory());
  }

  return wrap;
}

function renderPcrLatest() {
  const rows = state.pcrLatest?.rows || [];
  const wrap = el('div', { class: 'table-wrap' });

  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No put/call ratio data available yet.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Series', 'P/C Ratio', '5-Day MA', '20-Day MA', 'Vol', 'Open Interest', 'Signal'].forEach((h, i) => {
    const cls = (i >= 1 && i <= 3) ? 'num' : (i === 5 || i === 6) ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, PCR_SERIES_LABELS[row.series] || row.series));

    const ratioVal = row.ratio != null ? row.ratio.toFixed(3) : '—';
    const ratioCls = row.ratio != null
      ? (row.ratio > 1.0 ? 'num red' : row.ratio < 0.7 ? 'num green' : 'num')
      : 'num';
    tr.appendChild(el('td', { class: ratioCls }, ratioVal));

    tr.appendChild(el('td', { class: 'num mut' }, row.ma5 != null ? row.ma5.toFixed(3) : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, row.ma20 != null ? row.ma20.toFixed(3) : '—'));

    const vol = row.total_volume != null ? fmtNum(row.total_volume) : '—';
    tr.appendChild(el('td', { class: 'num mut' }, vol));

    const oi = row.total_oi != null ? fmtNum(row.total_oi) : '—';
    tr.appendChild(el('td', { class: 'num mut' }, oi));

    const signal = row.signal || 'NEUTRAL';
    tr.appendChild(el('td', { class: 'num ' + pcrSignalClass(signal) }, pcrSignalLabel(signal)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  // Interpretation legend
  wrap.appendChild(el('div', { class: 'hint', style: { marginTop: '12px', fontSize: '12px' } },
    'Interpretation: High ratio (>1.2) = bearish sentiment / contrarian buy · Low ratio (<0.6) = bullish complacency / contrarian sell · Equity PCR < 0.6 often coincides with market tops.'));

  return wrap;
}

function renderPcrSignals() {
  const s = state.pcrSignals || { latest_date: '', signals: [] };
  const wrap = el('div', { class: 'table-wrap' });

  if (!s.signals || !s.signals.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No extreme readings in the recent window.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Series', 'Ratio', '5-Day MA', 'Z-Score', 'Signal'].forEach((h, i) => {
    const cls = i >= 2 ? 'num' : '';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of s.signals) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: 'mono' }, fmtDateISO(row.date)));
    tr.appendChild(el('td', {}, PCR_SERIES_LABELS[row.series] || row.series));

    const ratioCls = row.ratio > 1.0 ? 'num red' : row.ratio < 0.7 ? 'num green' : 'num';
    tr.appendChild(el('td', { class: ratioCls }, row.ratio.toFixed(3)));

    tr.appendChild(el('td', { class: 'num mut' }, row.ma5 != null ? row.ma5.toFixed(3) : '—'));

    const z = row.z_score != null ? (row.z_score > 0 ? '+' : '') + row.z_score.toFixed(2) : '—';
    const zCls = row.z_score > 2 ? 'num red' : row.z_score < -2 ? 'num green' : 'num mut';
    tr.appendChild(el('td', { class: zCls }, z));

    tr.appendChild(el('td', { class: 'num ' + pcrSignalClass(row.signal) }, pcrSignalLabel(row.signal)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  return wrap;
}

function renderPcrHistory() {
  const h = state.pcrHistory;
  const wrap = el('div', { class: 'section' });

  // Series selector
  const selWrap = el('div', { class: 'filters' });
  selWrap.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Series:'),
    el('select', {
      onchange: (e) => {
        state.pcrHistorySeries = e.target.value;
        refreshPcrHistory();
      },
    }, ...['TOTAL', 'INDEX', 'EQUITY', 'ETP', 'VIX'].map(s =>
      el('option', { value: s, selected: s === (state.pcrHistorySeries || 'TOTAL') }, PCR_SERIES_LABELS[s] || s)
    ))));
  wrap.appendChild(selWrap);

  if (!h || !h.rows || !h.rows.length) {
    if (!state.loading) wrap.appendChild(el('div', { class: 'empty' }, 'No historical data available.'));
    return wrap;
  }

  // Chart container
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '400px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'pcr-history-chart' }));
  wrap.appendChild(chartWrap);

  // Render chart after DOM ready
  setTimeout(async () => {
    await ensureChartJS();
    const rows = h.rows;
    const labels = rows.map(r => r.date ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}` : '');
    const ratios = rows.map(r => r.ratio);
    const ma5 = rows.map(r => r.ma5);

    const ctx = document.getElementById('pcr-history-chart');
    if (!ctx) return;  // view re-rendered/navigated away before Chart.js loaded
    if (charts['pcr-history-chart']) charts['pcr-history-chart'].destroy();
    charts['pcr-history-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Put/Call Ratio',
            data: ratios,
            borderColor: '#3B82F6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
          },
          {
            label: '5-Day MA',
            data: ma5,
            borderColor: '#C9A24E',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#E8EBEF', font: { size: 10 } },
          },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 12,
            callbacks: {
              label: (ctx) => {
                const idx = ctx.dataIndex;
                const v = ctx.raw;
                if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
                const band = v >= 1.0 ? '#C7564A' : v <= 0.6 ? '#2E9E6B' : '#C9A24E';
                const label = ctx.dataset.label || '';
                const cls = label.includes('MA') ? '' : (v > 1.0 ? 'Bearish' : v < 0.6 ? 'Bullish' : 'Neutral');
                return `${label}: ${v.toFixed(3)} ${cls}`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }, 0);

  return wrap;
}

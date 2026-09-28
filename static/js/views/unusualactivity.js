import { api, loadMeta } from '../core/api.js';
import { ensureChartJS, CHART_COLORS, charts } from '../core/charts.js';
import { el, stat } from '../core/dom.js';
import { fmtDateISO, fmtNotional } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash, render } from '../router.js';

// ---------------- Unusual Activity loader ----------------
export async function loadUnusualActivity(r) {
  state.uaActiveTab = r.uaTab || 'latest';
  state.uaSelectedTicker = r.uaTicker || null;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, latest] = await Promise.all([
      api('/api/ua/meta'),
      api('/api/ua/latest'),
    ]);
    state.uaMeta = meta;
    state.uaLatest = latest;
    if (state.uaSelectedTicker) {
      state.uaHistory = await api(`/api/ua/history/${state.uaSelectedTicker}`);
      state.uaActiveTab = 'history';
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ──────────────────────────────────────────────────────────────
// Unusual Activity trackers
// ──────────────────────────────────────────────────────────────
export function renderUnusualActivity() {
  const wrap = el('div', { class: 'section' });

  if (!state.uaMeta && !state.uaLatest) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading unusual activity data…'));
    return wrap;
  }

  const m = state.uaMeta || {};
  const latest = state.uaLatest || { rows: [] };
  const rows = latest.rows || [];

  // Stats row
  if (m.latest_date) {
    const stats = el('div', { class: 'stats' });
    stats.appendChild(stat('As of', fmtDateISO(m.latest_date)));
    stats.appendChild(stat('Tickers', m.ticker_count || 0, 'brass'));
    stats.appendChild(stat('Extreme', m.extreme_count || 0, 'red'));
    stats.appendChild(stat('High', m.high_count || 0, 'amber'));
    if (m.last_ingestion) {
      stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
    }
    wrap.appendChild(stats);
  }

  // Empty state
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      m.latest_date
        ? 'No flagged activity for this date.'
        : 'No activity data in database yet. Run the Unusual Activity cron to ingest.'));
    return wrap;
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.uaActiveTab === 'latest' ? 'active' : ''),
    onclick: () => { state.uaActiveTab = 'latest'; render(); },
  }, 'Latest'));
  tabs.appendChild(el('div', {
    class: 'tab ' + (state.uaActiveTab === 'history' ? 'active' : ''),
    onclick: () => { state.uaActiveTab = 'history'; render(); },
  }, 'History'));
  wrap.appendChild(tabs);

  if (state.uaActiveTab === 'history') {
    wrap.appendChild(renderUAHistory());
  } else {
    wrap.appendChild(renderUATable(rows));
  }

  return wrap;
}

function renderUATable(rows) {
  const tableWrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Ticker', 'Type', 'CP', 'Expiry', 'Strike', 'Vol', 'OI', 'VOI', 'Notional', 'IV', 'Price', 'Vol Ratio', 'Severity', 'Signal'].forEach((h, i) => {
    trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const r of rows) {
    const isExtreme = r.signal === 'EXTREME';
    const isHigh = r.signal === 'HIGH';
    const signalCls = isExtreme ? 'red' : isHigh ? 'amber' : 'mut';
    const typeLabel = r.activity_type === 'options' ? 'Options' : 'Volume';
    const cpLabel = r.call_put ? r.call_put.toUpperCase() : '—';
    const expiryLabel = r.expiry || '—';
    const strikeLabel = r.strike != null ? r.strike.toFixed(0) : '—';
    const oiLabel = r.open_interest != null ? r.open_interest.toLocaleString() : '—';
    const voiLabel = r.voi_ratio != null ? r.voi_ratio.toFixed(2) : '—';

    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/unusual-activity/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', { class: 'num' }, typeLabel));
    tr.appendChild(el('td', { class: 'num' }, cpLabel));
    tr.appendChild(el('td', { class: 'num mut' }, expiryLabel));
    tr.appendChild(el('td', { class: 'num' }, strikeLabel));
    tr.appendChild(el('td', { class: 'num' }, r.volume ? r.volume.toLocaleString() : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, oiLabel));
    tr.appendChild(el('td', { class: 'num mut' }, voiLabel));
    tr.appendChild(el('td', { class: 'num' }, fmtNotional(r.notional_usd)));
    tr.appendChild(el('td', { class: 'num' }, r.iv_pct != null ? r.iv_pct.toFixed(1) + '%' : '—'));
    tr.appendChild(el('td', { class: 'num' }, r.price != null ? '$' + r.price.toFixed(1) : '—'));
    tr.appendChild(el('td', { class: 'num mut' }, r.vol_ratio != null ? r.vol_ratio.toFixed(1) + 'x' : '—'));
    tr.appendChild(el('td', { class: 'num' }, r.severity_score != null ? r.severity_score.toFixed(0) : '—'));
    tr.appendChild(el('td', { class: 'num ' + signalCls }, r.signal));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  return tableWrap;
}

function renderUAHistory() {
  const h = state.uaHistory;
  const wrap = el('div', { class: 'section' });

  if (!h || !h.rows || !h.rows.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Select a ticker from the Latest tab to view its activity history.'));
    return wrap;
  }

  // Drill header
  const header = el('div', { class: 'drill-header' });
  header.appendChild(el('a', {
    class: 'back',
    href: '#/unusual-activity',
    onclick: (e) => { e.preventDefault(); setHash('#/unusual-activity'); },
  }, '← Back'));
  header.appendChild(el('h2', {}, `${h.ticker} — Activity History`));
  wrap.appendChild(header);

  // Summary stats
  const totalActivities = h.rows.length;
  const activityTypes = h.rows.filter(r => r.activity_type === 'options').length;
  const volumeTypes = h.rows.filter(r => r.activity_type === 'volume').length;
  const extremeCount = h.rows.filter(r => r.signal === 'EXTREME').length;
  const highCount = h.rows.filter(r => r.signal === 'HIGH').length;

  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Total Events', totalActivities, 'brass'));
  stats.appendChild(stat('Options', activityTypes, activityTypes > 0 ? 'amber' : 'mut'));
  stats.appendChild(stat('Volume', volumeTypes, volumeTypes > 0 ? 'teal' : 'mut'));
  stats.appendChild(stat('Extreme', extremeCount, 'red'));
  stats.appendChild(stat('High', highCount, highCount > 0 ? 'amber' : 'mut'));
  wrap.appendChild(stats);

  // Activity table
  wrap.appendChild(renderUATable(h.rows));

  // Chart: Severity over time
  const chartWrap = el('div', { style: { flex: '1 1 600px', height: '300px', width: '100%' } });
  chartWrap.appendChild(el('canvas', { id: 'ua-history-chart' }));
  wrap.appendChild(chartWrap);

  setTimeout(async () => {
    await ensureChartJS();
    const canvas = document.getElementById('ua-history-chart');
    if (!canvas) return;

    const data = h.rows;
    const labels = data.map(r => r.date
      ? `${String(r.date).slice(5, 7)}/${String(r.date).slice(8, 10)}/${String(r.date).slice(2, 4)}`
      : '');
    const severities = data.map(r => r.severity_score || 0);
    const colors = data.map(r =>
      r.signal === 'EXTREME' ? CHART_COLORS.red :
      r.signal === 'HIGH' ? CHART_COLORS.amber :
      CHART_COLORS.blue
    );

    if (charts['ua-history-chart']) charts['ua-history-chart'].destroy();
    charts['ua-history-chart'] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Severity',
          data: severities,
          borderColor: CHART_COLORS.brass,
          backgroundColor: colors.map(c => c + '20'),
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: colors,
          fill: false,
          tension: 0.1,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#11161D',
            titleColor: '#E8EBEF',
            bodyColor: '#7E8A9A',
            borderColor: '#1E2A38',
            borderWidth: 1,
            padding: 8,
            callbacks: {
              label: (ctx) => `Severity: ${ctx.raw.toFixed(0)}`,
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Date', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            title: { display: true, text: 'Severity (0–100)', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
            min: 0,
            max: 100,
          },
        },
      },
    });
  }, 0);

  return wrap;
}

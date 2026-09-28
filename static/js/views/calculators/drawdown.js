import { ensureChartJS, CHART_COLORS, charts, destroyAllCharts } from '../../core/charts.js';
import { el, stat } from '../../core/dom.js';
import { fmtUSD } from '../../core/format.js';

// ---------------- Drawdown Simulator (Monte Carlo) ----------------
export function renderDrawdownSimulator() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  // ---- Header ----
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Drawdown Simulator'),
    el('div', { class: 'hint' }, 'Monte Carlo · Kelly-compatible')));

  // ---- Inputs ----
  const ctrl = el('div', { class: 'sim-controls' });

  const accountInput = el('input', { type: 'number', id: 'ds-account', min: '0', step: '1000', value: '100000' });
  const winRateInput = el('input', { type: 'number', id: 'ds-winrate', min: '0', max: '100', step: '0.5', value: '60' });
  const rrrInput     = el('input', { type: 'number', id: 'ds-rrr', min: '0.01', step: '0.1', value: '2.0' });
  const riskInput    = el('input', { type: 'number', id: 'ds-risk', min: '0', max: '100', step: '0.5', value: '2' });
  const tradesInput  = el('input', { type: 'number', id: 'ds-trades', min: '1', max: '1000', step: '1', value: '250' });
  const simsInput    = el('input', { type: 'number', id: 'ds-sims', min: '10', max: '200', step: '10', value: '50' });

  /** Helper: build a labelled input row with optional unit suffix */
  function addCtrl(label, inputEl, unit) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', { for: inputEl.id }, label));
    const row = el('div', { class: 'calc-input-row' });
    row.appendChild(inputEl);
    if (unit) row.appendChild(el('span', { class: 'unit' }, unit));
    field.appendChild(row);
    return field;
  }

  ctrl.appendChild(addCtrl('Account size', accountInput));
  ctrl.appendChild(addCtrl('Win rate', winRateInput, '%'));
  ctrl.appendChild(addCtrl('Reward : Risk', rrrInput));
  ctrl.appendChild(addCtrl('Risk per trade', riskInput, '%'));
  ctrl.appendChild(addCtrl('Trades', tradesInput));
  ctrl.appendChild(addCtrl('Simulations', simsInput));
  wrap.appendChild(ctrl);

  // ---- Stats panel ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addStat('Avg final value',  'avgFinal', 'brass');
  addStat('Median final',     'median');
  addStat('Avg max drawdown', 'avgDD',    'red');
  addStat('Prob >20% DD',     'probDD',   'amber');
  addStat('Prob of ruin',     'probRuin', 'red');
  addStat('Worst 5%',         'worst5');
  addStat('Avg CAGR',         'cagr',     'green');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'sim-chart' });
  chartWrap.appendChild(el('canvas', { id: 'ds-equity-chart' }));
  wrap.appendChild(chartWrap);

  // ---- Formula ----
  wrap.appendChild(el('p', { class: 'calc-formula' },
    'Trade: win → account × (1 + r×b),  loss → account × (1 − r)  |  r = risk %, b = reward:risk  |  252 trading days/year'));

  // ---- Helpers ----
  /** Set stat value text, optionally overriding the value color class */
  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      if (cls !== undefined) v.className = 'stat-value ' + cls;
    }
  }

  // ---- Simulation ----
  async function runSim() {
    const account   = parseFloat(accountInput.value)  || 100000;
    const winRate   = parseFloat(winRateInput.value)  || 60;
    const rrr       = parseFloat(rrrInput.value)        || 2;
    const riskPct   = parseFloat(riskInput.value)     || 2;
    const numTrades = Math.max(1, parseInt(tradesInput.value) || 250);
    const numSims   = Math.min(200, Math.max(10, parseInt(simsInput.value) || 50));

    const p = winRate / 100;
    const b = rrr;
    const r = riskPct / 100;
    const ruinThreshold = account * 0.5;

    const finals = [];
    const maxDDs = [];
    const allPaths = [];

    for (let s = 0; s < numSims; s++) {
      let cap = account;
      let peak = cap;
      let maxDD = 0;
      const path = [cap];

      for (let t = 0; t < numTrades; t++) {
        if (Math.random() < p) {
          cap *= (1 + r * b);
        } else {
          cap *= (1 - r);
        }
        path.push(cap);
        if (cap > peak) peak = cap;
        const dd = (peak - cap) / peak;
        if (dd > maxDD) maxDD = dd;
      }

      finals.push(cap);
      maxDDs.push(maxDD * 100);
      allPaths.push(path);
    }

    // ---- Aggregate stats ----
    const sortedFinals = [...finals].sort((a, b) => a - b);
    const worst5th    = sortedFinals[Math.floor(numSims * 0.05) || 0];
    const medianFinal = sortedFinals[Math.floor(numSims * 0.5)];
    const cagrs       = finals.map(f => Math.pow(f / account, 252 / numTrades) - 1);
    const avgCagr     = cagrs.reduce((a, v) => a + v, 0) / numSims;
    const avgFinal    = finals.reduce((a, v) => a + v, 0) / numSims;
    const avgMaxDD    = maxDDs.reduce((a, v) => a + v, 0) / numSims;
    const probDD      = maxDDs.filter(dd => dd > 20).length / numSims * 100;
    const probRuin    = finals.filter(f => f < ruinThreshold).length / numSims * 100;

    setStat('avgFinal', fmtUSD(avgFinal, { compact: false }));
    setStat('median',   fmtUSD(medianFinal, { compact: false }));
    setStat('avgDD',    avgMaxDD.toFixed(1) + '%', avgMaxDD > 20 ? 'red' : avgMaxDD > 10 ? 'amber' : '');
    setStat('probDD',   probDD.toFixed(0) + '%',   probDD > 50 ? 'red' : probDD > 0 ? 'amber' : 'green');
    setStat('probRuin', probRuin.toFixed(0) + '%', probRuin > 0 ? 'red' : 'green');
    setStat('worst5',   fmtUSD(worst5th, { compact: false }));
    setStat('cagr',     (avgCagr * 100).toFixed(1) + '%', avgCagr > 0 ? 'green' : avgCagr < 0 ? 'red' : '');

    // ---- Chart ----
    const chartPaths = allPaths.slice(0, Math.min(20, numSims));

    // Compute median path across all sims
    const medianPath = [];
    for (let t = 0; t <= numTrades; t++) {
      const vals = allPaths.map(pa => pa[t] || account).sort((a, b) => a - b);
      medianPath.push(vals[Math.floor(vals.length / 2)]);
    }

    const labelStep = Math.max(1, Math.floor(numTrades / 10));
    const labels = Array.from({ length: numTrades + 1 }, (_, i) =>
      i % labelStep === 0 ? String(i) : '');

    const canvas = document.getElementById('ds-equity-chart');
    if (!canvas) return;
    if (charts['ds-equity-chart']) charts['ds-equity-chart'].destroy();

    await ensureChartJS();

    const ctx = canvas.getContext('2d');
    charts['ds-equity-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          // Individual sim paths (dim)
          ...chartPaths.map((path, i) => ({
            label: 'Sim ' + (i + 1),
            data: path,
            borderColor: 'rgba(126, 138, 154, 0.25)',
            borderWidth: 1,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          })),
          // Starting capital reference
          {
            label: 'Starting capital',
            data: Array(numTrades + 1).fill(account),
            borderColor: 'rgba(126, 138, 154, 0.5)',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
          },
          // Median path (brass, bold)
          {
            label: 'Median',
            data: medianPath,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2.5,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          },
        ],
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
              label: (c) => '$' + Math.round(c.raw).toLocaleString(),
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            beginAtZero: false,
            ticks: {
              color: '#7E8A9A',
              font: { size: 9 },
              callback: (v) => '$' + Math.round(v).toLocaleString(),
            },
            grid: { color: '#1E2A38' },
          },
        },
      },
    });
  }

  // Attach listeners
  [accountInput, winRateInput, rrrInput, riskInput, tradesInput, simsInput]
    .forEach(inp => inp.addEventListener('input', runSim));

  runSim();
  return wrap;
}

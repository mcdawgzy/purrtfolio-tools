import { ensureChartJS, CHART_COLORS, charts, destroyAllCharts, cssVar } from '../../core/charts.js';
import { el, stat } from '../../core/dom.js';
import { fmtUSD } from '../../core/format.js';

// ---------------- Greeks Explainer ----------------
// Black-Scholes-Merton Greeks calculator (client-side, no API)

function normCDF(x) {
  // Abramowitz & Stegun 26.2.17 approximation
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3734358 + t * (1.7814779 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

function normPDF(x) {
  return 0.3989423 * Math.exp(-x * x / 2);
}

function computeGreeks(S, K, r, q, sigma, T, isCall) {
  // Convert T from days to years
  const tau = T / 365;
  if (tau <= 0 || sigma <= 0 || S <= 0) {
    return { price: 0, delta: 0, gamma: 0, theta: 0, vega: 0, probITM: 0 };
  }

  const d1 = (Math.log(S / K) + (r - q + sigma * sigma / 2) * tau) / (sigma * Math.sqrt(tau));
  const d2 = d1 - sigma * Math.sqrt(tau);

  const _Nd1 = normCDF(d1);
  const _Nd2 = normCDF(d2);
  const pdf1 = normPDF(d1);

  // Discount factors
  const disc_r = Math.exp(-r * tau);
  const disc_q = Math.exp(-q * tau);

  // Option price (for reference)
  const price = isCall
    ? S * disc_q * _Nd1 - K * disc_r * normCDF(d2)
    : K * disc_r * normCDF(-d2) - S * disc_q * normCDF(-d1);

  // Delta
  const delta = isCall
    ? disc_q * _Nd1
    : disc_q * (_Nd1 - 1);

  // Gamma (same for call and put)
  const gamma = disc_q * pdf1 / (S * sigma * Math.sqrt(tau));

  // Theta (annualized, then converted to daily)
  const theta = isCall
    ? -(S * sigma * pdf1 * disc_q) / (2 * Math.sqrt(tau))
      - r * K * disc_r * normCDF(d2)
      + q * S * disc_q * _Nd1
    : -(S * sigma * pdf1 * disc_q) / (2 * Math.sqrt(tau))
      + r * K * disc_r * normCDF(-d2)
      - q * S * disc_q * normCDF(-d1);
  const thetaDaily = -theta / 365; // Convert to daily decay (positive = decay)

  // Vega (per 1% vol change)
  const vega = S * disc_q * pdf1 * Math.sqrt(tau) / 100;

  // Probability of expiring ITM
  const probITM = isCall ? _Nd2 : normCDF(-d2);

  return {
    price: price,
    delta: delta,
    gamma: gamma,
    theta: thetaDaily,
    vega: vega,
    probITM: probITM,
  };
}

export function renderGreeksExplainer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Greeks Explainer'),
    el('div', { class: 'hint brass' }, 'Black-Scholes-Merton · Live Greeks · Client-side')));

  // ---- Controls ----
  const defaults = { spot: 100, strike: 100, vol: 20, rate: 2, div: 1, days: 30, type: 'call' };

  const controls = el('div', { class: 'greeks-controls' });
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Spot Price'),
    el('input', { type: 'number', class: 'g-input', min: '0.01', step: '0.1', value: defaults.spot })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Strike Price'),
    el('input', { type: 'number', class: 'g-input', min: '0.01', step: '0.1', value: defaults.strike })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Implied Volatility (%)'),
    el('input', { type: 'number', class: 'g-input', min: '0.1', step: '0.1', value: defaults.vol })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Days to Expiry'),
    el('input', { type: 'number', class: 'g-input', min: '1', step: '1', value: defaults.days })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Interest Rate (%)'),
    el('input', { type: 'number', class: 'g-input', min: '-5', step: '0.1', value: defaults.rate })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Dividend Yield (%)'),
    el('input', { type: 'number', class: 'g-input', min: '0', step: '0.1', value: defaults.div })));
  controls.appendChild(el('div', { class: 'calc-field' },
    el('label', {}, 'Option Type'),
    el('select', { class: 'g-type' },
      el('option', { value: 'call' }, 'Call'),
      el('option', { value: 'put' }, 'Put'))));
  wrap.appendChild(controls);

  // ---- Stats grid ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addGreeksStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addGreeksStat('Option Price',  'price',   '');
  addGreeksStat('Delta',         'delta',   '');
  addGreeksStat('Gamma',         'gamma',   '');
  addGreeksStat('Theta (daily)', 'theta',   '');
  addGreeksStat('Vega (/1% vol)', 'vega',   '');
  addGreeksStat('Prob ITM',      'probITM', '');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'greeks-chart' });
  chartWrap.appendChild(el('canvas', { id: 'greeks-chart' }));
  wrap.appendChild(chartWrap);

  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      v.className = 'stat-value ' + (cls || '');
    }
  }

  function readInputs() {
    const inputs = controls.querySelectorAll('.g-input');
    return {
      spot:  parseFloat(inputs[0].value),
      strike: parseFloat(inputs[1].value),
      vol:   parseFloat(inputs[2].value),
      days:  parseFloat(inputs[3].value),
      rate:  parseFloat(inputs[4].value),
      div:   parseFloat(inputs[5].value),
      type:  controls.querySelector('.g-type').value,
    };
  }

  function fmtDelta(v) {
    if (isNaN(v)) return '—';
    const s = v < 0 ? '' : '+';
    return `${s}${v.toFixed(4)}`;
  }

  function fmtGamma(v) {
    if (isNaN(v)) return '—';
    return `${v.toFixed(6)}`;
  }

  function fmtTheta(v) {
    if (isNaN(v)) return '—';
    const s = v > 0 ? '+' : '';
    return `$${s}${v.toFixed(2)}`;
  }

  function fmtVega(v) {
    if (isNaN(v)) return '—';
    const s = v > 0 ? '+' : '';
    return `$${s}${v.toFixed(2)}`;
  }

  function computeAndRender() {
    const p = readInputs();
    const isCall = p.type === 'call';
    const g = computeGreeks(p.spot, p.strike, p.rate / 100, p.div / 100, p.vol / 100, p.days, isCall);

    setStat('price', fmtUSD(g.price, { sign: false, compact: false }));
    setStat('delta', fmtDelta(g.delta), g.delta > 0 ? 'green' : 'red');
    setStat('gamma', fmtGamma(g.gamma));
    setStat('theta', fmtTheta(g.theta), g.theta > 0 ? 'red' : 'green');
    setStat('vega',  fmtVega(g.vega),  g.vega > 0 ? 'green' : '');
    setStat('probITM', `${(g.probITM * 100).toFixed(1)}%`);

    // Chart: Delta vs Spot
    const center = p.spot;
    const lo = center * 0.5;
    const hi = center * 1.5;
    const N = 100;
    const step = (hi - lo) / N;
    const labels = [], deltas = [], gammas = [];
    for (let i = 0; i <= N; i++) {
      const s = lo + i * step;
      labels.push(s.toFixed(0));
      const dg = computeGreeks(s, p.strike, p.rate / 100, p.div / 100, p.vol / 100, p.days, isCall);
      deltas.push(dg.delta);
      gammas.push(dg.gamma * 100); // scale for visibility
    }

    // Render or update chart
    const canvas = document.getElementById('greeks-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (charts['greeks-chart']) charts['greeks-chart'].destroy();
    const ctx = canvas.getContext('2d');

    charts['greeks-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Delta',
            data: deltas,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.2,
            yAxisID: 'y',
          },
          {
            label: 'Gamma ×100',
            data: gammas,
            borderColor: CHART_COLORS.blue,
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            tension: 0.2,
            yAxisID: 'y1',
            borderDash: [4, 4],
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: cssVar('--panel'),
            titleColor: cssVar('--text'),
            bodyColor: cssVar('--text-dim'),
            borderColor: cssVar('--line'),
            borderWidth: 1,
            padding: 8,
          },
        },
        scales: {
          x: {
            title: { display: true, text: 'Underlying Price ($)', color: cssVar('--text-dim'), font: { size: 10 } },
            ticks: { color: cssVar('--text-dim'), font: { size: 9 } },
            grid: { color: cssVar('--line') },
          },
          y: {
            title: { display: true, text: 'Delta', color: cssVar('--text-dim'), font: { size: 10 } },
            ticks: { color: cssVar('--text-dim'), font: { size: 9 } },
            grid: { color: cssVar('--line') },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'Gamma ×100', color: cssVar('--text-dim'), font: { size: 10 } },
            ticks: { color: cssVar('--text-dim'), font: { size: 9 } },
            grid: { display: false },
            offset: true,
          },
        },
      },
    });
  }

  // Wire up inputs
  controls.querySelectorAll('.g-input').forEach(i => i.addEventListener('input', computeAndRender));
  controls.querySelector('.g-type').addEventListener('change', computeAndRender);

  // Initial render: stats now, chart once Chart.js is loaded and the view is mounted
  computeAndRender();
  ensureChartJS().then(computeAndRender);

  return wrap;
}

import { ensureChartJS, CHART_COLORS, charts, destroyAllCharts } from '../../core/charts.js';
import { el, stat } from '../../core/dom.js';
import { fmtUSD } from '../../core/format.js';

// ---------------- Options Payoff Visualizer ----------------
export function renderPayoffVisualizer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Options Payoff Visualizer'),
    el('div', { class: 'hint brass' }, 'Multi-leg builder · P&L at expiration · Client-side')));

  // ---- Legs container ----
  const legsContainer = el('div', { class: 'legs-container' });
  wrap.appendChild(legsContainer);

  const addBtn = el('button', { class: 'payoff-add-btn', onclick: addLeg }, '+ Add Leg');
  wrap.appendChild(addBtn);

  // ---- Stats panel ----
  const statsPanel = el('div', { class: 'stats' });
  const statEls = {};
  function addStat(label, key, cls) {
    const s = stat(label, '—', cls || '');
    statEls[key] = s;
    statsPanel.appendChild(s);
  }
  addStat('Max profit',  'maxProfit', 'green');
  addStat('Max loss',    'maxLoss',   'red');
  addStat('Breakevens',  'breakevens');
  addStat('P&L at low',  'pnlLow');
  addStat('P&L at high', 'pnlHigh');
  wrap.appendChild(statsPanel);

  // ---- Chart ----
  const chartWrap = el('div', { class: 'sim-chart' });
  chartWrap.appendChild(el('canvas', { id: 'pv-chart' }));
  wrap.appendChild(chartWrap);

  // ---- Formula footnote ----
  wrap.appendChild(el('div', { class: 'calc-formula' },
    'Long call: max(S−K,0) − premium  |  Long put: max(K−S,0) − premium  |  Short:  premium − max(intrinsic,0)'));

  // ---- Helpers ----
  function setStat(key, val, cls) {
    const v = statEls[key].querySelector('.stat-value');
    if (v) {
      v.textContent = val;
      if (cls !== undefined) v.className = 'stat-value ' + cls;
    }
  }

  function makeSelect(opts, cls, label) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', {}, label));
    const sel = el('select', { class: cls || '' });
    opts.forEach(([v, t]) => sel.appendChild(el('option', { value: v }, t)));
    field.appendChild(sel);
    return field;
  }

  function makeNumField(label, cls, val) {
    const field = el('div', { class: 'calc-field' });
    field.appendChild(el('label', {}, label));
    field.appendChild(el('input', { type: 'number', class: cls, min: '0', step: '0.01', value: val ?? '' }));
    return field;
  }

  function addLeg(defaults) {
    defaults = defaults || {};
    const row = el('div', { class: 'leg-row' });
    row.appendChild(makeSelect([['call','Call'],['put','Put']], 'leg-type', 'Type'));
    row.appendChild(makeSelect([['buy','Buy'],['sell','Sell']], 'leg-action', 'Action'));
    row.appendChild(makeNumField('Strike',  'leg-strike',  defaults.strike ?? ''));
    row.appendChild(makeNumField('Premium',  'leg-premium', defaults.premium ?? ''));
    row.appendChild(el('button', { class: 'leg-remove', onclick: () => { row.remove(); recalc(); } }, '✕'));
    legsContainer.appendChild(row);
    row.querySelectorAll('input, select').forEach(i => i.addEventListener('input', recalc));
    const firstEmpty = row.querySelector('input[value=""]');
    if (firstEmpty) firstEmpty.focus(); else row.querySelector('input').focus();
    recalc();
  }

  // ---- Payoff math ----
  function calcLegPayoff(leg, price) {
    const intrinsic = leg.type === 'call' ? Math.max(price - leg.strike, 0) : Math.max(leg.strike - price, 0);
    return leg.action === 'buy' ? intrinsic - leg.premium : leg.premium - intrinsic;
  }

  function readLegs() {
    const legs = [];
    const rows = legsContainer.querySelectorAll('.leg-row');
    for (const row of rows) {
      const type   = row.querySelector('.leg-type').value;
      const action = row.querySelector('.leg-action').value;
      const strike  = parseFloat(row.querySelector('.leg-strike').value);
      const premium = parseFloat(row.querySelector('.leg-premium').value);
      if (!isNaN(strike) && !isNaN(premium) && strike > 0 && premium >= 0) {
        legs.push({ type, action, strike, premium });
      }
    }
    return legs;
  }

  function findBreakevens(prices, payoffs) {
    const result = [];
    for (let i = 1; i < payoffs.length; i++) {
      const a = payoffs[i - 1], b = payoffs[i];
      if ((a <= 0 && b > 0) || (a >= 0 && b < 0)) {
        const t = a === b ? 0 : -a / (b - a);
        result.push(prices[i - 1] + t * (prices[i] - prices[i - 1]));
      }
    }
    return result;
  }

  // ---- Main recalc ----
  async function recalc() {
    const legs = readLegs();

    if (legs.length === 0) {
      setStat('maxProfit',  '—');
      setStat('maxLoss',    '—');
      setStat('breakevens', '—');
      setStat('pnlLow',     '—');
      setStat('pnlHigh',    '—');
      if (charts['pv-chart']) charts['pv-chart'].destroy();
      return;
    }

    // Price range (60% below lowest strike to 40% above highest)
    const strikes = legs.map(l => l.strike);
    const lo = Math.min(...strikes), hi = Math.max(...strikes);
    const priceMin = Math.max(0.01, lo * 0.6);
    const priceMax = hi * 1.4;
    const N = 200;
    const step = (priceMax - priceMin) / N;
    const prices = [], payoffs = [];
    for (let i = 0; i <= N; i++) {
      const p = priceMin + i * step;
      prices.push(p);
      payoffs.push(legs.reduce((sum, leg) => sum + calcLegPayoff(leg, p), 0));
    }

    const maxProfit = Math.max(...payoffs);
    const maxLoss   = Math.min(...payoffs);
    const bbs       = findBreakevens(prices, payoffs);

    setStat('maxProfit',  fmtUSD(maxProfit, { compact: false }), maxProfit >= 0 ? 'green' : 'red');
    setStat('maxLoss',    fmtUSD(maxLoss, { compact: false }),   maxLoss  < 0 ? 'red'   : 'green');
    setStat('breakevens', bbs.length ? bbs.map(b => '$' + b.toFixed(2)).join(', ') : 'None');
    setStat('pnlLow',     fmtUSD(payoffs[0], { compact: false }));
    setStat('pnlHigh',    fmtUSD(payoffs[N], { compact: false }));

    // Chart
    await ensureChartJS();
    const canvas = document.getElementById('pv-chart');
    if (!canvas) return;
    if (charts['pv-chart']) charts['pv-chart'].destroy();
    const ctx = canvas.getContext('2d');
    const zeroData = prices.map(() => 0);

    charts['pv-chart'] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: prices.map(p => p.toFixed(0)),
        datasets: [
          {
            label: 'P&L',
            data: payoffs,
            borderColor: CHART_COLORS.brass,
            borderWidth: 2,
            pointRadius: 0,
            fill: false,
            tension: 0.1,
          },
          {
            label: 'Break-even',
            data: zeroData,
            borderColor: '#5C6B7A',
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
          },
          ...bbs.map(price => ({
            label: 'Breakeven',
            data: [{ x: price, y: 0 }],
            backgroundColor: CHART_COLORS.brass,
            borderColor: CHART_COLORS.brass,
            pointRadius: 5,
            pointHoverRadius: 7,
            showLine: false,
          })),
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
            title: { display: true, text: 'Underlying Price ($)', color: '#7E8A9A', font: { size: 10 } },
            ticks: { color: '#7E8A9A', font: { size: 9 } },
            grid: { color: '#1E2A38' },
          },
          y: {
            title: { display: true, text: 'P&L ($)', color: '#7E8A9A', font: { size: 10 } },
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

  // Seed with a single long call for immediate visual feedback
  addLeg({ strike: 100, premium: 5 });

  return wrap;
}

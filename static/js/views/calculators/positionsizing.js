import { destroyAllCharts } from '../../core/charts.js';
import { el } from '../../core/dom.js';
import { fmtUSD } from '../../core/format.js';

// ---------------- Position Sizing Calculator (Kelly Criterion) ----------------
export function renderPositionSizing() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });

  // ---- Header ----
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Position Sizing Calculator'),
    el('div', { class: 'hint' }, 'Kelly Criterion · Full · Half · Quarter')));

  // ---- Calculator ----
  const form = el('div', { class: 'calc-form' });

  // --- Inputs ---
  const inputPanel = el('div', { class: 'calc-inputs' });

  const accountInput = el('input', { type: 'number', id: 'ps-account', min: '0', step: '1000', value: '100000' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-account' }, 'Account size'),
    accountInput));

  const winRateInput = el('input', { type: 'number', id: 'ps-winrate', min: '0', max: '100', step: '0.5', value: '60' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-winrate' }, 'Win rate'),
    el('div', { class: 'calc-input-row' },
      winRateInput,
      el('span', { class: 'unit' }, '%'))));

  const rrrInput = el('input', { type: 'number', id: 'ps-rrr', min: '0.01', step: '0.1', value: '2.0' });
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-rrr' }, 'Reward : Risk'),
    rrrInput));

  const variantSelect = el('select', { id: 'ps-variant' },
    el('option', { value: 'full' }, 'Full Kelly'),
    el('option', { value: 'half', selected: true }, 'Half Kelly'),
    el('option', { value: 'quarter' }, 'Quarter Kelly'));
  inputPanel.appendChild(el('div', { class: 'calc-field' },
    el('label', { for: 'ps-variant' }, 'Allocation'),
    variantSelect));

  // --- Results ---
  const resultsPanel = el('div', { class: 'calc-results' });

  const elKellyFull    = el('span', { class: 'calc-stat-value mono' }, '—');
  const elKellyHalf    = el('span', { class: 'calc-stat-value mono brass' }, '—');
  const elKellyQuarter = el('span', { class: 'calc-stat-value mono' }, '—');
  const elRisk         = el('span', { class: 'calc-stat-value mono' }, '—');
  const elPosition     = el('span', { class: 'calc-stat-value mono' }, '—');
  const elEv           = el('span', { class: 'calc-stat-value mono' }, '—');

  resultsPanel.appendChild(el('div', { class: 'calc-result-group' },
    el('h3', {}, 'Kelly allocation'),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Full'),
      elKellyFull),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Half'),
      elKellyHalf),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Quarter'),
      elKellyQuarter)));

  resultsPanel.appendChild(el('div', { class: 'calc-result-group' },
    el('h3', {}, 'Position sizing'),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Risk per trade'),
      elRisk),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Position value'),
      elPosition),
    el('div', { class: 'calc-stat-row' },
      el('span', { class: 'calc-stat-label' }, 'Expected value'),
      elEv)));

  form.appendChild(inputPanel);
  form.appendChild(resultsPanel);
  wrap.appendChild(form);

  // ---- Formula footnote ----
  wrap.appendChild(el('p', { class: 'calc-formula' },
    'f* = p − (1−p)/b  |  p = win rate, b = reward:risk ratio  |  position = risk × b'));

  // ---- Calculation (pure functions, no DOM lookups) ----
  function fmtPct(n) {
    if (n === 0) return '0.0%';
    return (n * 100).toFixed(1) + '%';
  }
  function fmtSignedPct(n) {
    if (n === 0) return '0.0%';
    return (n > 0 ? '+' : '−') + Math.abs(n * 100).toFixed(1) + '%';
  }

  function recalc() {
    const account = parseFloat(accountInput.value) || 0;
    const winRate = parseFloat(winRateInput.value) || 0;
    const rrr     = parseFloat(rrrInput.value) || 1;
    const variant = variantSelect.value;

    const p = winRate / 100;
    const q = 1 - p;
    const b = rrr;

    // Kelly Criterion: f* = p − q/b
    const kelly = p - q / b;
    const kellyFull    = Math.max(0, kelly);
    const kellyHalf    = Math.max(0, kelly / 2);
    const kellyQuarter = Math.max(0, kelly / 4);

    elKellyFull.textContent    = fmtPct(kellyFull);
    elKellyHalf.textContent    = fmtPct(kellyHalf);
    elKellyQuarter.textContent = fmtPct(kellyQuarter);

    const variantMap = { full: kellyFull, half: kellyHalf, quarter: kellyQuarter };
    const selected = variantMap[variant];

    const riskPerTrade  = account * selected;
    const positionValue = riskPerTrade * b;
    const ev            = p * b - q;  // expected value per dollar risked

    const hasEdge = kelly > 0;

    elRisk.textContent     = hasEdge ? fmtUSD(riskPerTrade,   { compact: false }) : '—';
    elPosition.textContent = hasEdge ? fmtUSD(positionValue, { compact: false }) : '—';
    elEv.textContent       = fmtSignedPct(ev);

    elEv.className = 'calc-stat-value mono ' + (ev > 0 ? 'green' : ev < 0 ? 'red' : '');
  }

  // Attach listeners to captured element references
  accountInput.addEventListener('input', recalc);
  winRateInput.addEventListener('input', recalc);
  rrrInput.addEventListener('input', recalc);
  variantSelect.addEventListener('change', recalc);

  recalc();
  return wrap;
}

import { destroyAllCharts } from '../../core/charts.js';
import { el } from '../../core/dom.js';

// ──────────────────────────────────────────────────────────────
// Options Explainer (educational reference)
// ──────────────────────────────────────────────────────────────
export function renderOptionsExplainer() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Options Explainer'),
    el('div', { class: 'hint brass' }, 'Concepts · Strategies · Risks · Client-side')));

  function section(title, html) {
    const s = el('div', { class: 'options-section' });
    s.appendChild(el('h3', { class: 'options-section-title' }, title));
    s.appendChild(el('div', { class: 'options-section-body', html }));
    return s;
  }

  function termRow(term, def) {
    return el('div', { class: 'options-term-row' },
      el('span', { class: 'options-term' }, term),
      el('span', { class: 'options-def' }, def));
  }

  function stratCard(name, desc, pnl) {
    const c = el('div', { class: 'options-strat' });
    c.appendChild(el('div', { class: 'options-strat-name' }, name));
    c.appendChild(el('div', { class: 'options-strat-desc' }, desc));
    c.appendChild(el('div', { class: 'options-strat-pnl' }, pnl));
    return c;
  }

  wrap.appendChild(section('What Are Options?',
    '<p>An <strong>option</strong> is a contract giving the buyer the <em>right</em> (not the obligation) to buy or sell an underlying asset at a set price before a set date. The <strong>seller</strong> of an option has the <em>obligation</em> if the buyer exercises.</p>' +
    '<ul><li><strong>Call option</strong> — right to <em>buy</em> (go long) at the strike.</li>' +
    '<li><strong>Put option</strong> — right to <em>sell</em> (go long) at the strike.</li>' +
    '<li><strong>Premium</strong> — the price of the option contract (quoted per share; 1 contract = 100 shares).</li></ul>'));

  const terms = el('div', { class: 'options-terms' });
  terms.appendChild(el('h3', { class: 'options-section-title' }, 'Key Concepts'));
  terms.appendChild(termRow('Strike Price', 'The price at which the underlying can be bought/sold if the option is exercised.'));
  terms.appendChild(termRow('Expiration', 'The last day the option can be exercised. After expiry it becomes worthless.'));
  terms.appendChild(termRow('Moneyness', 'An option is <strong>ITM</strong> (in-the-money) if it has intrinsic value, <strong>OTM</strong> (out-of-the-money) if it has no intrinsic value, and <strong>ATM</strong> (at-the-money) if the strike ≈ spot.'));
  terms.appendChild(termRow('Intrinsic Value', 'Spot − Strike (calls) or Strike − Spot (puts). This is the immediate exercise value.'));
  terms.appendChild(termRow('Time Value', 'Premium − Intrinsic Value. It reflects the probability of ending up ITM before expiry.'));
  terms.appendChild(termRow('American vs European', '<strong>American</strong> can be exercised any time before expiry; <strong>European</strong> only at expiry.'));
  wrap.appendChild(terms);

  wrap.appendChild(section('The Greeks at a Glance',
    '<p>The Greeks measure how an option&rsquo;s price responds to changes in its inputs. Each Greek is the partial derivative of the option price:</p>' +
    '<ul><li><strong>Delta (Δ)</strong> — sensitivity to the underlying&rsquo;s price. Calls: 0→1; Puts: −1→0.</li>' +
    '<li><strong>Gamma (Γ)</strong> — rate of change of Delta. Highest near ATM, at expiry.</li>' +
    '<li><strong>Theta (Θ)</strong> — time decay per day. Options lose value as expiry approaches.</li>' +
    '<li><strong>Vega (ν)</strong> — sensitivity to implied volatility. Long options benefit from rising IV.</li>' +
    '<li><strong>Rho (ρ)</strong> — sensitivity to interest rates (minor for short-dated options).</li></ul>' +
    '<p><a href="#/greeks-explainer">Interactive Greeks Calculator &rarr;</a> · ' +
    '<a href="#/iv-rank">IV Rank & Percentile Tracker</a></p>'));

  wrap.appendChild(section('Time Decay & Volatility',
    '<p><strong>Theta</strong> accelerates non-linearly near expiry — the last 30 days can erase more time value than the first 90. Long option holders are negatively exposed to theta; short sellers (writers) collect it as income.</p>' +
    '<p><strong>Implied Volatility (IV)</strong> is the market&rsquo;s consensus forecast of future volatility, backed out of the option price. When IV is <em>high</em> (IV Rank > 50%), options are expensive to buy — consider selling premium. When IV is <em>low</em> (IV Rank < 30%), options are cheap to buy.</p>'));

  const stratGrid = el('div', { class: 'options-strats' });
  const strats = [
    ['Covered Call', 'Own the stock, sell a call against it. Generates income but caps upside.', 'Max profit = premium + (strike − stock cost), capped upside'],
    ['Protective Put', 'Own the stock, buy a put for downside insurance. Costs premium for protection.', 'Max loss = put premium + (stock cost − strike), downside limited'],
    ['Long Straddle', 'Buy a call + put at the same strike. Profits from big moves either direction.', 'Max loss = total premium paid, unlimited profit'],
    ['Long Strangle', 'Buy an OTM call + OTM put (lower strike). Cheaper but needs bigger move.', 'Max loss = total premium paid, wider breakeven range needed'],
    ['Vertical Spread', 'Sell an OTM option against a further-OTM or ITM option in the same class.', 'Defined risk, income strategy — direction and volatility neutral'],
    ['Iron Condor', 'Sell an OTM strangle, buy further OTM strangle. Income from range-bound action.', 'Max loss = width − credit received, max profit = net credit'],
  ];
  strats.forEach(s => stratGrid.appendChild(stratCard(...s)));
  wrap.appendChild(el('h3', { class: 'options-section-title' }, 'Common Strategies'));
  wrap.appendChild(stratGrid);

  wrap.appendChild(section('Before You Trade',
    '<p><strong>Risk checklist:</strong></p>' +
    '<ul><li>Options can expire worthless — 60–90% of contracts expire out of the money.</li>' +
    '<li>Selling options has <em>unlimited</em> risk on short calls; defined risk on short puts.</li>' +
    '<li>Position size matters: never risk more than 1–2% of capital on a single options trade.</li>' +
    '<li>Consider the <a href="#/position-sizing">Position Sizing Calculator</a> for Kelly-based sizing.</li>' +
    '<li>Check <a href="#/payoff-visualizer">Options Payoff Visualizer</a> to model multi-leg P/L before entry.</li></ul>'));

  return wrap;
}

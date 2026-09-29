// Nav data and dropdown behaviour shared by the SPA nav (nav.js) and the
// static research pages (site-nav.js). No imports, so static pages can load it
// without pulling in the router and every view.

// Nav link definitions grouped by category
export const NAV_GROUPS = [
  {
    label: 'Data Views',
    items: [
      { view: 'funds',     label: 'Funds' },
      { view: 'consensus', label: 'Consensus' },
      { view: 'sectors',   label: 'Sectors' },
    ],
  },
  {
    label: 'Scanners',
    items: [
      { view: 'snapshot',      label: 'Market Snapshot' },
      { view: 'shortinterest', label: 'Short Interest' },
      { view: 'economic',      label: 'Economic Calendar' },
      { view: 'insider',       label: 'Insider Trading' },
      { view: 'momentum',      label: 'Price Momentum' },
      { view: 'correlation',   label: 'Correlation Matrix' },
      { view: 'factors',       label: 'Factor Exposure' },
      { view: 'putcallratio',  label: 'Put/Call Ratio' },
      { view: 'ivrank',        label: 'IV Rank Tracker' },
      { view: 'news',          label: 'News Sentiment' },
      { view: 'screener',      label: 'Stock Screener' },
      { view: 'earningsrevisions', label: 'Earnings Revision' },
      { view: 'crowdedtrades', label: 'Crowded Trades' },
    ],
  },
  {
    label: 'Tools',
    items: [
      { view: 'positioning', label: 'Position Sizing' },
      { view: 'drawdown',    label: 'Drawdown Simulator' },
      { view: 'payoff',      label: 'Options Payoff' },
      { view: 'greeks',      label: 'Greeks Explainer' },
      { view: 'optionsexplainer', label: 'Options Explainer' },
      { view: 'quotes',           label: 'Famous Trader Quotes' },
    ],
  },
];

// Map nav item view → hash route
export const NAV_ROUTES = {
  funds:       '#/funds',
  consensus:   '#/consensus',
  sectors:     '#/sectors',
  snapshot:    '#/snapshot',
  shortinterest: '#/short-interest',
  economic:    '#/economic-calendar',
  insider:     '#/insider',
  momentum:    '#/momentum',
  correlation: '#/correlation',
  factors:     '#/factors',
  putcallratio: '#/put-call-ratio',
  ivrank:       '#/iv-rank',
  news:         '#/news',
  positioning:  '#/position-sizing',
  drawdown:     '#/drawdown-simulator',
  payoff:       '#/payoff-visualizer',
  greeks:        '#/greeks-explainer',
  optionsexplainer: '#/options-explainer',
  unusualactivity: '#/unusual-activity',
  screener:       '#/screener',
  earningsrevisions: '#/earnings-revisions',
  crowdedtrades: '#/crowded-trades',
  quotes:         '#/quotes',
};

// Close all open dropdowns (click-outside, Escape, after navigation)
export function closeNavDropdowns() {
  document.querySelectorAll('.nav-dropdown.open').forEach(d => d.classList.remove('open'));
}

// Click-outside handler
document.addEventListener('click', (e) => {
  if (!e.target.closest('.nav-dropdown')) {
    closeNavDropdowns();
  }
});

// Escape key closes dropdowns
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeNavDropdowns();
  }
});

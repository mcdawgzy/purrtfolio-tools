// Nav data and dropdown behaviour shared by the SPA nav (nav.js) and the
// static research pages (site-nav.js). No imports, so static pages can load it
// without pulling in the router and every view.

// Nav link definitions grouped by category. The site is focused on strategy
// research, so only the calculators are listed. The data dashboards (13F,
// scanners, explainers) are unlisted but still reachable by URL (NAV_ROUTES).
export const NAV_GROUPS = [
  {
    label: 'Tools',
    items: [
      { view: 'positioning', label: 'Position Sizing' },
      { view: 'drawdown',    label: 'Drawdown Simulator' },
      { view: 'payoff',      label: 'Options Payoff' },
      { view: 'greeks',      label: 'Greeks Explainer' },
    ],
  },
];

// Call-to-action pinned to the right of the nav on every page
export const NAV_CTA = { label: 'Follow on X', href: 'https://x.com/Purrtfolio' };

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

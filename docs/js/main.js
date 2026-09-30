/* Trading Tools by Purrtfolio — entry point.
   No framework, no build step: native ES modules served as-is.
   State lives in core/state.js; view = render(state) (see router.js). */

import { COLD_START_MSG, loadMeta, setBooting } from './core/api.js';
import { el } from './core/dom.js';
import { state } from './core/state.js';
import { handleRoute, render } from './router.js';

window.addEventListener('hashchange', handleRoute);

// Charts read theme colours when they're built, so rebuild the view when the
// OS switches between light and dark.
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (!state.routeLoading) render();
});

window.addEventListener('error', (e) => {
  console.error('Global error:', e.error);
});

window.addEventListener('unhandledrejection', (e) => {
  console.error('Unhandled promise rejection:', e.reason);
});

// ---------------- boot ----------------
async function boot() {
  // The bare site root is the Research hub; app pages all have a hash route.
  if (!location.hash.replace(/^#\/?/, '')) {
    location.replace('./research/');
    return;
  }
  document.getElementById('app').replaceChildren(el('div', { class: 'loading' }, COLD_START_MSG));
  try {
    await loadMeta();
  } catch (e) {
    // Keep the shell usable: calculator/explainer pages don't need the API.
    state.bootError = 'Could not reach the data server (' + e.message + '). Data pages may fail to load; calculators still work.';
  }
  setBooting(false);
  await handleRoute();
}

boot().catch(e => {
  document.getElementById('app').replaceChildren(
    el('div', { class: 'error' }, 'Failed to start: ' + e.message));
});

// API base resolution, fetch wrapper with cold-start retry, and the shared /api/meta loader.

import { el } from './dom.js';
import { state } from './state.js';

// API base URL — override with ?api=<url> or <meta name="api-base" content="...">;
// otherwise the local server in dev, production elsewhere.
export const API = (() => {
  // ?api= is a dev convenience: only local or Render hosts, so a shared link
  // can't point the public site at an arbitrary data source.
  let fromQuery = new URLSearchParams(location.search).get('api');
  try {
    const host = fromQuery != null ? new URL(fromQuery).hostname : '';
    if (!/^(localhost|127\.0\.0\.1|[\w-]+\.onrender\.com)$/.test(host)) fromQuery = null;
  } catch (e) { fromQuery = null; }
  const fromMeta = document.querySelector('meta[name="api-base"]')?.content;
  const override = fromQuery ?? fromMeta;
  if (override != null) return override.trim().replace(/\/+$/, '');
  return (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? ''
    : 'https://one3f-tracker-wpj6.onrender.com';
})();

export const COLD_START_MSG = 'Waking the server (free-tier host, can take ~30s)…';

// While any request is in its retry loop, show a small cold-start notice.
// It lives outside #app so render() doesn't wipe it.
let _coldStartWaits = 0;

let _booting = true;  // boot() shows its own wake-up message in #app
export function setBooting(v) { _booting = v; }

function updateColdStartHint() {
  const n = document.getElementById('cold-start-hint');
  if (_coldStartWaits > 0 && !n && !_booting) {
    document.body.appendChild(el('div', { id: 'cold-start-hint', class: 'cold-start-hint', role: 'status' }, COLD_START_MSG));
  } else if (_coldStartWaits === 0 && n) {
    n.remove();
  }
}

async function _retryApi(path, params, attempt) {
  const retry = async () => {
    await new Promise(res => setTimeout(res, 2000 * Math.pow(2, attempt - 1)));
    return api(path, params, attempt + 1);
  };
  if (attempt !== 1) return retry();
  _coldStartWaits++; updateColdStartHint();
  try { return await retry(); }
  finally { _coldStartWaits--; updateColdStartHint(); }
}

// Retry transient failures (network errors from Render free-tier cold starts,
// and 5xx/429/408) with exponential backoff so a single spin-up hiccup doesn't
// surface as "Failed to fetch". 5 attempts with 2s base covers ~30s cold starts.
export async function api(path, params = {}, _attempt = 1) {
  const url = new URL(API + path, location.origin);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
  });
  let r;
  try {
    r = await fetch(url);
  } catch (e) {
    // Network-level failure (instance asleep / DNS / connection reset).
    if (_attempt >= 5) throw e;
    return _retryApi(path, params, _attempt);
  }
  if (!r.ok) {
    // Retry transient server-side errors; fail fast on real 4xx client errors.
    if (_attempt < 5 && (r.status >= 500 || r.status === 408 || r.status === 429)) {
      return _retryApi(path, params, _attempt);
    }
    const body = await r.text();
    throw new Error(`HTTP ${r.status}: ${body.slice(0, 200)}`);
  }
  return r.json();
}

// Shared by every data view (masthead counts) and boot().
export async function loadMeta() {
  if (state.meta) return state.meta;
  state.meta = await api('/api/meta');
  state.bootError = null;
  return state.meta;
}

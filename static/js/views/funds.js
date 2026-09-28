import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtUSD } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

export async function loadFunds() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const d = await api('/api/funds');
    state.funds = d.funds;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---- Funds list view ----
export function renderFunds() {
  const wrap = el('div', { class: 'section' });

  // Top stats
  const totalAum = state.funds.reduce((s, f) => s + (f.latest_aum_usd || 0), 0);
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Funds', state.funds.length));
  stats.appendChild(stat('Tracked AUM', fmtUSD(totalAum), 'brass'));
  stats.appendChild(stat('Quarters tracked', state.meta?.quarters?.length || 0));
  const latestQ = state.meta?.quarters?.[0]?.report_period || '';
  stats.appendChild(stat('Latest quarter', latestQ));
  wrap.appendChild(stats);

  // Funds table
  const tableWrap = el('div', { class: 'table-wrap' });
  const rows = state.funds;
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Strategy', 'Fund', 'CIK', 'Latest AUM', 'Holdings'].forEach((h, i) => {
    const th = el('th', { class: i >= 3 ? 'num' : '' }, h);
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const f of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/fund/' + f.cik),
    });
    tr.appendChild(el('td', {},
      el('span', { class: 'strategy-tag' }, f.strategy || '—')));
    tr.appendChild(el('td', { class: 'brass' }, f.name));
    tr.appendChild(el('td', { class: 'mono mut' }, f.cik));
    tr.appendChild(el('td', { class: 'num' },
      f.latest_aum_usd ? fmtUSD(f.latest_aum_usd) : '—'));
    tr.appendChild(el('td', { class: 'num mut' },
      f.latest_holdings_count?.toLocaleString() || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

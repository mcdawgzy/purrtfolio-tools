import { api, loadMeta } from '../core/api.js';
import { el, stat } from '../core/dom.js';
import { fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { render } from '../router.js';

export async function loadEconomicCalendar() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, events] = await Promise.all([
      api('/api/econ/meta'),
      api('/api/econ/events', {
        days_ahead: state.econDaysAhead,
        impact: state.econImpact,
        category: state.econCategory,
      }),
    ]);
    state.econMeta = meta;
    state.econEvents = events.events || events;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- Economic Calendar view ----------------
export function renderEconomicCalendar() {
  const wrap = el('div', { class: 'section' });

  // Stats row
  const m = state.econMeta;
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Upcoming', m ? m.upcoming_count : '—'));
  stats.appendChild(stat('Categories', m && m.categories ? m.categories.length : '—'));
  const lastUpd = m && m.last_update
    ? `${String(m.last_update).slice(5, 7)}/${String(m.last_update).slice(8, 10)}/${String(m.last_update).slice(0, 4)}`
    : '—';
  stats.appendChild(stat('Last Updated', lastUpd, 'brass'));
  wrap.appendChild(stats);

  // Filters
  const filters = el('div', { class: 'filters' });
  // Impact filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Impact:'),
    ...['', 'high', 'medium', 'low'].map(imp =>
      el('button', {
        class: state.econImpact === imp ? 'active' : '',
        onclick: async () => {
          state.econImpact = imp;
          state.loading = true; render();
          const resp = await api('/api/econ/events', {
            days_ahead: state.econDaysAhead,
            impact: state.econImpact || undefined,
            category: state.econCategory || undefined,
          });
          state.econEvents = resp.events || resp;
          state.loading = false; render();
        },
      }, imp ? imp.charAt(0).toUpperCase() + imp.slice(1) : 'ALL')
    )
  ));
  // Days ahead filter
  filters.appendChild(el('div', { class: 'filter-group' },
    el('span', {}, 'Days:'),
    ...[14, 30, 60, 90].map(d =>
      el('button', {
        class: state.econDaysAhead === d ? 'active' : '',
        onclick: async () => {
          state.econDaysAhead = d;
          state.loading = true; render();
          const resp = await api('/api/econ/events', {
            days_ahead: d,
            impact: state.econImpact || undefined,
            category: state.econCategory || undefined,
          });
          state.econEvents = resp.events || resp;
          state.loading = false; render();
        },
      }, String(d))
    )
  ));
  wrap.appendChild(filters);

  // Table
  const tableWrap = el('div', { class: 'table-wrap' });
  const events = state.econEvents || [];
  if (!events.length) {
    tableWrap.appendChild(el('div', { class: 'empty' }, 'No economic events match your filters.'));
    wrap.appendChild(tableWrap);
    return wrap;
  }

  // Group by date
  const byDate = {};
  for (const e of events) {
    const d = e.event_date;
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(e);
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Date', 'Time', 'Event', 'Category', 'Impact', 'Forecast', 'Prior'].forEach((h, i) => {
    let cls = '';
    if (h === 'Date' || h === 'Time') cls = 'mono';
    if (['Impact', 'Forecast', 'Prior'].includes(h)) cls = 'num';
    trh.appendChild(el('th', { class: cls }, h));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const [dateStr, dayEvents] of Object.entries(byDate)) {
    for (const e of dayEvents) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'mono' }, fmtDateISO(e.event_date)));
      tr.appendChild(el('td', { class: 'mono mut' }, e.event_time || '—'));
      tr.appendChild(el('td', {}, e.event_name));
      tr.appendChild(el('td', { class: 'mono mut' }, e.category || '—'));
      const impactCls = e.impact === 'high' ? 'num red'
        : e.impact === 'medium' ? 'num amber' : 'num mut';
      tr.appendChild(el('td', { class: impactCls }, e.impact || '—'));
      tr.appendChild(el('td', { class: 'num' }, e.forecast || '—'));
      tr.appendChild(el('td', { class: 'num mut' }, e.prior || '—'));
      tbody.appendChild(tr);
    }
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  return wrap;
}

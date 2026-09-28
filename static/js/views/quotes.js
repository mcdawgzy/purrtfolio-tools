import { api, loadMeta } from '../core/api.js';
import { el } from '../core/dom.js';
import { state } from '../core/state.js';
import { render } from '../router.js';

export async function loadQuotes(r) {
  state.error = null;
  state.loading = true;
  try {
    const cat = r && r.category ? r.category : state.quoteCategory || '';
    state.quoteCategory = cat;
    await loadMeta();
    const [meta, quotes] = await Promise.all([
      api('/api/quotes/meta'),
      api('/api/quotes', { category: cat, limit: 50 }),
    ]);
    state.quoteMeta = meta;
    state.quoteList = quotes;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

async function loadRandomQuote() {
  try {
    state.loading = true;
    const q = await api('/api/quotes/random');
    state.quoteList = q ? [q] : [];
    if (!state.quoteMeta) {
      state.quoteMeta = await api('/api/quotes/meta');
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
    render();
  }
}

function changeQuoteCategory(cat) {
  state.quoteCategory = cat;
  state.loading = true; render();
  loadQuotes({ category: cat }).then(render);
}

// ──────────────────────────────────────────────────────────────
// Famous Trader Quotes
// ──────────────────────────────────────────────────────────────
export function renderQuotes() {
  const wrap = el('div', { class: 'section' });

  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Famous Trader Quotes'),
    el('div', { class: 'hint brass' }, 'Curated · ' + ((state.quoteMeta && state.quoteMeta.categories) ? state.quoteMeta.categories.length : 0) + ' categories')));

  // ── Controls ──
  const controls = el('div', { class: 'q-controls' });

  // Category filter
  const cats = (state.quoteMeta && state.quoteMeta.categories) || [];
  const sel = el('select', { class: 'q-select' });
  sel.appendChild(el('option', { value: '', selected: !state.quoteCategory }, 'All Categories'));
  cats.forEach(c => sel.appendChild(el('option', { value: c, selected: state.quoteCategory === c }, c)));
  sel.addEventListener('change', () => changeQuoteCategory(sel.value));
  controls.appendChild(sel);

  // Random button
  const randBtn = el('button', { class: 'btn btn-ghost btn-sm', type: 'button' }, '🎲 Random');
  randBtn.addEventListener('click', loadRandomQuote);
  controls.appendChild(randBtn);

  if (state.quoteList.length > 0 || state.loading) {
    controls.appendChild(el('span', { class: 'q-count hint' },
      state.loading ? 'Loading…' : state.quoteList.length + ' quote' + (state.quoteList.length === 1 ? '' : 's')));
  }
  wrap.appendChild(controls);

  if (state.loading) {
    wrap.appendChild(el('div', { class: 'loading' }, 'FETCHING WISDOM…'));
    return wrap;
  }

  const rows = state.quoteList;
  if (rows.length === 0) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No quotes match the current filter.'));
    return wrap;
  }

  // ── Quote grid ──
  const grid = el('div', { class: 'q-grid' });
  rows.forEach(q => {
    grid.appendChild(el('div', { class: 'q-card' },
      el('div', { class: 'q-mark' }, '"'),
      el('div', { class: 'q-text' }, q.quote),
      el('div', { class: 'q-author-row' },
        el('span', { class: 'q-author' }, q.author),
        q.category ? el('span', { class: 'q-badge' }, q.category) : null,
      ),
      q.source ? el('div', { class: 'q-source' }, q.source) : null,
    ));
  });
  wrap.appendChild(grid);

  return wrap;
}

import { API, api, loadMeta } from '../core/api.js';
import { el } from '../core/dom.js';
import { state } from '../core/state.js';

export async function loadSnapshot() {
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    state.snapshot = await api('/api/snapshot/latest');
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---- Market Snapshot view ----
export function renderSnapshot() {
  if (!state.snapshot) return el('div', { class: 'empty' }, 'Loading…');

  const s = state.snapshot;
  if (!s.date_str) {
    return el('div', { class: 'section' },
      el('div', { class: 'section-header' },
        el('h2', {}, 'Market Snapshot'),
      ),
      el('div', { class: 'empty' }, 'No snapshot available yet. Run the macro pipeline to generate one.'),
    );
  }

  const wrap = el('div', { class: 'section' });

  // Date label — handle both YYYYMMDD format and "latest" / other strings
  let dateLabel = '';
  if (s.date_str) {
    if (/^\d{8}$/.test(s.date_str)) {
      dateLabel = `${s.date_str.slice(4, 6)}/${s.date_str.slice(6, 8)}/${s.date_str.slice(0, 4)}`;
    } else {
      // e.g. "latest" — try the timestamp field as fallback
      const ts = s.timestamp || '';
      dateLabel = ts.slice(0, 10).replace(/(\d{4})-(\d{2})-(\d{2})/, '$2/$3/$1') || s.date_str;
    }
  }

  // Header
  wrap.appendChild(el('div', { class: 'section-header' },
    el('h2', {}, 'Market Snapshot'),
    dateLabel ? el('div', { class: 'hint brass' }, dateLabel) : el('div', { class: 'hint' }, 'No date available'),
  ));

  // Headline / caption
  if (s.caption) {
    wrap.appendChild(el('div', { class: 'snapshot-caption' }, s.caption));
  }

  // What's driving the markets — top 3 movers with driver narratives (moved above the PNG)
  if (s.top_movers && s.top_movers.length > 0) {
    const mv = el('div', { class: 'snapshot-movers' });
    mv.appendChild(el('h3', {}, 'What\u2019s driving the markets'));
    const ul = el('ul');
    for (const m of s.top_movers) {
      const color = m.pct_change > 0 ? 'green' : m.pct_change < 0 ? 'red' : 'dim';
      const sign = m.pct_change > 0 ? '+' : '';
      ul.appendChild(el('li', {},
        el('span', { class: 'mono ' + color }, sign + m.pct_change.toFixed(2) + '%'),
        el('span', { class: 'mover-name' }, m.name),
        el('span', { class: 'mover-driver' }, m.driver),
      ));
    }
    mv.appendChild(ul);
    wrap.appendChild(mv);
  }

  // Hero: snapshot image
  const imgUrl = API + '/snapshots/' + s.png_filename;
  const hero = el('div', { class: 'snapshot-hero' });
  const img = el('img', {
    src: imgUrl,
    alt: 'Market Snapshot ' + dateLabel,
    style: { maxWidth: '100%', height: 'auto', borderRadius: '6px', border: '1px solid var(--line)' },
  });
  img.onerror = () => {
    img.src = '';
    img.style.minHeight = '200px';
    img.style.display = 'flex';
    img.style.alignItems = 'center';
    img.style.justifyContent = 'center';
    img.style.color = 'var(--text-dim)';
    img.textContent = 'Snapshot image not yet available';
  };
  hero.appendChild(img);
  wrap.appendChild(hero);

  return wrap;
}

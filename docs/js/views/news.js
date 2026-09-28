import { api, loadMeta } from '../core/api.js';
import { el, safeUrl, stat } from '../core/dom.js';
import { fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { render } from '../router.js';

// ---------------- News Sentiment loader ----------------
export async function loadNews(r) {
  state.newsActiveTab = r.newsTab || 'headlines';
  state.newsTicker = r.newsTicker || null;
  state.error = null;
  state.loading = true;
  try {
    await loadMeta();
    const [meta, headlines, signals] = await Promise.all([
      api('/api/news/meta'),
      api('/api/news/headlines'),
      api('/api/news/signals'),
    ]);
    state.newsMeta = meta;
    state.newsHeadlines = headlines;
    state.newsSignals = signals;
    if (state.newsActiveTab === 'ticker' && state.newsTicker) {
      state.newsTickerDetail = await api(`/api/news/tickers/${state.newsTicker}`);
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- render ----------------
export function renderNews() {
  const wrap = el('div', { class: 'section' });

  if (!state.newsMeta && !state.newsHeadlines) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading news sentiment data…'));
    return wrap;
  }

  const m = state.newsMeta || {};
  const headlines = state.newsHeadlines || { headlines: [] };
  const signals = state.newsSignals || { bullish: [], bearish: [] };

  // Stats row
  const dateFmt = fmtDateISO(m.latest_date);
  const sigDate = fmtDateISO(signals.latest_date);
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('As of', dateFmt));
  stats.appendChild(stat('Headlines', m.total_headlines || 0, 'brass'));
  stats.appendChild(stat('Sources', m.sources ? m.sources.length : 0));
  stats.appendChild(stat('Signals', sigDate, 'brass'));
  const bullishN = (signals.bullish || []).length;
  const bearishN = (signals.bearish || []).length;
  stats.appendChild(stat('Bullish', bullishN, 'green'));
  stats.appendChild(stat('Bearish', bearishN, 'red'));
  if (m.last_ingestion) {
    stats.appendChild(stat('Updated', fmtDateISO(m.last_ingestion.started_at), 'brass'));
  }
  wrap.appendChild(stats);

  // Sources badge
  if (m.sources && m.sources.length) {
    const badgeWrap = el('div', { class: 'badge-row' });
    for (const src of m.sources) {
      badgeWrap.appendChild(el('span', { class: 'badge' }, src));
    }
    wrap.appendChild(badgeWrap);
  }

  // Tabs
  const tabs = el('div', { class: 'tabs' });
  const tabLabels = [
    { key: 'headlines', label: 'Headlines' },
    { key: 'signals',   label: 'Signals' },
    { key: 'ticker',    label: state.newsTicker || 'Ticker' },
  ];
  for (const t of tabLabels) {
    if (t.key === 'ticker' && !state.newsTicker) continue;
    tabs.appendChild(el('div', {
      class: 'tab' + (state.newsActiveTab === t.key ? ' active' : ''),
      onclick: () => {
        if (t.key === 'ticker' && !state.newsTicker) {
          const tkr = prompt('Enter ticker symbol (e.g. AAPL):');
          if (tkr) {
            state.newsTicker = tkr.trim().toUpperCase();
            state.newsActiveTab = 'ticker';
            state.newsTickerDetail = null;
            location.hash = '#/news/' + state.newsTicker;
            return;
          }
          return;
        }
        state.newsActiveTab = t.key;
        if (state.newsTicker) {
          location.hash = '#/news/' + (t.key === 'ticker' ? state.newsTicker : t.key);
        } else {
          location.hash = '#/news/' + t.key;
        }
      },
    }, t.label));
  }
  wrap.appendChild(tabs);

  // Tab bodies
  if (state.newsActiveTab === 'headlines') {
    wrap.appendChild(renderNewsHeadlines());
  } else if (state.newsActiveTab === 'signals') {
    wrap.appendChild(renderNewsSignals());
  } else if (state.newsActiveTab === 'ticker') {
    wrap.appendChild(renderNewsTicker());
  }

  return wrap;
}

function renderNewsHeadlines() {
  const h = state.newsHeadlines || { headlines: [] };
  const rows = h.headlines || [];
  const wrap = el('div', { class: 'table-wrap' });

  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No headlines available yet.'));
    return wrap;
  }

  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  ['Score', 'Source', 'Headline', 'Tickers'].forEach((hdr, i) => {
    trh.appendChild(el('th', { class: i === 0 ? 'num' : '' }, hdr));
  });
  thead.appendChild(trh);
  table.appendChild(thead);

  const tbody = el('tbody');
  const fmtTime = (s) => s ? String(s).slice(11, 16) : '—';
  for (const row of rows) {
    const tr = el('tr', { style: { '--hl-sentiment': row.sentiment_score } });
    const scoreCls = row.sentiment_label === 'bullish' ? 'num green' :
                     row.sentiment_label === 'bearish' ? 'num red' : 'num mut';
    const arrow = row.sentiment_label === 'bullish' ? '↑' :
                  row.sentiment_label === 'bearish' ? '↓' : '≈';
    const score = row.sentiment_score != null ? row.sentiment_score.toFixed(2) : '0.00';
    tr.appendChild(el('td', { class: scoreCls }, arrow + ' ' + score));
    tr.appendChild(el('td', { class: 'sm mut' }, row.source || '—'));
    const linkCell = el('td');
    const link = el('a', {
      href: safeUrl(row.url),
      target: '_blank',
      rel: 'noopener noreferrer',
      class: 'link',
    }, row.title);
    linkCell.appendChild(link);
    if (row.tickers_mentioned) {
      const chips = row.tickers_mentioned.split(',').map(t => el('span', { class: 'ticker-chip' }, t.trim()));
      linkCell.appendChild(el('div', { class: 'ticker-chips' }, ...chips));
    }
    tr.appendChild(linkCell);
    tr.appendChild(el('td', { class: 'mono sm mut' }, row.tickers_mentioned || '—'));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderNewsSignals() {
  const s = state.newsSignals || { latest_date: null, bullish: [], bearish: [] };
  const wrap = el('div', { class: 'table-wrap' });

  if (!s.bullish?.length && !s.bearish?.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      'No significant sentiment signals. Tickers need ≥2 headlines with avg sentiment ≥0.15 (bullish) or ≤−0.15 (bearish).'));
    return wrap;
  }

  const dateFmt = fmtDateISO(s.latest_date);
  wrap.appendChild(el('div', { class: 'section-title' }, 'Signals as of ' + dateFmt));

  function renderSignalTable(label, rows, signClass) {
    if (!rows || !rows.length) return null;
    const block = el('div', { class: 'signal-block' });
    block.appendChild(el('h4', { class: 'signal-label ' + signClass }, label));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['Ticker', 'Headlines', 'Avg', '↑ Bull', '↓ Bear'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? '' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of rows) {
      const tr = el('tr');
      const tickerLink = el('a', {
        href: '#/news/' + row.ticker,
        class: 'ticker-link',
        onclick: (e) => {
          e.preventDefault();
          state.newsActiveTab = 'ticker';
          state.newsTicker = row.ticker;
          state.newsTickerDetail = null;
          location.hash = '#/news/' + row.ticker;
          render();
        },
      }, row.ticker);
      tr.appendChild(el('td', {}, tickerLink));
      tr.appendChild(el('td', { class: 'num' }, row.headline_count));
      const avgCls = row.avg_sentiment > 0 ? 'num green' : 'num red';
      tr.appendChild(el('td', { class: avgCls },
        (row.avg_sentiment > 0 ? '+' : '') + (row.avg_sentiment || 0).toFixed(2)));
      tr.appendChild(el('td', { class: 'num green' }, row.bullish_count || 0));
      tr.appendChild(el('td', { class: 'num red' }, row.bearish_count || 0));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    block.appendChild(table);
    return block;
  }

  const b = renderSignalTable('Bullish', s.bullish, 'green');
  if (b) wrap.appendChild(b);
  const be = renderSignalTable('Bearish', s.bearish, 'red');
  if (be) wrap.appendChild(be);

  return wrap;
}

function renderNewsTicker() {
  const d = state.newsTickerDetail;
  const wrap = el('div', { class: 'table-wrap' });

  if (!d) {
    wrap.appendChild(el('div', { class: 'empty' }, 'Loading ticker data…'));
    return wrap;
  }

  if (!d.history?.length && !d.headlines?.length) {
    wrap.appendChild(el('div', { class: 'empty' },
      `No news sentiment data for ${d.ticker} yet. Try another ticker.`));
    return wrap;
  }

  // History table
  if (d.history && d.history.length) {
    wrap.appendChild(el('h4', { class: 'signal-label brass' }, d.ticker + ' — Daily Sentiment History'));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['Date', 'Headlines', 'Avg Sentiment', '↑', '↓', '≈'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? 'mono' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of d.history.reverse()) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'mono sm' }, fmtDateISO(row.date)));
      tr.appendChild(el('td', { class: 'num' }, row.headline_count));
      const avgCls = row.avg_sentiment > 0.15 ? 'num green' :
                     row.avg_sentiment < -0.15 ? 'num red' : 'num mut';
      tr.appendChild(el('td', { class: avgCls },
        (row.avg_sentiment > 0 ? '+' : '') + (row.avg_sentiment || 0).toFixed(3)));
      tr.appendChild(el('td', { class: 'num green' }, row.bullish_count || 0));
      tr.appendChild(el('td', { class: 'num red' }, row.bearish_count || 0));
      tr.appendChild(el('td', { class: 'num mut' }, row.neutral_count || 0));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
    d.history.reverse(); // restore
  }

  // Headlines table
  if (d.headlines && d.headlines.length) {
    wrap.appendChild(el('h4', { class: 'signal-label brass' }, d.ticker + ' — Recent Headlines'));
    const table = el('table');
    const thead = el('thead');
    const trh = el('tr');
    ['', 'Headline', 'Sentiment'].forEach((h, i) => {
      trh.appendChild(el('th', { class: i === 0 ? 'sm mut' : i === 1 ? '' : 'num' }, h));
    });
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    for (const row of d.headlines) {
      const tr = el('tr');
      tr.appendChild(el('td', { class: 'sm mut' }, row.source || '—'));
      const link = el('a', {
        href: safeUrl(row.url),
        target: '_blank',
        rel: 'noopener noreferrer',
        class: 'link',
      }, row.title);
      tr.appendChild(el('td', {}, link));
      const scoreCls = row.sentiment_label === 'bullish' ? 'num green' :
                       row.sentiment_label === 'bearish' ? 'num red' : 'num mut';
      const arrow = row.sentiment_label === 'bullish' ? '↑' :
                    row.sentiment_label === 'bearish' ? '↓' : '≈';
      const score = row.sentiment_score != null ? row.sentiment_score.toFixed(2) : '0.00';
      tr.appendChild(el('td', { class: scoreCls }, arrow + ' ' + score));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  return wrap;
}

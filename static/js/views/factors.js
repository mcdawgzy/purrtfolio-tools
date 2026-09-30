import { api, loadMeta } from '../core/api.js';
import { CHART_COLORS, destroyAllCharts, createBarChart, cssVar } from '../core/charts.js';
import { el, stat } from '../core/dom.js';
import { fmtUSD, fmtNum, fmtPct, fmtDateISO } from '../core/format.js';
import { state } from '../core/state.js';
import { setHash } from '../router.js';

export async function loadFactors(r) {
  state.error = null;
  state.loading = true;
  state.factorActiveTab = r.factorTab || 'drift';
  // 13F data is quarterly/static — cache drift + crowded on first load;
  // only (re)fetch the per-ticker detail when drilling into a ticker.
  const cached = state.factorExposure && state.crowdedTrades;
  if (!r.factorTicker && cached && state.factorActiveTab !== 'ticker') {
    state.loading = false;
    return;
  }
  try {
    await loadMeta();
    if (state.factorActiveTab === 'ticker') {
      // Batch meta + ticker detail in parallel (404 on ticker is not an error)
      const [meta, tickerData] = await Promise.all([
        api('/api/factors/meta'),
        api('/api/factors/tickers/' + r.factorTicker).catch(e => {
          if (e.message && e.message.includes('404')) return null;
          throw e;
        }),
      ]);
      state.factorMeta = meta;
      state.factorTicker = tickerData;
    } else {
      state.factorMeta = await api('/api/factors/meta');
    }
    if (state.factorActiveTab === 'drift' && !state.factorExposure) {
      state.factorExposure = await api('/api/factors/exposure');
    }
    if (state.factorActiveTab === 'crowded' && !state.crowdedTrades) {
      state.crowdedTrades = await api('/api/factors/crowded');
    }
  } catch (e) {
    state.error = e.message;
  } finally {
    state.loading = false;
  }
}

// ---------------- factor helpers ----------------
function factorColorHex(dimKey, bucket) {
  if (dimKey === 'size') return bucket === 'Large' ? CHART_COLORS.green
    : bucket === 'Mid' ? CHART_COLORS.brass
    : bucket === 'Small' ? CHART_COLORS.red : CHART_COLORS.dim;
  if (dimKey === 'value_growth') return bucket === 'Value' ? CHART_COLORS.green
    : bucket === 'Growth' ? CHART_COLORS.cyan
    : bucket === 'Blend' ? CHART_COLORS.brass : CHART_COLORS.dim;
  if (dimKey === 'momentum') return bucket === 'Momentum' ? CHART_COLORS.green
    : bucket === 'Contrarian' ? CHART_COLORS.red
    : bucket === 'Neutral' ? CHART_COLORS.brass : CHART_COLORS.dim;
  return CHART_COLORS.brass;
}

function bucketClass(dimKey, bucket) {
  if (dimKey === 'size') return bucket === 'Large' ? 'green'
    : bucket === 'Mid' ? 'brass' : bucket === 'Small' ? 'red' : 'dim';
  if (dimKey === 'value_growth') return bucket === 'Value' ? 'green'
    : bucket === 'Growth' ? 'brass' : bucket === 'Blend' ? 'brass' : 'dim';
  if (dimKey === 'momentum') return bucket === 'Momentum' ? 'green'
    : bucket === 'Contrarian' ? 'red' : bucket === 'Neutral' ? 'brass' : 'dim';
  return 'brass';
}

function dominantBucket(breakdown, order) {
  let best = order[0], bestPct = -1;
  for (const b of order) {
    const p = breakdown[b] || 0;
    if (p > bestPct) { bestPct = p; best = b; }
  }
  return { bucket: best, pct: bestPct };
}

// ---------------- Factor Exposure view ----------------
export function renderFactors() {
  destroyAllCharts();
  const wrap = el('div', { class: 'section' });
  const meta = state.factorMeta || {};

  // stats bar
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Quarter', fmtDateISO(meta.quarter) || '—'));
  stats.appendChild(stat('Coverage', meta.coverage_pct != null ? meta.coverage_pct + '%' : '—'));
  stats.appendChild(stat('Classified', meta.classified_tickers || 0));
  wrap.appendChild(stats);

  // tab bar
  const TAB_DEFS = [
    { key: 'drift', label: 'Style Drift' },
    { key: 'crowded', label: 'Crowded Trades' },
  ];
  const tabBar = el('div', { class: 'tabs' });
  for (const t of TAB_DEFS) {
    const active = state.factorActiveTab === t.key ? ' active' : '';
    tabBar.appendChild(el('a', {
      class: 'tab' + active,
      onclick: () => {
        state.factorActiveTab = t.key;
        setHash(t.key === 'drift' ? '#/factors' : '#/factors/' + t.key);
      },
    }, t.label));
  }
  wrap.appendChild(tabBar);

  if (meta.ready === false) {
    wrap.appendChild(el('div', { class: 'empty' },
      'Factor data table not yet populated. Run the enrich_factors cron job over the latest 13F quarter.'));
    return wrap;
  }

  if (state.factorActiveTab === 'crowded') {
    wrap.appendChild(renderCrowdedTrades());
  } else if (state.factorActiveTab === 'ticker' && state.factorTicker) {
    wrap.appendChild(renderFactorTicker());
  } else {
    wrap.appendChild(renderFactorDrift());
  }
  return wrap;
}

function renderFactorDrift() {
  const exp = state.factorExposure;
  if (!exp) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No factor exposure data available yet.'));
  }

  const wrap = el('div');

  wrap.appendChild(el('div', { class: 'hint' },
    `Portfolio-value-weighted exposure for the latest 13F quarter (${fmtDateISO(exp.quarter)}). ` +
    `${exp.coverage_pct}% of ${fmtUSD(exp.total_aum_usd)} total AUM classified across ` +
    `${exp.classified_tickers} tickers.`));

  // one section per factor dimension
  for (const dim of exp.dimensions || []) {
    const sec = el('div', { class: 'section', style: { marginBottom: '20px' } });
    sec.appendChild(el('h3', { style: { marginTop: '0' } }, dim.label));

    // bar chart
    const canvas = el('canvas', {
      id: 'fc-' + dim.key,
      width: '400',
      height: '200',
      style: { width: '100%', height: '200px' },
    });
    sec.appendChild(canvas);
    setTimeout(() => {
      const labels = dim.overall.map(r => r.bucket);
      const data = {
        labels,
        datasets: [{
          label: 'Portfolio %',
          data: dim.overall.map(r => r.pct),
          backgroundColor: dim.overall.map(r => factorColorHex(dim.key, r.bucket)),
          borderColor: cssVar('--bg'),
          borderWidth: 0,
        }],
      };
      createBarChart('fc-' + dim.key, data, { indexAxis: 'y',
        scales: {
          x: { beginAtZero: true, max: 100, grid: { display: false } },
          y: { grid: { display: false } },
        },
        plugins: { tooltip: {
          callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed.x.toFixed(1)}%` }
        }},
      });
    }, 0);

    sec.appendChild(renderFactorTable(dim));
    wrap.appendChild(sec);
  }

  // strategy-tilt summary table
  wrap.appendChild(renderStrategyTilt(exp));
  return wrap;
}

function renderFactorTable(dim) {
  const wrap = el('div', { class: 'table-wrap' });
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  const cols = [{ l: 'Bucket', c: '' }, { l: 'Portfolio $', c: 'num' },
                { l: '%', c: 'num' }, { l: 'Tickers', c: 'num' },
                { l: 'Funds', c: 'num' }];
  for (const c of cols) trh.appendChild(el('th', { class: c.c }, c.l));
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of dim.overall) {
    const tr = el('tr');
    tr.appendChild(el('td', { class: bucketClass(dim.key, r.bucket) }, r.bucket));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.value_usd)));
    tr.appendChild(el('td', { class: 'num' }, r.pct.toFixed(1) + '%'));
    tr.appendChild(el('td', { class: 'num' }, r.tickers || 0));
    tr.appendChild(el('td', { class: 'num' }, r.holders || 0));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderStrategyTilt(exp) {
  const wrap = el('div', { class: 'section' });
  wrap.appendChild(el('h3', {}, 'Strategy Tilt'));
  const dims = exp.dimensions || [];
  // build per-strategy breakdown map
  const stratMap = {};
  for (const dim of dims) {
    for (const s of dim.by_strategy || []) {
      if (!stratMap[s.strategy]) stratMap[s.strategy] = { aum: 0, buckets: {} };
      stratMap[s.strategy].buckets[dim.key] = s.breakdown || {};
      if (s.aum_usd > (stratMap[s.strategy].aum || 0)) {
        stratMap[s.strategy].aum = s.aum_usd;
      }
    }
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  for (const h of ['Strategy', 'AUM', 'Size', 'Value/Growth', 'Momentum']) {
    trh.appendChild(el('th', { class: h === 'AUM' ? 'num' : '' }, h));
  }
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  const strategies = Object.keys(stratMap).sort();
  if (!strategies.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No strategy-level data.'));
    return wrap;
  }
  for (const strat of strategies) {
    const sm = stratMap[strat];
    const tr = el('tr');
    tr.appendChild(el('td', {}, strat));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(sm.aum)));
    for (const dim of dims) {
      const d = dominantBucket(sm.buckets[dim.key] || {}, dim.buckets);
      const cell = d.pct > 0 ? `${d.bucket} (${d.pct.toFixed(1)}%)` : '—';
      tr.appendChild(el('td', { class: 'num ' + bucketClass(dim.key, d.bucket) }, cell));
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  wrap.appendChild(el('div', { class: 'hint' },
    'Dominant factor bucket per strategy (portfolio-value-weighted). Click any ticker below in Crowded Trades to drill down.'));
  return wrap;
}

function renderCrowdedTrades() {
  const data = state.crowdedTrades;
  if (!data) {
    return el('div', { class: 'table-wrap' },
      el('div', { class: 'empty' }, 'No crowded-trades data available yet.'));
  }
  const wrap = el('div');
  const stats = el('div', { class: 'stats' });
  stats.appendChild(stat('Quarter', fmtDateISO(data.quarter) || '—'));
  stats.appendChild(stat('Positions', (data.rows || []).length));
  wrap.appendChild(stats);

  const rows = data.rows || [];
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, 'No holdings data for this quarter.'));
    return wrap;
  }
  const table = el('table');
  const thead = el('thead');
  const trh = el('tr');
  for (const h of ['Ticker', 'Name', 'Sector', 'Funds', 'Total $', 'Added', 'Removed']) {
    trh.appendChild(el('th', { class: h === 'Funds' || h === 'Total $' || h === 'Added' || h === 'Removed' ? 'num' : '' }, h));
  }
  thead.appendChild(trh);
  table.appendChild(thead);
  const tbody = el('tbody');
  for (const r of rows) {
    const tr = el('tr', {
      style: { cursor: 'pointer' },
      onclick: () => setHash('#/factors/' + r.ticker),
    });
    tr.appendChild(el('td', { class: 'mono brass' }, r.ticker));
    tr.appendChild(el('td', {}, r.name || '—'));
    tr.appendChild(el('td', {}, r.sector || '—'));
    tr.appendChild(el('td', { class: 'num' }, r.holders || 0));
    tr.appendChild(el('td', { class: 'num' }, fmtUSD(r.total_value)));
    tr.appendChild(el('td', { class: 'num green' }, (r.funds_added || 0) > 0 ? ('+' + (r.funds_added)) : (r.funds_added || 0)));
    tr.appendChild(el('td', { class: 'num red' }, (r.funds_removed || 0) > 0 ? ('−' + (r.funds_removed)) : (r.funds_removed || 0)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);

  wrap.appendChild(el('div', { class: 'hint' },
    'Crowd score ~ funds holding × portfolio weight. Added/Removed = funds that increased/decreased this quarter.'));
  return wrap;
}

function renderFactorTicker() {
  const t = state.factorTicker;
  if (!t) {
    return el('div', { class: 'section' },
      el('div', { class: 'empty' }, 'No factor data for this ticker.'));
  }
  const wrap = el('div');

  // drill header
  const hdr = el('div', { class: 'drill-header' });
  hdr.appendChild(el('a', {
    class: 'back', href: '#/factors/crowded',
    onclick: (e) => { e.preventDefault(); setHash('#/factors/crowded'); },
  }, '← Crowded Trades'));
  hdr.appendChild(el('h2', {}, t.ticker));
  wrap.appendChild(hdr);

  // factor classification table
  const info = el('div', { class: 'table-wrap' });
  const itable = el('table');
  const itbody = el('tbody');
  const irows = [
    ['Size', fmtUSD(t.market_cap), 'size', t.size_bucket],
    ['Value / Growth', '\u2014', 'value_growth', t.value_bucket],
    ['Momentum (20d ROC)', t.momentum_roc_20d != null ? fmtPct(t.momentum_roc_20d) : '\u2014', 'momentum', t.momentum_bucket],
    ['P/E (trailing)', t.pe_ratio != null ? t.pe_ratio.toFixed(2) : '\u2014', '', ''],
    ['P/B', t.price_to_book != null ? t.price_to_book.toFixed(2) : '\u2014', '', ''],
  ];
  for (const [k, v, dimKey, bucket] of irows) {
    const tr = el('tr');
    tr.appendChild(el('td', {}, k));
    tr.appendChild(el('td', { class: 'num' }, v));
    tr.appendChild(el('td', { class: dimKey ? bucketClass(dimKey, bucket) : 'dim' }, bucket || '\u2014'));
    itbody.appendChild(tr);
  }
  itable.appendChild(itbody);
  info.appendChild(itable);
  wrap.appendChild(info);

  // holders table
  const holders = t.holders || [];
  wrap.appendChild(el('h4', {}, `Fund Holders (${holders.length})`));
  if (holders.length) {
    const htable = el('table');
    const hthead = el('thead');
    const htrh = el('tr');
    for (const h of ['Fund', 'Strategy', 'Position $', '% of Fund', 'Shares']) {
      htrh.appendChild(el('th', { class: ['Position $','% of Fund','Shares'].includes(h) ? 'num' : '' }, h));
    }
    hthead.appendChild(htrh);
    htable.appendChild(hthead);
    const htbody = el('tbody');
    for (const h of holders) {
      const tr = el('tr', {
        style: { cursor: 'pointer' },
        onclick: () => setHash('#/fund/' + h.fund_cik),
      });
      tr.appendChild(el('td', {}, h.fund_name || '—'));
      tr.appendChild(el('td', {}, h.strategy || '—'));
      tr.appendChild(el('td', { class: 'num' }, fmtUSD(h.position_value)));
      tr.appendChild(el('td', { class: 'num' }, h.pct_of_fund != null ? h.pct_of_fund.toFixed(2) + '%' : '—'));
      tr.appendChild(el('td', { class: 'num' }, fmtNum(h.shares)));
      htbody.appendChild(tr);
    }
    htable.appendChild(htbody);
    wrap.appendChild(htable);
  }
  return wrap;
}

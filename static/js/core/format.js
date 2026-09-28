// Display formatters (pure functions).

function formatStrategy(s) {
  if (!s) return '—';
  const map = {
    'activist': 'Activist',
    'index_passive': 'Index Passive',
    'macro_all_weather': 'Macro All-Weather',
    'quant_multi_strat': 'Quant Multi-Strat',
    'sovereign': 'Sovereign',
    'tech_growth': 'Tech Growth',
    'value_concentrated': 'Value Concentrated',
  };
  return map[s] || s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function fmtUSD(n, { compact = true, sign = false } = {}) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  const s = sign && n > 0 ? '+' : (n < 0 ? '−' : '');
  if (compact) {
    if (abs >= 1e12) return `${s}$${(abs / 1e12).toFixed(2)}T`;
    if (abs >= 1e9)  return `${s}$${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6)  return `${s}$${(abs / 1e6).toFixed(1)}M`;
    if (abs >= 1e3)  return `${s}$${(abs / 1e3).toFixed(0)}K`;
  }
  return `${s}$${abs.toLocaleString()}`;
}

export function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString();
}

export function fmtPct(n) {
  if (n === null || n === undefined) return '—';
  const s = n > 0 ? '+' : '';
  return `${s}${n.toFixed(1)}%`;
}

// Compute % of free float: (short_interest_shares / free_float_shares * 100)
function computePctFreeFloat(r) {
  if (!r.free_float_shares || r.free_float_shares <= 0 || !r.current_short) return null;
  return (r.current_short * 100.0 / r.free_float_shares).toFixed(2);
}

export function fmtFreeFloat(r) {
  if (r.pct_of_free_float !== null && r.pct_of_free_float !== undefined) {
    return r.pct_of_free_float.toFixed(2) + '%';
  }
  const pct = computePctFreeFloat(r);
  return pct !== null ? pct + '%' : '—';
}

export function fmtDateISO(s) {
  if (!s) return '—';
  return `${String(s).slice(5, 7)}/${String(s).slice(8, 10)}/${String(s).slice(0, 4)}`;
}

export function fmtDateYMD(s) {
  return s ? String(s).slice(0, 4) + '-' + String(s).slice(5, 7) + '-' + String(s).slice(8, 10) : '—';
}

export function fmtNotional(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1e9)  return sign + '$' + (abs / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6)  return sign + '$' + (abs / 1e6).toFixed(0) + 'M';
  if (abs >= 1e3)  return sign + '$' + (abs / 1e3).toFixed(0) + 'K';
  return sign + '$' + abs.toLocaleString();
}

// The single shared app state object. Mutated in place by loaders and views.

export const state = {
  view:   'funds',
  fund:   null,             // current fund detail (cik, name, ...)
  ticker: null,             // current ticker detail
  meta:   null,
  funds:  [],
  holdings: { rows: [], total: 0, quarter: null },
  changes:  { rows: [], total: 0, quarter: null },
  fundTab: 'holdings',      // 'holdings' | 'changes'
  holdingsSort: { col: 'value', dir: 'desc' },
  holdingsFilters: { min_value: '', ticker: '', limit: 100, offset: 0 },
  changesFilters:  { status: '', min_abs_value: '', limit: 100, offset: 0 },
  consensus: { buys: [], sells: [], quarter: null, min_funds: 2 },
  loading: false,
  error:  null,
  siMeta: null,
  siLatest: { rows: [], total: 0, limit: 100, min_short: 1_000_000 },
  siSignals: null,
  siTicker: null,
  siActiveTab: 'latest',   // 'latest' | 'signals' | 'history'
  snapshot: null,           // latest market snapshot metadata
  econMeta: null,           // economic calendar metadata
  econEvents: [],           // economic calendar events
  econDaysAhead: 30,        // lookahead window
  econImpact: '',           // '' | 'high' | 'medium' | 'low'
  econCategory: '',         // filter by category
  insiderMeta: null,        // insider trading metadata
  insiderLatest: { rows: [], total: 0, limit: 100, min_value: '' },
  insiderSignals: null,     // top buys / sells / officer trades
  insiderTicker: null,      // single ticker full history
  insiderActiveTab: 'latest',  // 'latest' | 'signals' | 'ticker'
  // Price Momentum
  momMeta: null,
  momRankings: { rows: [], total: 0 },
  momVolumeSpikes: { rows: [], total: 0 },
  momConsolidation: { rows: [], total: 0 },
  momGaps: { rows: [], total: 0 },
  momTickerHistory: null,
  momActiveTab: 'rankings',   // 'rankings' | 'volume-spikes' | 'consolidation' | 'gaps' | 'ticker'
  // Correlation Matrix
  corrMeta: null,
  corrMatrix: null,
  corrPivotView: null,        // correlation to a specific pivot ticker
  corrActiveTab: 'matrix',   // 'matrix' | 'pivot'
  // Factor Exposure / Style Drift
  factorMeta: null,
  factorExposure: null,      // {quarter, dimensions, coverage_pct, ...}
  crowdedTrades: null,       // {quarter, rows}
  factorActiveTab: 'drift',  // 'drift' | 'crowded' | 'ticker'
  factorTicker: null,
  // Put/Call Ratio
  pcrMeta: null,
  pcrLatest: null,        // { latest_date, rows: [...] }
  pcrSignals: null,
  pcrHistory: null,       // { series, rows: [...] }
  pcrActiveTab: 'latest',  // 'latest' | 'signals' | 'history'
  pcrHistorySeries: 'TOTAL',
  pcrHistoryDays: 60,
  // IV Rank & IV Percentile
  ivMeta: null,
  ivLatest: { rows: [] },
  ivHistory: null,
  ivActiveTab: 'latest',
  ivSelectedTicker: null,
  ivHistoryDays: 300,
  // Unusual Activity / Dark Pool
  uaMeta: null,
  uaLatest: { rows: [] },
  uaHistory: null,
  uaActiveTab: 'latest',   // 'latest' | 'history'
  uaSelectedTicker: null,
  // News Sentiment
  newsMeta: null,        // { latest_date, total_headlines, sources, ... }
  newsHeadlines: null,   // { latest_date, headlines: [...] }
  newsSignals: null,     // { latest_date, bullish: [...], bearish: [...] }
  newsTickerDetail: null,// { ticker, history: [...], headlines: [...] }
  newsActiveTab: 'headlines',  // 'headlines' | 'signals' | 'ticker'
  newsTicker: null,
  // Stock Screener
  screenerMeta: null,
  screenerResults: { rows: [], total: 0 },
  screenerFilters: {
    sector: '', min_price: '', max_price: '',
    min_volume: '', min_market_cap: '',
    etf_only: false, stocks_only: false,
  },
  screenerSort: { col: 'market_cap', dir: 'desc' },
  // Famous Trader Quotes
  quoteMeta: null,
  quoteList: [],
  quoteCategory: '',
  // Earnings Revision Momentum
  ermMeta: null,
  ermRows: [],
  // Crowded Trades Scanner
  ctMeta: null,
  ctLatest: null,
};

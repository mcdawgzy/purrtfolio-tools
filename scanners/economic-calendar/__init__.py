"""Economic Calendar scanner — free, no-paid-API data sources.

Sources:
  - FOMC meetings: scraped from federalreserve.gov (no API key)
  - US economic releases (CPI, PPI, NFP, GDP, etc.): Finnhub free API
    (optional; falls back to a curated static list when key is absent)
  - ECB / BOE / BOJ rate decision dates: scraped from central bank websites
    + a curated static fallback

Data is stored in the shared purrtfolio.db in a new `economic_events` table.
"""

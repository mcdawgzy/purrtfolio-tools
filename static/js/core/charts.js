// Chart.js lazy loading, shared palette, and chart-instance bookkeeping.

import { el } from './dom.js';
import { fmtUSD } from './format.js';

// Lazy-load Chart.js — only fetched when a chart view is first rendered,
// so non-chart pages don't pay the 205KB download cost.
let _chartJsPromise = null;

export function ensureChartJS() {
  if (typeof Chart !== 'undefined') return Promise.resolve();
  if (_chartJsPromise) return _chartJsPromise;
  _chartJsPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = './chart.min.js';
    script.onload = () => { applyChartDefaults(); resolve(); };
    script.onerror = () => { reject(new Error('Failed to load chart.min.js')); };
    document.head.appendChild(script);
  });
  return _chartJsPromise;
}

// Canvas can't resolve var(--x), so read the current theme's token values at
// chart-creation time. Charts are rebuilt on every render, so a theme switch is
// picked up on the next render (see main.js).
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Chart.js globals: body font and muted text/grid colours from the theme.
function applyChartDefaults() {
  Chart.defaults.font.family = cssVar('--font');
  Chart.defaults.color = cssVar('--text-dim');
  Chart.defaults.borderColor = cssVar('--line');
}

// Chart color palette - hex values that read on both the light and dark theme.
export const CHART_COLORS = {
  brass: '#C86F2E',
  green: '#00A86B',
  red: '#D23B41',
  blue: '#3B82F6',
  pink: '#EC4899',
  orange: '#F97316',
  teal: '#14B8A6',
  purple: '#A855F7',
  amber: '#EAB308',
  cyan: '#22D3EE',
  indigo: '#6366F1',
  emerald: '#10B981',
  rose: '#F43F5E',
};

export const CHART_COLOR_ARRAY = [
  CHART_COLORS.brass,
  CHART_COLORS.green,
  CHART_COLORS.red,
  CHART_COLORS.blue,
  CHART_COLORS.pink,
  CHART_COLORS.orange,
  CHART_COLORS.teal,
  CHART_COLORS.purple,
  CHART_COLORS.amber,
  CHART_COLORS.cyan,
  CHART_COLORS.indigo,
  CHART_COLORS.emerald,
  CHART_COLORS.rose,
];

// Chart instances stored to allow destruction on re-render
export const charts = {};

export function destroyAllCharts() {
  Object.keys(charts).forEach(key => {
    if (charts[key]) {
      charts[key].destroy();
      delete charts[key];
    }
  });
}

export function generateColorShades(baseColor, count) {
  // Use the base color directly with slight variations for better visibility
  // Chart.js works better with explicit color arrays
  return CHART_COLOR_ARRAY.slice(0, count);
}

export async function createPieChart(canvasId, data, options = {}) {
  await ensureChartJS();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (charts[canvasId]) {
    charts[canvasId].destroy();
  }
  // Explicit colors for Chart.js (CSS variables don't work reliably in canvas)
  const TEXT_COLOR = cssVar('--text');
  const TEXT_DIM = cssVar('--text-dim');
  const PANEL = cssVar('--panel');
  const LINE = cssVar('--line');
  charts[canvasId] = new Chart(ctx, {
    type: 'pie',
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            font: { family: 'ui-monospace, SFMono-Regular, monospace', size: 10 },
            color: TEXT_COLOR,
            padding: 8,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: PANEL,
          titleColor: TEXT_COLOR,
          bodyColor: TEXT_DIM,
          borderColor: LINE,
          borderWidth: 1,
          padding: 12,
          callbacks: {
            label: (ctx) => {
              const label = ctx.label || '';
              const value = ctx.parsed;
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((value / total) * 100).toFixed(1);
              return `${label}: ${pct}% (${fmtUSD(value)})`;
            },
          },
        },
      },
      ...options,
    },
  });
  return charts[canvasId];
}

export async function createBarChart(canvasId, data, options = {}) {
  await ensureChartJS();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (charts[canvasId]) {
    charts[canvasId].destroy();
  }
  const TEXT_COLOR = cssVar('--text');
  const TEXT_DIM = cssVar('--text-dim');
  const LINE = cssVar('--line');
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: data,
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar('--panel'),
          titleColor: TEXT_COLOR,
          bodyColor: TEXT_DIM,
          borderColor: LINE,
          borderWidth: 1,
          padding: 12,
        },
      },
      scales: {
        x: {
          ticks: { color: TEXT_COLOR, font: { size: 11 } },
          grid: { color: LINE },
        },
        y: {
          ticks: { color: TEXT_DIM, font: { size: 10 } },
          grid: { color: LINE },
        },
      },
      ...options,
    },
  });
  return charts[canvasId];
}

// ---- Pie Chart helper ----
  async function renderPieChart(container, data, labels, options = {}) {
    await ensureChartJS();
    const canvas = el('canvas', { width: 300, height: 300 });
    container.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: [
            CHART_COLORS.brass, CHART_COLORS.green, CHART_COLORS.red, CHART_COLORS.blue, '#8B5CF6',
            CHART_COLORS.pink, '#06B6D4', '#84CC16', CHART_COLORS.orange, CHART_COLORS.indigo,
          ],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: {
            position: 'right',
            labels: {
              color: cssVar('--text'),
              font: { size: 11, family: cssVar('--font') },
              padding: 12,
              usePointStyle: true,
              pointStyle: 'circle',
            },
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const pct = ((context.raw / total) * 100).toFixed(1);
                return `${context.label}: ${pct}% (${fmtUSD(context.raw, {compact: true})})`;
              },
            },
          },
        },
      },
    });
  }
